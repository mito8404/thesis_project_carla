# CARLA weather-sweep + SAM3 pipeline — cheat sheet

## Files (run in this order — numbered so it's obvious)

| File | What it does |
|---|---|
| `run_pipeline.sh` | Runs everything below in one go, for a named scenario. **This is what you normally run.** |
| `01_record_scenario.py` | Stage 1. Spawns cars/bikes/pedestrians and records their movement to a `.log` file. Run standalone only for quick previews. |
| `02_weather_sweep_capture.py` | Stage 2. Replays a `.log` once per weather preset, saving camera frames. Run standalone to re-capture without re-recording. |
| `03_sam3_segment.py` | Stage 3. Runs SAM3 over captured frames, saving segmentation masks. |
| `CHEATSHEET.md` | This file. |

All 4 must live in the same folder on `ElementsSE`.

---

## One-time setup (already done, here for reference)

```bash
pip install --no-deps "/media/its/4bb1988e-283d-48b5-8b92-feaf62709288/CARLA_0.9.16/PythonAPI/carla/dist/carla-0.9.16-cp312-cp312-manylinux_2_31_x86_64.whl"
python3 -c "import carla; print('ok')"
```

---

## Run a full scenario (the normal thing you do)

```bash
chmod +x run_pipeline.sh
./run_pipeline.sh city              # Town10 downtown, centered, full 9-weather sweep
./run_pipeline.sh waterfront        # Town10 promenade, day/night/rain contrast set (5 presets)
./run_pipeline.sh tunnel            # Town03 underpass, day/night/rain contrast set (5 presets)
./run_pipeline.sh underpass         # Town05 bridge/underpass, day/night/rain contrast set (5 presets)
./run_pipeline.sh suburban          # Town02 residential, light 3-preset weather set
./run_pipeline.sh highway           # Town04 figure-8 highway loop, light 3-preset weather set
./run_pipeline.sh city 43           # same scenario, different seed = different traffic pattern
./run_pipeline.sh myscenario        # any other name -> falls back to defaults (whole map, full sweep)
```
## Capture status

| Scenario | Status |
|---|---|
| City | Captured |
| Tunnel | Captured |
| Underpass | Captured |
| Highway | Captured |
| Suburban | Not captured yet for all segmentation |

## Redo (masks + overlays) and why

| Scenario | Redo | Why |
|---|---|---|
| City | Masks + overlays regenerated (`_v2`) | Overlay bug: old overlays only ever showed one detected instance per file (e.g. one car highlighted per image), making it look like SAM3 missed everything else in the frame. `_v2` adds a combined `_all` overlay per frame/prompt with every detected instance highlighted together. |
| Underpass | Masks + overlays regenerated (`_v2`) | Same overlay bug fix as City. |
| Suburban | Masks + overlays regenerated (`_v2`) | Same overlay bug fix as City. |
| Tunnel | Masks + overlays regenerated (`_v2`) | Same overlay bug fix as City. |
| Highway | Masks + overlays regenerated (`_v2`) | Same overlay bug fix as City. |
Each named scenario gets its own log file and its own output folders — nothing overwrites another scenario. Output lands in:
- `carla_captures_<name>/<WeatherPreset>/frame_XXXXXX.png`
- `carla_masks_<name>/<WeatherPreset>/<prompt>/frame_XXXXXX_NN.png`

**`waterfront` still needs coordinates filled in** — until you do, it behaves like `city` (whole map). See "Finding coordinates" below, then edit its `PRESET_CENTER[...]` line near the top of `run_pipeline.sh`. The other five already have real centers found via `find_location.py`.

`suburban` and `highway` get a lighter 3-preset weather set on purpose — for those two the environment/road structure itself is the point of including them, not the weather variation. Bump their `PRESET_WEATHER[...]` entries up if you want full parity with `city`.

### Per-scenario vehicle/pedestrian density

A scenario with no row below just uses the global `NUM_CARS`/`NUM_BIKES`/`NUM_WALKERS` at the top of `run_pipeline.sh` (currently 60/40/120). Add a row here (and a matching entry in `PRESET_CARS`/`PRESET_BIKES`/`PRESET_WALKERS` in `run_pipeline.sh`) whenever you override a scenario's density, so this table always matches what's actually configured — don't let it drift out of sync.

| Scenario | Cars | Bikes | Walkers | Why |
|---|---|---|---|---|
| `city` | 80 | 40 | 150 | Densely populated overall, by design - cars and people both high, this is the "busy downtown" scenario. |
| `suburban` | 35 | 15 | 100 | Densely populated with *people*, average cars - residential streets see plenty of foot traffic but only moderate car traffic, unlike downtown. |
| `highway` | 120 | 0 | 0 | Densely populated with cars. Bikes/walkers are 0, not just "low" - pedestrians and cyclists are illegal on a limited-access highway in real life, so 0 is the realistic choice, not a placeholder. |
| `tunnel` | 80 | 5 | 5 | Realistically almost nobody walks through a highway tunnel - kept pedestrians/bikes minimal. Cars set high on purpose relative to measured capacity (only 18/265 vehicle spawn points fell within `--radius 80` in Town03) so CARLA fills every available spawn point instead of under-using the space - the `WARNING: only N spawn points available` line is expected here, not a problem to chase. |
| `underpass` | 80 | 5 | 5 | Same reasoning as `tunnel` - Town05's bridge/underpass is the same "nobody walks here" structural case. |
| `waterfront` | *(global)* | *(global)* | *(global)* | Not yet decided - a promenade probably wants pedestrian-heavy like `suburban`, but you haven't set an override yet. |

Fill in a row's Cars/Bikes/Walkers once you give it its own override, and jot down the reasoning in "Why" while it's still fresh — it's the kind of decision that's easy to forget the justification for a few weeks later when writing this up.

Only `tunnel`'s capacity (18 spawn points) has actually been measured against its density target - `city`/`suburban`/`highway`'s numbers above are starting points, not verified limits. If a run prints `only N spawn points available` or `N/M requested walkers found a navigable spawn point`, that's real evidence of the actual ceiling for that spot - raise `PRESET_RADIUS` for that scenario or lower its count here to match what the location can really hold.

---

## Kill everything / clean slate

```bash
pkill -9 -f -i carla
sleep 3
ps aux | grep -i carla        # should show only the grep itself
ss -tulpn | grep 2000         # should print nothing
```

Run this before starting a new `./run_pipeline.sh` if a previous run crashed or was interrupted.

---

## Quick preview (before committing to a full run)

Start the server manually first:
```bash
pkill -9 -f -i carla; sleep 3
cd /media/its/4bb1988e-283d-48b5-8b92-feaf62709288/CARLA_0.9.16
./CarlaUE4.sh -quality-level=Epic
```

In a second terminal (`sam3` env), watch density live or grab a few sample frames:
```bash
# just watch the CARLA window while it records - fastest check
python3 01_record_scenario.py --map Town10HD_Opt --duration 15 --log test_scenario.log -n 40 -b 25 -w 120 --seed 42

# or grab actual sample images from one weather preset only
python3 02_weather_sweep_capture.py --map Town10HD_Opt --log test_scenario.log --duration 15 --fps 5 --camera-mode ego --out ./preview --only ClearNoon
```

---

## See what a mask actually looks like (not just a black frame with a white blob)

By default `03_sam3_segment.py` (and `sam3_batch_segment.py`) writes plain black/white ground-truth masks - correct for training, useless for eyeballing. Add `--overlays` to also save the original frame with the mask painted on as a translucent color highlight, written to a sibling folder so it never touches the real masks:

```bash
python3 03_sam3_segment.py --frames-dir ./captures --out ./masks \
    --prompts road car person bicycle --overlays
# masks:    ./masks/<weather>/<prompt>/frame_XXXXXX_NN.png       (black/white, ground truth)
# overlays: ./masks_overlays/<weather>/<prompt>/frame_XXXXXX_NN.png  (color highlight on original frame)
```

`--overlay-alpha 0.3` (more transparent, default 0.5) or `--overlay-out /some/other/path` to change where they land.

---

## Only one car/person gets segmented per frame even though several are visible

This is SAM3's own internal confidence filter, not a bug in these scripts. `Sam3Processor` drops any detected object scoring below `--score-threshold` (default `0.5`) *inside the model*, before masks ever reach `03_sam3_segment.py` - and that score is a class-match confidence **times** an object-presence confidence, so it drops fast for anything distant, partially occluded, or poorly lit (worse at night). Usually only the single clearest/nearest object per prompt survives.

Lower it to surface more instances:
```bash
python3 03_sam3_segment.py --frames-dir ./captures --out ./masks \
    --prompts road car person bicycle --score-threshold 0.3
```
Trade-off: more instances kept also means more false positives/noisier masks - use `--overlays` (above) to visually check where the new cutoff lands before committing to it for a full run.

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

- **`conda run` can eat `Ctrl+C`.** After interrupting, verify with `ps aux | grep -iE "carla|python3"` that nothing's still running.
- **The CARLA server never resets itself.** A crashed run leaves actors alive for the *next* run to pile on top of — always do the "kill everything" step above after any crash.
- **Two servers on the same port = segfault.** Never manually launch `CarlaUE4.sh` in one terminal while also running `run_pipeline.sh` (which launches its own).
- **Density (`-n`/`-b`/`-w`) lives in `01_record_scenario.py`'s config, not `02_weather_sweep_capture.py`** — the capture stage has no concept of vehicle/pedestrian counts, it only replays whatever the recording already has.
