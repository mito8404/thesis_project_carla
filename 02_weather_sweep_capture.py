"""
02_weather_sweep_capture.py  (STAGE 2 of 3 — run via run_pipeline.sh, or standalone)

Replay the recording made by 01_record_scenario.py once per weather preset,
capturing camera frames each time. Because every replay reproduces the EXACT
same actor trajectories from the log, the only thing that differs between
output folders is the weather — cars, bicycles, and pedestrians are in
identical positions frame-for-frame.

Bonus: frames are saved by simulation frame number (image.frame), so
frame_000123.png in every weather folder is the *same simulated instant*.
That makes this directly usable for paired cross-weather comparisons later
(e.g. feeding matched frames into SAM3, or a domain-adaptation setup like
Rote-DA's).

Weather presets are discovered dynamically from carla.WeatherParameters
(every static preset CARLA ships), so this automatically covers "every
weather scenario CARLA can do" for whatever version you're running, without
hardcoding a preset list that could drift across CARLA versions.

IMPORTANT — actor cleanup: the CARLA server is a persistent process that
does NOT reset itself between script runs or between replay_file() calls.
If actors from a previous (possibly crashed) run are left alive, a new
replay spawns a second set directly on top of them, which is what causes
vehicles to overlap/pile up and get violently shoved apart by physics
("flying"). This script explicitly destroys every vehicle/walker/sensor
actor (a) once at startup, in case a previous crashed run left a mess, and
(b) after every single weather iteration — success, failure, or Ctrl+C —
via try/finally, so runs can never contaminate each other.

Usage:
    ./CarlaUE4.sh -quality-level=Epic   # server, separate terminal
    python3 02_weather_sweep_capture.py --map Town10HD_Opt \
        --log scenario01.log --duration 40 --fps 10 \
        --camera-mode ego --out ./captures

Use --replay-start to skip a recorded "warmup" period (see run_pipeline.sh),
and --only to run a curated subset of weather presets instead of all of them,
e.g. --only ClearNoon ClearNight HardRainNoon HardRainNight WetNight for a
day/night/rain contrast set rather than a full sweep.
"""

import argparse
import os
import time

import carla


def discover_weather_presets():
    presets = {}
    for name in dir(carla.WeatherParameters):
        if name.startswith('_'):
            continue
        value = getattr(carla.WeatherParameters, name)
        if isinstance(value, carla.WeatherParameters):
            presets[name] = value
    return dict(sorted(presets.items()))


def destroy_all_actors(client, world):
    """Nuke every vehicle/walker/controller/sensor currently in the world.
    Safe to call even if the world is already empty. Called before the
    sweep starts (in case a previous crashed run left actors alive) and
    after every single weather iteration."""
    actors = world.get_actors()
    to_destroy = list(actors.filter('vehicle.*')) + \
        list(actors.filter('walker.pedestrian.*')) + \
        list(actors.filter('controller.ai.walker')) + \
        list(actors.filter('sensor.*'))
    if not to_destroy:
        return
    for a in to_destroy:
        try:
            if a.type_id.startswith('controller.'):
                a.stop()
        except RuntimeError:
            pass
    client.apply_batch([carla.command.DestroyActor(a.id) for a in to_destroy])
    world.tick()
    print(f"  (cleaned up {len(to_destroy)} leftover actors)")


def find_hero(world, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for actor in world.get_actors().filter('vehicle.*'):
            if actor.attributes.get('role_name') == 'hero':
                return actor
        world.tick()
    return None


def capture_one_weather(client, world, args, weather_name, weather_params, bp_lib):
    out_dir = os.path.join(args.out, weather_name)
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n=== {weather_name} ===")

    camera = None
    try:
        client.replay_file(args.log, args.replay_start, args.duration, 0)
        world.tick()  # let the replay start populating actors

        world.set_weather(weather_params)  # weather is independent of the recording

        cam_bp = bp_lib.find('sensor.camera.rgb')
        cam_bp.set_attribute('image_size_x', str(args.width))
        cam_bp.set_attribute('image_size_y', str(args.height))
        cam_bp.set_attribute('fov', '90')
        cam_bp.set_attribute('sensor_tick', str(1.0 / args.fps))

        if args.camera_mode == 'ego':
            hero = find_hero(world)
            if hero is None:
                print(f"  WARNING: hero actor not found for {weather_name}, skipping capture.")
                return
            cam_transform = carla.Transform(carla.Location(x=1.5, z=2.0))  # dashcam-ish mount
            camera = world.spawn_actor(cam_bp, cam_transform, attach_to=hero)
        else:  # fixed
            x, y, z, pitch, yaw, roll = args.camera_transform
            cam_transform = carla.Transform(
                carla.Location(x=x, y=y, z=z),
                carla.Rotation(pitch=pitch, yaw=yaw, roll=roll))
            camera = world.spawn_actor(cam_bp, cam_transform)

        frame_count = 0

        def on_image(image):
            nonlocal frame_count
            image.save_to_disk(os.path.join(out_dir, f"frame_{image.frame:06d}.png"))
            frame_count += 1

        camera.listen(on_image)

        n_ticks = int(args.duration / args.fixed_delta_seconds)
        for _ in range(n_ticks):
            world.tick()

        print(f"  saved {frame_count} frames to {out_dir}")

    finally:
        # Runs on success, on exception, AND on Ctrl+C — this is what
        # prevents the "sensor still alive" abort and actor pile-up.
        if camera is not None:
            try:
                camera.stop()
            except RuntimeError:
                pass
            try:
                camera.destroy()
            except RuntimeError:
                pass
        destroy_all_actors(client, world)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', default=2000, type=int)
    ap.add_argument('--map', default=None,
                     help='Must match the --map used in 01_record_scenario.py.')
    ap.add_argument('--log', required=True)
    ap.add_argument('--replay-start', type=float, default=0.0,
                     help='Seconds into the recording to START playback from. Use this to skip '
                          'the "cold start" seconds right after everyone spawns and simultaneously '
                          'pulls off toward the nearest intersection, before traffic has settled '
                          'into a naturally spread-out flow — e.g. record --duration 50 and capture '
                          'with --replay-start 10 --duration 40 to use only the settled last 40s.')
    ap.add_argument('--duration', type=float, default=40.0,
                     help='Playback length from --replay-start. (replay-start + duration) must be '
                          '<= the recorded duration.')
    ap.add_argument('--fixed-delta-seconds', type=float, default=0.05,
                     help='Must match the recording run for frame numbers to line up.')
    ap.add_argument('--fps', type=float, default=10.0, help='Camera capture rate.')
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--height', type=int, default=720)
    ap.add_argument('--camera-mode', choices=['ego', 'fixed'], default='ego',
                     help="'ego' = dashcam mounted on the hero vehicle (needs role_name='hero' "
                          "from the record step). 'fixed' = static world-space camera, "
                          "use --camera-transform.")
    ap.add_argument('--camera-transform', type=float, nargs=6,
                     default=[0, 0, 10, -30, 0, 0],
                     metavar=('X', 'Y', 'Z', 'PITCH', 'YAW', 'ROLL'),
                     help='Only used with --camera-mode fixed. Get real coordinates from '
                          'the CARLA spectator or a spawn point on your map.')
    ap.add_argument('--out', default='./captures')
    ap.add_argument('--only', nargs='*', default=None,
                     help='Optional list of preset names to run instead of all of them, '
                          'e.g. --only ClearNoon HardRainNoon ClearNight')
    args = ap.parse_args()

    client = carla.Client(args.host, args.port)
    client.set_timeout(30.0)
    world = client.load_world(args.map) if args.map else client.get_world()

    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = args.fixed_delta_seconds
    world.apply_settings(settings)

    bp_lib = world.get_blueprint_library()

    # Defensive cleanup in case a previous crashed/interrupted run left
    # actors alive in this (persistent) server before we even start.
    print("Clearing any leftover actors from previous runs...")
    destroy_all_actors(client, world)

    presets = discover_weather_presets()
    if args.only:
        presets = {k: v for k, v in presets.items() if k in args.only}
    print(f"Sweeping {len(presets)} weather presets: {list(presets.keys())}")

    os.makedirs(args.out, exist_ok=True)

    try:
        for name, params in presets.items():
            capture_one_weather(client, world, args, name, params, bp_lib)
    except KeyboardInterrupt:
        print("\nInterrupted — cleaning up before exit...")
        destroy_all_actors(client, world)
    finally:
        settings.synchronous_mode = False
        world.apply_settings(settings)

    print("\nDone.")


if __name__ == '__main__':
    main()
