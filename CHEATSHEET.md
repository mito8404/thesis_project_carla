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
./run_pipeline.sh city              # downtown Town10HD_Opt, whole map, every weather preset
./run_pipeline.sh tunnel            # Town03 underpass, day/night/rain contrast set
./run_pipeline.sh waterfront        # Town10 waterfront area, day/night/rain contrast set
./run_pipeline.sh city 43           # same scenario, different seed = different traffic pattern
./run_pipeline.sh myscenario        # any other name -> falls back to defaults (whole map, full sweep)
```

Each named scenario gets its own log file and its own output folders — nothing overwrites another scenario. Output lands in:
- `carla_captures_<name>/<WeatherPreset>/frame_XXXXXX.png`
- `carla_masks_<name>/<WeatherPreset>/<prompt>/frame_XXXXXX_NN.png`

**`tunnel` and `waterfront` need coordinates filled in before they're actually useful** — until you do, they behave like `city` (whole map). See "Finding coordinates" below, then edit the `PRESET_CENTER[...]` lines near the top of `run_pipeline.sh`.

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
3. Use that as `--center X Y --radius 150` on `01_record_scenario.py`, or paste it into the matching `PRESET_CENTER[...]` line in `run_pipeline.sh`.

Note: **Town10HD_Opt has no tunnel** — CARLA's Town03 is the map with a confirmed underpass, which is why the `tunnel` preset in `run_pipeline.sh` is set to `Town03` instead.

---

## Known gotchas

- **`conda run` can eat `Ctrl+C`.** After interrupting, verify with `ps aux | grep -iE "carla|python3"` that nothing's still running.
- **The CARLA server never resets itself.** A crashed run leaves actors alive for the *next* run to pile on top of — always do the "kill everything" step above after any crash.
- **Two servers on the same port = segfault.** Never manually launch `CarlaUE4.sh` in one terminal while also running `run_pipeline.sh` (which launches its own).
- **Density (`-n`/`-b`/`-w`) lives in `01_record_scenario.py`'s config, not `02_weather_sweep_capture.py`** — the capture stage has no concept of vehicle/pedestrian counts, it only replays whatever the recording already has.
