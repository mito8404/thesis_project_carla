"""
01_record_scenario.py  (STAGE 1 of 3 — run via run_pipeline.sh, or standalone)

Spawn a dense, realistic scene (hero vehicle + NPC cars + bicycles + walking
pedestrians) and RECORD it with CARLA's built-in recorder. This log is the
single source of truth for "what moved where, when" — every weather replay
in stage 2 (02_weather_sweep_capture.py) reproduces these exact trajectories.

Run this ONCE per scenario you want. Re-run it (with a new --log name) to
generate a different scenario, then sweep weather over each one separately.

Usage:
    ./CarlaUE4.sh -quality-level=Epic   # server, separate terminal
    python3 01_record_scenario.py --map Town10HD_Opt --duration 40 \
        --log scenario01.log -n 40 -b 10 -w 60 --seed 42

To run in a different part of town, add --center X Y --radius 150 (meters).
Find coordinates by free-flying the CARLA spectator (right-click drag +
WASD in the CARLA window) to wherever you want, then in a second terminal
with the server already running:

    python3 -c "
import carla
w = carla.Client('127.0.0.1', 2000).get_world()
t = w.get_spectator().get_transform()
print(f'--center {t.location.x:.1f} {t.location.y:.1f}')
"
"""

import argparse
import random
import time

import carla


def destroy_all_actors(client, world):
    """Nuke every vehicle/walker/controller/sensor currently in the world.
    Defends against a previous crashed/interrupted run having left actors
    alive in this (persistent) CARLA server."""
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
    print(f"Cleared {len(to_destroy)} leftover actors from a previous run.")


def location_near(world, center, radius, max_tries=50):
    """Sample a random navigable pedestrian location, retrying until it falls
    within `radius` meters (in the XY plane) of `center`. Returns None if no
    such point turns up within max_tries (radius likely too small for this
    part of the navmesh)."""
    cx, cy = center
    for _ in range(max_tries):
        loc = world.get_random_location_from_navigation()
        if loc is not None and ((loc.x - cx) ** 2 + (loc.y - cy) ** 2) ** 0.5 <= radius:
            return loc
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', default=2000, type=int)
    ap.add_argument('--tm-port', default=8000, type=int)
    ap.add_argument('--map', default=None, help='Map to load, e.g. Town10HD_Opt. '
                     'IMPORTANT: use the exact same --map value in 02_weather_sweep_capture.py.')
    ap.add_argument('--log', required=True, help='Output recorder log path, e.g. scenario01.log')
    ap.add_argument('--center', type=float, nargs=2, default=None, metavar=('X', 'Y'),
                     help='World-space X Y to center the scenario on. Omit to spawn across the '
                          'whole map (previous behavior). Get coordinates by free-flying the '
                          'CARLA spectator to the neighborhood you want, then querying its '
                          'transform (see script docstring above for the exact command).')
    ap.add_argument('--radius', type=float, default=150.0,
                     help='Only used with --center. Max distance (meters) from --center that '
                          'vehicles/pedestrians will spawn and wander within.')
    ap.add_argument('--duration', type=float, default=40.0, help='Seconds of scenario to record.')
    ap.add_argument('--fixed-delta-seconds', type=float, default=0.05,
                     help='Physics tick size. Keep this IDENTICAL between record and replay runs.')
    ap.add_argument('-n', '--number-of-cars', default=40, type=int)
    ap.add_argument('-b', '--number-of-bicycles', default=10, type=int)
    ap.add_argument('-w', '--number-of-walkers', default=60, type=int)
    ap.add_argument('--seed', default=None, type=int)
    ap.add_argument('--walker-retarget-seconds', type=float, default=10.0,
                     help="How often (in sim seconds) each pedestrian gets a fresh random "
                          "destination. Without this they walk to ONE point and then stand "
                          "frozen there for the rest of the scenario once they arrive.")
    args = ap.parse_args()

    client = carla.Client(args.host, args.port)
    client.set_timeout(30.0)

    world = client.load_world(args.map) if args.map else client.get_world()
    tm = client.get_trafficmanager(args.tm_port)
    tm.set_synchronous_mode(True)

    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = args.fixed_delta_seconds
    settings.no_rendering_mode = False
    world.apply_settings(settings)

    if args.seed is not None:
        random.seed(args.seed)
        tm.set_random_device_seed(args.seed)

    # Defensive cleanup: if --map wasn't passed (no fresh reload) and a
    # previous run crashed/was interrupted, this clears its leftovers so
    # we don't spawn on top of them.
    destroy_all_actors(client, world)

    bp_lib = world.get_blueprint_library()
    spawn_points = world.get_map().get_spawn_points()

    if args.center is not None:
        cx, cy = args.center
        in_range = [sp for sp in spawn_points
                    if ((sp.location.x - cx) ** 2 + (sp.location.y - cy) ** 2) ** 0.5 <= args.radius]
        print(f"--center {cx},{cy} --radius {args.radius}: "
              f"{len(in_range)}/{len(spawn_points)} vehicle spawn points in range.")
        needed = 1 + args.number_of_cars + args.number_of_bicycles
        if len(in_range) < needed:
            print(f"  WARNING: only {len(in_range)} spawn points available here, but "
                  f"{needed} vehicles were requested. Increase --radius or lower -n/-b.")
        spawn_points = in_range

    random.shuffle(spawn_points)

    all_vehicle_bps = list(bp_lib.filter('vehicle.*'))
    car_bps = [bp for bp in all_vehicle_bps if int(bp.get_attribute('number_of_wheels')) == 4]
    bike_bps = [bp for bp in all_vehicle_bps if int(bp.get_attribute('number_of_wheels')) == 2]

    # --- Start recording BEFORE anything spawns, so spawn events are captured too ---
    print(f"Recording to {args.log}")
    client.start_recorder(args.log, True)  # additional_data=True: also logs bounding boxes etc.

    vehicle_ids = []

    # Hero vehicle first, tagged so the replay/capture script can find it reliably.
    hero_bp = random.choice(car_bps)
    hero_bp.set_attribute('role_name', 'hero')
    hero = None
    for sp in spawn_points:
        hero = world.try_spawn_actor(hero_bp, sp)
        if hero is not None:
            break
    if hero is None:
        raise RuntimeError("Could not find a free spawn point for the hero vehicle.")
    hero.set_autopilot(True, tm.get_port())
    vehicle_ids.append(hero.id)
    spawn_points.remove(sp)

    # NPC cars
    batch = []
    for transform in spawn_points[:args.number_of_cars]:
        bp = random.choice(car_bps)
        bp.set_attribute('role_name', 'npc')
        if bp.has_attribute('color'):
            bp.set_attribute('color', random.choice(bp.get_attribute('color').recommended_values))
        batch.append(carla.command.SpawnActor(bp, transform).then(
            carla.command.SetAutopilot(carla.command.FutureActor, True, tm.get_port())))

    # Bicycles — same autopilot treatment, Traffic Manager handles 2-wheeled vehicles too
    remaining = spawn_points[args.number_of_cars:args.number_of_cars + args.number_of_bicycles]
    for transform in remaining:
        bp = random.choice(bike_bps) if bike_bps else random.choice(car_bps)
        bp.set_attribute('role_name', 'npc')
        batch.append(carla.command.SpawnActor(bp, transform).then(
            carla.command.SetAutopilot(carla.command.FutureActor, True, tm.get_port())))

    for response in client.apply_batch_sync(batch, True):
        if not response.error:
            vehicle_ids.append(response.actor_id)

    tm.set_global_distance_to_leading_vehicle(2.5)
    tm.global_percentage_speed_difference(20.0)
    tm.set_hybrid_physics_mode(True)
    print(f"Spawned {len(vehicle_ids)} vehicles/bicycles (incl. hero id={hero.id}).")

    # --- Pedestrians ---
    walker_bps = bp_lib.filter('walker.pedestrian.*')
    walker_speed, walker_spawns = [], []
    for _ in range(args.number_of_walkers):
        loc = location_near(world, args.center, args.radius) if args.center is not None \
            else world.get_random_location_from_navigation()
        if loc is not None:
            walker_spawns.append(carla.Transform(location=loc))

    batch = []
    for sp in walker_spawns:
        bp = random.choice(walker_bps)
        if bp.has_attribute('is_invincible'):
            bp.set_attribute('is_invincible', 'false')
        walker_speed.append(bp.get_attribute('speed').recommended_values[1]
                             if bp.has_attribute('speed') else 1.4)
        batch.append(carla.command.SpawnActor(bp, sp))

    results = client.apply_batch_sync(batch, True)
    walker_ids = [r.actor_id for r in results if not r.error]
    walker_speed = [s for r, s in zip(results, walker_speed) if not r.error]

    controller_bp = bp_lib.find('controller.ai.walker')
    batch = [carla.command.SpawnActor(controller_bp, carla.Transform(), wid) for wid in walker_ids]
    controller_results = client.apply_batch_sync(batch, True)
    controller_ids = [r.actor_id for r in controller_results if not r.error]

    world.tick()
    world.set_pedestrians_cross_factor(0.3)
    for i, cid in enumerate(controller_ids):
        controller = world.get_actor(cid)
        controller.start()
        first_target = location_near(world, args.center, args.radius) if args.center is not None \
            else world.get_random_location_from_navigation()
        controller.go_to_location(first_target)
        controller.set_max_speed(float(walker_speed[i]))

    print(f"Spawned {len(walker_ids)} pedestrians.")

    # --- Run the scenario for the requested duration ---
    try:
        n_ticks = int(args.duration / args.fixed_delta_seconds)
        ticks_per_retarget = max(1, int(args.walker_retarget_seconds / args.fixed_delta_seconds))
        print(f"Simulating {args.duration}s ({n_ticks} ticks), "
              f"re-targeting pedestrians every {args.walker_retarget_seconds}s...")
        for tick in range(n_ticks):
            world.tick()
            # Without this, a walker just stands frozen wherever it happens to
            # arrive (including mid-crosswalk) once it reaches its one and only
            # destination — CARLA's walker AI never re-targets on its own.
            if tick > 0 and tick % ticks_per_retarget == 0:
                for cid in controller_ids:
                    controller = world.get_actor(cid)
                    if controller is not None:
                        new_target = location_near(world, args.center, args.radius) \
                            if args.center is not None else world.get_random_location_from_navigation()
                        if new_target is not None:
                            controller.go_to_location(new_target)
        print(f"Done. Recorded {args.duration}s to {args.log}")
    except KeyboardInterrupt:
        print("\nInterrupted — stopping recorder early and cleaning up...")
    finally:
        # Always stop the recorder and destroy actors, even on Ctrl+C or
        # an exception — otherwise this run's actors linger for the NEXT
        # run to accidentally spawn on top of.
        client.stop_recorder()
        for cid in controller_ids:
            try:
                world.get_actor(cid).stop()
            except RuntimeError:
                pass
        client.apply_batch([carla.command.DestroyActor(x) for x in controller_ids + walker_ids])
        client.apply_batch([carla.command.DestroyActor(x) for x in vehicle_ids])
        settings.synchronous_mode = False
        world.apply_settings(settings)
        tm.set_synchronous_mode(False)


if __name__ == '__main__':
    main()
