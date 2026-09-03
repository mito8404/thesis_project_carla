# CARLA weather-sweep + SAM3 pipeline — cheat sheet

_Mirrored from the live copy deployed at `/media/its/ElementsSE/CHEATSHEET.md` on monolith. If you edit the deployed copy, bring the changes back here too so a fresh chat starts from the current version._

## Files (run in this order — numbered so it's obvious)

| File | What it does |
|---|---|
| `run_pipeline.sh` | Runs everything below in one go, for a named scenario. **This is what you normally run.** |
| `01_record_scenario.py` | Stage 1. Spawns cars/bikes/pedestrians and records their movement to a `.log` file. Run standalone only for quick previews. |
| `02_weather_sweep_capture.py` | Stage 2. Replays a `.log` once per weather preset, saving camera frames. Run standalone to re-capture without re-recording. |
| `03_sam3_segment.py` | Stage 3. Runs SAM3 over captured frames, saving segmentation masks. |
| `CHEATSHEET.md` | This file. |

All 4 must live in the same folder on `ElementsSE`. (There's also an original-named twin set — `carla_record_scenario.py`, `sam3_batch_segment.py` — kept in sync with the numbered files line-for-line; either set works, `run_pipeline.sh` calls the numbered ones specifically.)

---

## One-time setup (already done, here for reference)

```bash
pip install --no-deps "/media/its/4bb1988e-283d-48b5-8b92-feaf62709288/CARLA_0.9.16/PythonAPI/carla/dist/carla-0.9.16-cp312-cp312-manylinux_2_31_x86_64.whl"
python3 -c "import carla; print('ok')"
```

---

## Run a full scenario (the normal thing you do)

```bash
conda activate sam3          # REQUIRED before running any stage manually - see "Known gotchas"
chmod +x run_pipeline.sh
./run_pipeline.sh city              # Town10 downtown, centered, full 9-weather sweep
./run_pipeline.sh waterfront        # Town10 promenade, day/night/rain contrast set (5 presets)
./run_pipeline.sh tunnel            # Town03 underpass, day/night/rain contrast set (5 presets)
./run_pipeline.sh underpass         # Town05 bridge/underpass, day/night/rain contrast set (5 presets)
./run_pipeline.sh suburban          # Town02 residential, light 3-preset weather set
./run_pipeline.sh highway           # Town04 figure-8 highway loop, light 3-preset weather set
./run_pipeline.sh underpass2        # Town05, DIFFERENT pathway than underpass, fewer cars (40 vs 80)
./run_pipeline.sh city2             # SAME spot as city, fewer cars (50 vs 80)
./run_pipeline.sh city 43           # same scenario, different seed = different traffic pattern
./run_pipeline.sh myscenario        # any other name -> falls back to defaults (whole map, full sweep)
```

Each named scenario gets its own log file and its own output folders — nothing overwrites another scenario. Output lands in:
- `carla_captures_<name>/<WeatherPreset>/frame_XXXXXX.png`
- `carla_masks_<name>/<WeatherPreset>/<prompt>/frame_XXXXXX_NN.png`

**`underpass2` and `city2` are extra, lower-density runs alongside `underpass`/`city` — they do NOT replace or overwrite the originals.** `underpass2` scouts a genuinely different pathway through Town05 (`-164.7 -95.1`, spawn point 000) with half the cars (40 vs 80), same bikes/walkers as `underpass`. `city2` reuses `city`'s exact same center (`32.3 130.5`) — same spot, just 50 cars instead of 80, same bikes/walkers as `city`. Because their preset names are just disambiguating suffixes, their output folders are named descriptively instead of literally `carla_captures_underpass2`/`carla_captures_city2`:
- `underpass2` → `carla_captures_underpass_altroute/`, `carla_masks_underpass_altroute/`
- `city2` → `carla_captures_city_lowdensity/`, `carla_masks_city_lowdensity/`

(This folder-name override lives in a new `PRESET_OUT_NAME` table in `run_pipeline.sh`, right after `PRESET_WALKERS` — add an entry there for any future preset whose name shouldn't be the literal folder name.)

**`waterfront` still needs coordinates filled in** — until you do, it behaves like `city` (whole map). See "Finding coordinates" below, then edit its `PRESET_CENTER[...]` line near the top of `run_pipeline.sh`. The rest already have real centers found via `find_location.py`:

| Scenario | Town | Center (X Y) | Radius |
|---|---|---|---|
| `city` | Town10HD_Opt | 32.3 130.5 | 150 |
| `city2` | Town10HD_Opt | 32.3 130.5 (SAME as `city`) | 150 |
| `waterfront` | Town10HD_Opt | *(TODO — not yet scouted)* | 180 |
| `tunnel` | Town03 | 163.9 -197.4 | 80 |
| `underpass` | Town05 | -159.7 -0.6 | 80 |
| `underpass2` | Town05 | -164.7 -95.1 (spawn pt 000, different pathway than `underpass`) | 80 |
| `suburban` | Town02 | 25.5 105.5 (spawn pt 028) | 150 |
| `highway` | Town04 | -494.2 240.9 | 250 |

`suburban` and `highway` get a lighter 3-preset weather set on purpose — for those two the environment/road structure itself is the point of including them, not the weather variation. Bump their `PRESET_WEATHER[...]` entries up if you want full parity with `city`.

### Per-scenario vehicle/pedestrian density

A scenario with no row below just uses the global `NUM_CARS`/`NUM_BIKES`/`NUM_WALKERS` at the top of `run_pipeline.sh` (currently 60/40/120). Add a row here (and a matching entry in `PRESET_CARS`/`PRESET_BIKES`/`PRESET_WALKERS` in `run_pipeline.sh`) whenever you override a scenario's density, so this table always matches what's actually configured — don't let it drift out of sync.

| Scenario | Location (Town, Center X Y) | Cars | Bikes | Walkers | Weather tested | Why |
|---|---|---|---|---|---|---|
| `city` | Town10HD_Opt, 32.3 130.5 | 80 | 40 | 150 | ClearNoon, ClearSunset, ClearNight, WetNoon, WetSunset, WetNight, HardRainNoon, HardRainSunset, HardRainNight (full 9-preset sweep) | Densely populated overall, by design - cars and people both high, this is the "busy downtown" scenario. |
| `city2` | Town10HD_Opt, 32.3 130.5 (SAME spot as `city`) | 50 | 40 | 150 | Same full 9-preset sweep as `city` | Extra run alongside `city`, same exact spot - fewer cars only, same bikes/walkers, to compare density at the same location. |
| `suburban` | Town02, 25.5 105.5 (spawn pt 028) | 35 | 15 | 100 | ClearNoon, HardRainNoon, ClearNight (light 3-preset set) | Densely populated with *people*, average cars - residential streets see plenty of foot traffic but only moderate car traffic, unlike downtown. |
| `highway` | Town04, -494.2 240.9 | 120 | 0 | 0 | ClearNoon, HardRainNoon, ClearNight (light 3-preset set) | Densely populated with cars. Bikes/walkers are 0, not just "low" - pedestrians and cyclists are illegal on a limited-access highway in real life, so 0 is the realistic choice, not a placeholder. |
| `tunnel` | Town03, 163.9 -197.4 | 80 | 5 | 5 | ClearNoon, ClearNight, HardRainNoon, HardRainNight, WetNight (day/night/rain contrast set) | Realistically almost nobody walks through a highway tunnel - kept pedestrians/bikes minimal. Cars set high on purpose relative to measured capacity (only 18/265 vehicle spawn points fell within `--radius 80` in Town03) so CARLA fills every available spawn point instead of under-using the space - the `WARNING: only N spawn points available` line is expected here, not a problem to chase. |
| `underpass` | Town05, -159.7 -0.6 | 80 | 5 | 5 | ClearNoon, ClearNight, HardRainNoon, HardRainNight, WetNight (day/night/rain contrast set) | Same reasoning as `tunnel` - Town05's bridge/underpass is the same "nobody walks here" structural case. |
| `underpass2` | Town05, -164.7 -95.1 (spawn pt 000, different pathway than `underpass`) | 40 | 5 | 5 | Same day/night/rain contrast set as `underpass` | Extra run alongside `underpass`, different pathway through Town05 - half the cars, same bikes/walkers, to compare density without losing the original capture. |

(`waterfront` isn't in this table - its `PRESET_CENTER` is still an unfilled TODO, so it has no real location or measured density yet. It'll get a row once it's scouted; see "Finding coordinates" below.)

"Weather tested" reflects each preset's `PRESET_WEATHER[...]` entry in `run_pipeline.sh` — the weather sweep that scenario is *configured* to run, not a confirmed record of which captures have actually completed. Cross-check against your own capture folders if you need to know what's actually landed on disk so far.

Fill in a row's Cars/Bikes/Walkers once you give it its own override, and jot down the reasoning in "Why" while it's still fresh — it's the kind of decision that's easy to forget the justification for a few weeks later when writing this up.

Only `tunnel`'s capacity (18 spawn points) has actually been measured against its density target - `city`/`suburban`/`highway`'s numbers above are starting points, not verified limits. If a run prints `only N spawn points available` or `N/M requested walkers found a navigable spawn point`, that's real evidence of the actual ceiling for that spot - raise `PRESET_RADIUS` for that scenario or lower its count here to match what the location can really hold.

**Open question, not yet resolved:** in `suburban` at its center (25.5, 105.5), a run showed no pedestrians visible on the walkways along with repeated `WARNING: NAV: Failed to set request to go to ...` lines during the tick loop. Leading theory: that spot's pedestrian navmesh is sparse/disconnected, or the 150m radius spreads the 100 walkers too far from the actual driven road for the ego camera to catch any. Not yet root-caused — next step is checking the actual capture frames or narrowing `--radius` for `suburban` and re-testing.

---

## Getting more than one car visible in a tight scenario (tunnel, underpass)

Spawning more cars doesn't fix this — a moving ego dashcam only ever shows whatever's directly ahead, so most of a scenario's actors are just elsewhere at any instant, even with capacity maxed out. `tunnel` really does have 18 vehicles in the simulation at once; the ego view just doesn't catch them all. (CARLA's Traffic Manager also routes autopilot NPCs across the *entire* map's road network the moment they spawn — `--radius`/`--center` only control where a vehicle starts, not where it drives afterward — so ordinary traffic disperses away from your scenario's actual location within seconds regardless of capacity.)

A "companion vehicle" system (dedicated cars kept near the hero via waypoint math) was tried and **fully reverted** at user request — not present in the current deployed scripts. The approach below (fixed camera) is the current/only fix for this issue.

Fix: point a **fixed** camera at the pinch-point itself, so it catches whatever passes through over the whole capture instead of driving past it. You need the full 6-value transform (X Y Z pitch yaw roll) for that spot — `find_location.py`'s filenames only give X/Y, so use `get_spawn_transform.py` to get the rest from the same spot (by its index number from the filename, e.g. `144_x163.9_y-197.4.png` → index `144`):

```bash
./CarlaUE4.sh -quality-level=Epic   # server, separate terminal
python3 get_spawn_transform.py --map Town03 --index 144
```

It prints a ready-to-paste `X Y Z pitch yaw roll` line — that spawn point's own rotation faces the same way a car there would drive, which is usually exactly the direction you want to look (into the tunnel). Paste it into `run_pipeline.sh`'s `PRESET_CAMERA_TRANSFORM[tunnel]`, then set `PRESET_CAMERA_MODE[tunnel]="fixed"` (both near the top of the file, just uncomment the example lines and fill in your real values). If the resulting shot faces the wrong way (out of the tunnel instead of into it), add/subtract 180 from the yaw and try again.

Leave a preset out of both tables and it just keeps using the global `ego` dashcam — this is opt-in per scenario, not a global switch. **Not yet activated for any scenario** — scaffolded but commented out.

---

## Kill everything / clean slate

```bash
pkill -9 -f -i carla
sleep 3
ps aux | grep -i carla        # should show only the grep itself
ss -tulpn | grep 2000         # should print nothing
```

Run this before starting a new `./run_pipeline.sh` if a previous run crashed or was interrupted.

If SAM3 (stage 4) OOMs with plenty of memory theoretically free, also check `nvidia-smi` for a stray leftover process (a crashed/aborted earlier run can leave GPU memory held by a zombie process not caught by the `pkill -f -i carla` pattern) and `kill -9` it directly by PID.

---

## Quick preview (before committing to a full run)

Start the server manually first:
```bash
pkill -9 -f -i carla; sleep 3
cd /media/its/4bb1988e-283d-48b5-8b92-feaf62709288/CARLA_0.9.16
./CarlaUE4.sh -quality-level=Epic
```

In a second terminal (`sam3` env — **`conda activate sam3` first**), watch density live or grab a few sample frames:
```bash
python3 01_record_scenario.py --map Town10HD_Opt --duration 15 --log test_scenario.log -n 40 -b 25 -w 120 --seed 42

python3 02_weather_sweep_capture.py --map Town10HD_Opt --log test_scenario.log --duration 15 --fps 5 --camera-mode ego --out ./preview --only ClearNoon
```

---

## See what a mask actually looks like (not just a black frame with a white blob)

By default `03_sam3_segment.py` (and `sam3_batch_segment.py`) writes plain black/white ground-truth masks - correct for training, useless for eyeballing. Add `--overlays` to also save the original frame with the mask painted on as a translucent color highlight, written to a sibling folder so it never touches the real masks:

```bash
python3 03_sam3_segment.py --frames-dir ./captures --out ./masks \
    --prompts road car person bicycle --overlays
```

`--overlay-alpha 0.3` (more transparent, default 0.5) or `--overlay-out /some/other/path` to change where they land.

Each frame/prompt gets both per-instance overlay files (`frame_XXXXXX_00.png`, `_01.png`, ... — one object highlighted each, useful for isolating a specific detection) AND one `frame_XXXXXX_all.png` with every kept instance for that prompt highlighted together — **`_all.png` is the one to look at** for "did it catch everything in this frame."

---

## Only one car/person gets segmented per frame even though several are visible

Two different causes, worth telling apart:

**1. SAM3 itself only found one instance.** `Sam3Processor` drops any detected object scoring below `--score-threshold` (default `0.5` in SAM3, `0.3` in these scripts) *inside the model*, before masks ever reach `03_sam3_segment.py` - and that score is a class-match confidence **times** an object-presence confidence, so it drops fast for anything distant, partially occluded, or poorly lit (worse at night). Lower `--score-threshold` further (e.g. `0.2-0.25`) to surface more instances; trade-off is more false positives/noisier masks.

**2. SAM3 found several instances, but the overlay only ever shows one at a time.** This was a real display bug, now fixed: the script was calling `save_overlay()` separately for each detected instance, each call writing its OWN file (`frame_XXXXXX_00.png`, `_01.png`, ...) with only that one object highlighted - so browsing the overlay folder looked like "one car at a time" even when every car in the frame was correctly detected and already present in the ground-truth masks. **Fixed**: each frame/prompt now also gets one additional `frame_XXXXXX_all.png` overlay with every kept instance unioned together and highlighted at once - that's the file to look at for "did it catch everything," while the per-instance files remain for isolating one specific detection. The individual ground-truth mask files (`.../frame_XXXXXX_NN.png` under the plain `--out` folder, not `--overlays`) were never affected by this - those were always one-file-per-instance correctly, which is the standard/correct format for instance segmentation training data.

If you run SAM3 directly on a single image yourself (bypassing these scripts entirely), `set_text_prompt()` already returns ALL instances above the confidence threshold in one call (`output['masks']`, `output['scores']`, both lists) - there's nothing special about running it manually that "collects more" than what these scripts already extract; the scripts were just visualizing it misleadingly before this fix.

---

## Capture a specific time window from an existing recording

No need to re-record — `.log` files are reusable. `--replay-start` skips ahead:
```bash
python3 02_weather_sweep_capture.py --map Town10HD_Opt --log scenario01.log \
    --replay-start 30 --duration 10 --fps 10 --camera-mode ego --out ./captures_30_40s
```

---

## Finding coordinates for a specific spot (tunnel, waterfront, anywhere)

CARLA doesn't publish coordinates for named features (checked the official Town03/Town10 docs - they only describe the layout in words, no X/Y). Two ways to find them yourself:

**Option A — scout script (recommended, no manual flying):**
```bash
./CarlaUE4.sh -quality-level=Epic   # server, separate terminal
python3 find_location.py --map Town03 --out ./town03_scout
python3 find_location.py --map Town10HD_Opt --out ./town10_scout
```
This screenshots every spawn point on the map from driving height. Open the output folder and scroll through - each filename already has its coordinates baked in, e.g. `047_x12.4_y-58.9.png` means `--center 12.4 -58.9`. Use `--stride 2` if a map has hundreds of spawn points and you want fewer, faster thumbnails.

**Option B — manual free-fly (for fine-tuning, or if a spawn point isn't quite close enough):**
1. Server running, then in the CARLA window: **right-click-drag + WASD** to free-fly the spectator to the spot you want.
2. In a second terminal:
   ```bash
   python3 -c "
   import carla
   w = carla.Client('127.0.0.1', 2000).get_world()
   t = w.get_spectator().get_transform()
   print(f'{t.location.x:.1f} {t.location.y:.1f}')
   "
   ```

Either way, use the result as `--center X Y --radius 150` on `01_record_scenario.py`, or paste it into the matching `PRESET_CENTER[...]` line in `run_pipeline.sh`.

Note: **Town10HD_Opt has no tunnel** — CARLA's Town03 is the map with a confirmed underpass, which is why the `tunnel` preset in `run_pipeline.sh` is set to `Town03` instead.

---

## Known gotchas

- **`conda activate sam3` is required before running any stage script directly** (not needed when going through `run_pipeline.sh`, which uses `conda run -n sam3` internally). Running bare `python3 03_sam3_segment.py ...` in a fresh terminal without activating first silently falls back to the *system* Python (`/usr/lib/python3/dist-packages/...`), which has a numpy/torch version mismatch and fails with `AttributeError: _ARRAY_API not found`. Check for `(sam3)` at the start of your prompt before running anything standalone.
- **`conda run` can eat `Ctrl+C`.** After interrupting, verify with `ps aux | grep -iE "carla|python3"` that nothing's still running.
- **The CARLA server never resets itself.** A crashed run leaves actors alive for the *next* run to pile on top of — always do the "kill everything" step above after any crash.
- **Two servers on the same port = segfault.** Never manually launch `CarlaUE4.sh` in one terminal while also running `run_pipeline.sh` (which launches its own).
- **Density (`-n`/`-b`/`-w`) lives in `01_record_scenario.py`'s config, not `02_weather_sweep_capture.py`** — the capture stage has no concept of vehicle/pedestrian counts, it only replays whatever the recording already has.
- **`SendUserFile`/browser downloads can silently version-suffix a filename** (`01_record_scenario(1).py`) instead of overwriting the old one in `~/Downloads` — if a script's behavior doesn't match what you were just told changed, check `ls -la ~/Downloads/<name>*` for a duplicate before assuming the fix didn't work. Clearing out old copies after each deploy avoids this.
- **The fire truck (and cargo truck) flip/launch into the air, sometimes landing in the hero's lane and blocking it entirely.** Not a hybrid-physics-radius issue — it's specific to those two blueprints. `vehicle.carlamotors.firetruck` and `vehicle.carlamotors.carlacola` are tall, heavy vehicles whose default CARLA physics tuning makes them unstable under ordinary Traffic Manager driving (cornering, being cut off, minor contact), unlike normal 4-wheel cars. Fixed by excluding them outright from the NPC vehicle pool in `01_record_scenario.py`/`carla_record_scenario.py` (`UNSTABLE_VEHICLE_KEYWORDS = ('firetruck', 'carlacola')`, filtered out of `car_bps` right where it's built) rather than trying to keep them stable. If you ever see a *different* vehicle model flip, add its blueprint id substring to that same tuple.
- **`terminate called after throwing an instance of 'std::runtime_error' ... Actor could not be found in the registry` crashes the whole run with a core dump, right after recording finishes successfully.** This is CARLA's hybrid-physics system internally racing against an actor being destroyed (e.g. by a collision) while trying to toggle that actor's physics on/off — an unrecoverable C++-level abort, not something `try`/`except` in the Python script can catch. It showed up specifically after widening `tm.set_hybrid_physics_radius()` to 100m (an earlier, wrong-theory attempt at fixing the flying-truck bug above) — more vehicles crossing a bigger radius boundary each tick means more chances to hit the race. **Fix: leave the hybrid-physics radius at CARLA's default (don't call `set_hybrid_physics_radius()` at all)** — both scripts do this now. If this crash ever reappears at the default radius, the next step would be `tm.set_hybrid_physics_mode(False)` (full physics on every actor, no toggling, more CPU cost) rather than tuning the radius again.
- **`RuntimeError: time-out of 30000ms while waiting for the simulator`** right after `01_record_scenario.py` starts, even though `run_pipeline.sh` already printed `CARLA server is up`. This is a race: `wait_for_carla()` in `run_pipeline.sh` only checks that CARLA's RPC *port* is accepting connections, not that the map has actually finished loading — the port opens before the Unreal Engine level is fully streamed in. The very first `load_world()` call for a given map can take longer than 30s (asset streaming/shader compilation), especially for a map that hasn't been loaded recently, and every script here used a 30s `client.set_timeout()` that could expire mid-load. **Fixed**: bumped `client.set_timeout()` to `120.0` in every script (`01_record_scenario.py`, `02_weather_sweep_capture.py`, `carla_record_scenario.py`, `carla_weather_sweep_capture.py`, `find_location.py`, `get_spawn_transform.py`). Since it's a race, it won't reproduce every time — that's expected, not a sign the fix didn't work.
- **Overlays only showed one detected instance at a time** (e.g. one car highlighted per file even when several were in the frame) — a display bug, not a detection problem. See "Only one car/person gets segmented per frame" above. Fixed by adding a combined `frame_XXXXXX_all.png` overlay per frame/prompt.
- **A new preset whose name is just a suffix off a base preset (e.g. `underpass2`, `city2`) would, by default, get a folder named literally after that suffix** (`carla_captures_underpass2`) — confusing on disk next to the original. `PRESET_OUT_NAME` in `run_pipeline.sh` (right after `PRESET_WALKERS`) overrides the output folder name for specific presets; add an entry there whenever you add a new suffix-named preset. Leave a preset out of it and it just uses its own name as the folder, same as always.
