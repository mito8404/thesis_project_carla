#!/usr/bin/env python3
"""
capture_crossing.py -- Deterministic pedestrian-crossing scenario for CARLA 0.9.16.

Scenario: the ego vehicle drives in a straight line toward a crossing. A pedestrian
walks across the road ahead, PAUSES mid-crossing, then continues to the far side.
The ego records the whole event. Everything is scripted and deterministic (sync mode,
fixed timestep, fixed spawn, no random traffic), so frame N is the SAME moment of the
SAME event in every weather condition -- matched pairs for a fair comparison.

Captures, per frame:
    rgb/000000.png   -- camera image
    seg/000000.png   -- CARLA ground-truth semantic segmentation (for scoring SAM 3)

Run ONCE PER CONDITION (server must already be running in another terminal):
    python3 capture_crossing.py --weather clear_day
    python3 capture_crossing.py --weather rain
    python3 capture_crossing.py --weather fog
    python3 capture_crossing.py --weather clear_night
"""

import argparse, os, queue, carla

# --- Output goes to the EXTERNAL drive, never the full root partition ---
BASE_OUT = "/media/its/ElementsSE/carla_capture/clear_night"

WEATHER = {
    "clear_day": carla.WeatherParameters(
        cloudiness=10.0, precipitation=0.0, precipitation_deposits=0.0,
        sun_altitude_angle=70.0, fog_density=0.0, wetness=0.0),
    "clear_night": carla.WeatherParameters(
        cloudiness=10.0, precipitation=0.0, precipitation_deposits=0.0,
        sun_altitude_angle=-90.0, fog_density=0.0, wetness=0.0),
    "rain": carla.WeatherParameters(
        cloudiness=80.0, precipitation=60.0, precipitation_deposits=50.0,
        sun_altitude_angle=45.0, fog_density=5.0, wetness=60.0),
    "hard_rain": carla.WeatherParameters(
        cloudiness=100.0, precipitation=100.0, precipitation_deposits=90.0,
        sun_altitude_angle=30.0, fog_density=10.0, wetness=100.0),
    "fog": carla.WeatherParameters(
        cloudiness=50.0, precipitation=0.0, precipitation_deposits=0.0,
        sun_altitude_angle=45.0, fog_density=60.0, fog_distance=10.0, wetness=0.0),
    "rain_night": carla.WeatherParameters(
        cloudiness=90.0, precipitation=70.0, precipitation_deposits=60.0,
        sun_altitude_angle=-90.0, fog_density=10.0, wetness=80.0),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weather", required=True, choices=list(WEATHER.keys()))
    ap.add_argument("--town", default="Town01")
    ap.add_argument("--spawn", type=int, default=0, help="fixed ego spawn-point index")
    ap.add_argument("--frames", type=int, default=250)
    ap.add_argument("--throttle", type=float, default=0.4)
    # Frame windows that script the pedestrian's walk / pause / walk:
    ap.add_argument("--walk_start", type=int, default=40,  help="frame the ped starts crossing")
    ap.add_argument("--pause_start", type=int, default=90, help="frame the ped stops mid-road")
    ap.add_argument("--pause_end", type=int, default=140,  help="frame the ped resumes")
    args = ap.parse_args()

    out_rgb = os.path.join(BASE_OUT, args.weather, "rgb")
    out_seg = os.path.join(BASE_OUT, args.weather, "seg")
    os.makedirs(out_rgb, exist_ok=True)
    os.makedirs(out_seg, exist_ok=True)

    client = carla.Client("localhost", 2000)
    client.set_timeout(20.0)
    world = client.load_world(args.town)   # reload => identical starting state each run

    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.05    # 20 FPS
    world.apply_settings(settings)
    world.set_weather(WEATHER[args.weather])

    bp = world.get_blueprint_library()
    actors = []
    try:
        # ---------------- Ego vehicle at a FIXED spawn point ----------------
        vehicle_bp = bp.filter("vehicle.tesla.model3")[0]
        spawn = world.get_map().get_spawn_points()[args.spawn]
        vehicle = world.spawn_actor(vehicle_bp, spawn)
        actors.append(vehicle)
        if "night" in args.weather:
            vehicle.set_light_state(carla.VehicleLightState(
                carla.VehicleLightState.LowBeam | carla.VehicleLightState.Position))

        # ---------------- Pedestrian placed ahead, at the roadside ----------------
        # Put the walker ~25 m in front of the ego and ~4 m off to one side,
        # so it will cross left-to-right across the ego's path.
        fwd = spawn.get_forward_vector()
        right = spawn.get_right_vector()
        ped_loc = carla.Location(
            x=spawn.location.x + fwd.x * 25.0 - right.x * 4.0,
            y=spawn.location.y + fwd.y * 25.0 - right.y * 4.0,
            z=spawn.location.z + 1.0)
        walker_bp = bp.filter("walker.pedestrian.0001")[0]
        if walker_bp.has_attribute("is_invincible"):
            walker_bp.set_attribute("is_invincible", "false")
        # face the walker across the road (toward +right)
        ped_yaw = spawn.rotation.yaw + 90.0
        walker = world.spawn_actor(
            walker_bp, carla.Transform(ped_loc, carla.Rotation(yaw=ped_yaw)))
        actors.append(walker)
        # direction unit vector for the crossing (across the road)
        cross_dir = carla.Vector3D(x=right.x, y=right.y, z=0.0)
        walk_speed = 1.4  # m/s, normal walking pace

        # ---------------- Sensors: RGB + ground-truth semantic seg ----------------
        cam_tf = carla.Transform(carla.Location(x=1.5, z=2.4))

        cam_bp = bp.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", "1280")
        cam_bp.set_attribute("image_size_y", "720")
        cam_bp.set_attribute("fov", "90")
        camera = world.spawn_actor(cam_bp, cam_tf, attach_to=vehicle)
        actors.append(camera)
        rgb_q = queue.Queue()
        camera.listen(rgb_q.put)

        seg_bp = bp.find("sensor.camera.semantic_segmentation")
        seg_bp.set_attribute("image_size_x", "1280")
        seg_bp.set_attribute("image_size_y", "720")
        seg_bp.set_attribute("fov", "90")
        seg_cam = world.spawn_actor(seg_bp, cam_tf, attach_to=vehicle)
        actors.append(seg_cam)
        seg_q = queue.Queue()
        seg_cam.listen(seg_q.put)

        # Let physics + sensors settle
        for _ in range(10):
            world.tick()
            rgb_q.get()
            seg_q.get()

        # ---------------- Drive + scripted crossing ----------------
        vehicle.apply_control(carla.VehicleControl(throttle=args.throttle, steer=0.0))
        for i in range(args.frames):
            # Pedestrian state machine: idle -> walk -> pause -> walk
            if args.walk_start <= i < args.pause_start or i >= args.pause_end:
                speed = walk_speed
            else:
                speed = 0.0   # before crossing, and during the mid-road pause
            walker.apply_control(carla.WalkerControl(
                direction=cross_dir, speed=speed))

            world.tick()

            img = rgb_q.get()
            seg = seg_q.get()
            img.save_to_disk(os.path.join(out_rgb, "%06d.png" % i))
            # CityScapes palette makes classes human-readable; raw class IDs are in
            # the red channel if you need exact label values for IoU scoring.
            seg.save_to_disk(os.path.join(out_seg, "%06d.png" % i),
                             carla.ColorConverter.CityScapesPalette)

            if i % 25 == 0:
                print("frame %d / %d  (ped speed %.1f)" % (i, args.frames, speed))

        print("DONE ->", os.path.join(BASE_OUT, args.weather))

    finally:
        for a in actors:
            if a.is_alive:
                a.destroy()
        s = world.get_settings()
        s.synchronous_mode = False
        s.fixed_delta_seconds = None
        world.apply_settings(s)


if __name__ == "__main__":
    main()
