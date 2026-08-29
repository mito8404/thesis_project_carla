#!/usr/bin/env bash
#
# run_pipeline.sh — runs all 3 stages in one go for a named scenario preset:
#   0. kill any leftover CARLA processes, confirm the port is free
#   1. launch the CARLA server
#   2. record the scenario   (01_record_scenario.py)
#   3. sweep weather + capture frames   (02_weather_sweep_capture.py)
#   4. shut the server down (frees GPU for SAM3)
#   5. run SAM3 segmentation over the captures   (03_sam3_segment.py)
#
# ============================================================
# QUICK REFERENCE — run one of these:
#
#   ./run_pipeline.sh city                  # downtown, whole map, full weather sweep
#   ./run_pipeline.sh tunnel                # Town03 underpass, day/night/rain contrast
#   ./run_pipeline.sh waterfront            # Town10 waterfront area, day/night/rain contrast
#   ./run_pipeline.sh <any-other-name>      # falls back to the manual CONFIG values below
#   ./run_pipeline.sh city 43               # ...with a specific seed as 2nd argument
#
# tunnel and waterfront need a --center coordinate filled in below before
# they're actually centered where you want — see "HOW TO FIND COORDINATES"
# further down. Until you do, they'll just spawn across the whole map like
# "city" does (still runs fine, just not zoomed into that specific spot).
# ============================================================

set -euo pipefail

SCENARIO_NAME="${1:-city}"
SCENARIO_SEED="${2:-42}"

# ---- per-scenario presets -----------------------------------------------
# CENTER values left "" are TODOs — fill in once you've located the spot
# with the spectator-fly trick (see bottom of this file / CHEATSHEET.md).
declare -A PRESET_MAP=(
    [city]="Town10HD_Opt"
    [waterfront]="Town10HD_Opt"
    [tunnel]="Town03"          # Town03 is the CARLA town with a confirmed underpass;
                                # Town10HD_Opt does not have one.
)
declare -A PRESET_CENTER=(
    [city]=""                              # "" = whole map
    [waterfront]=""                        # TODO: fill in, see instructions below
    [tunnel]=""                            # TODO: fill in, see instructions below
)
declare -A PRESET_RADIUS=(
    [city]=150
    [waterfront]=180
    [tunnel]=80
)
declare -A PRESET_WEATHER=(
    # 3x3 grid: {Clear/dry, Wet-road, HardRain} x {Noon, Sunset, Night} -
    # two independent, clearly-separable axes (illumination + precipitation)
    # rather than all 23 near-redundant presets. "" = full sweep, every preset.
    [city]="ClearNoon ClearSunset ClearNight WetNoon WetSunset WetNight HardRainNoon HardRainSunset HardRainNight"
    [waterfront]="ClearNoon HardRainNoon ClearSunset ClearNight HardRainNight"
    [tunnel]="ClearNoon ClearNight HardRainNoon HardRainNight WetNight"  # day/night/rain/illumination contrast
)
# --------------------------------------------------------------------------

# ============ CONFIG — edit these ============
CARLA_ROOT="/media/its/4bb1988e-283d-48b5-8b92-feaf62709288/CARLA_0.9.16"
LOG_FILE="${SCENARIO_NAME}.log"
WARMUP_SECONDS=10     # recorded but skipped during capture - lets traffic disperse from the
                      # simultaneous-spawn "everyone piles up at the nearest intersection" moment
CAPTURE_DURATION=40   # actual usable seconds captured per weather, AFTER the warmup
RECORD_DURATION=$((WARMUP_SECONDS + CAPTURE_DURATION))
FIXED_DELTA=0.05
FPS=10
NUM_CARS=40
NUM_BIKES=10
NUM_WALKERS=60
SEED="$SCENARIO_SEED"
CAMERA_MODE="ego"          # ego | fixed
OUT_DIR="/media/its/ElementsSE/carla_captures_${SCENARIO_NAME}"
MASKS_DIR="/media/its/ElementsSE/carla_masks_${SCENARIO_NAME}"
SAM3_PROMPTS="road car person bicycle"
CONDA_ENV="sam3"           # carla wheel installed into this same env (cp312 matches it)
CARLA_PORT=2000
# ===============================================

# Resolve this scenario's settings from the preset table, falling back to
# sane defaults if SCENARIO_NAME isn't one of the named presets above.
MAP="${PRESET_MAP[$SCENARIO_NAME]:-Town10HD_Opt}"
CENTER="${PRESET_CENTER[$SCENARIO_NAME]-}"
RADIUS="${PRESET_RADIUS[$SCENARIO_NAME]:-150}"
WEATHER_ONLY="${PRESET_WEATHER[$SCENARIO_NAME]-}"

echo "Scenario: $SCENARIO_NAME  (map=$MAP, log=$LOG_FILE, seed=$SEED)"
echo "Output:   $OUT_DIR"
echo "Masks:    $MASKS_DIR"
if [[ ( "$SCENARIO_NAME" == "tunnel" || "$SCENARIO_NAME" == "waterfront" ) && -z "$CENTER" ]]; then
    echo "NOTE: no --center coordinates filled in yet for '$SCENARIO_NAME' -" \
         "it'll spawn across the whole $MAP map instead of that specific spot." \
         "See the CENTER TODOs near the top of this file."
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CARLA_PID=""

cleanup() {
    if [[ -n "$CARLA_PID" ]] && kill -0 "$CARLA_PID" 2>/dev/null; then
        echo "Shutting down CARLA server (pid $CARLA_PID)..."
        kill "$CARLA_PID" 2>/dev/null || true
        wait "$CARLA_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

port_is_open() {
    (exec 3<>"/dev/tcp/127.0.0.1/$CARLA_PORT") 2>/dev/null && { exec 3>&- 3<&-; return 0; }
    return 1
}

wait_for_carla() {
    echo "Waiting for CARLA server on port $CARLA_PORT..."
    for _ in $(seq 1 60); do
        # Bail immediately if OUR launched process already died (e.g. segfaulted
        # on "Address already in use") rather than silently trusting whatever
        # else answers on the port - that's what let a stale leftover server
        # get used unnoticed before.
        if ! kill -0 "$CARLA_PID" 2>/dev/null; then
            echo "ERROR: the CARLA process we launched (pid $CARLA_PID) died already." >&2
            echo "This usually means the port was already occupied by a leftover process." >&2
            echo "Run:  pkill -9 -f -i carla ; sleep 3 ; ss -tulpn | grep $CARLA_PORT" >&2
            echo "...confirm that prints nothing, then re-run this script." >&2
            exit 1
        fi
        if port_is_open; then
            echo "CARLA server is up."
            return 0
        fi
        sleep 2
    done
    echo "ERROR: CARLA server did not come up within 120s." >&2
    exit 1
}

echo "=== 0/4: pre-flight cleanup (killing any leftover CARLA processes) ==="
pkill -9 -f -i carla 2>/dev/null || true
sleep 3
if port_is_open; then
    echo "ERROR: port $CARLA_PORT is still occupied after pkill." >&2
    echo "Find and kill it manually:  ps aux | grep -i carla" >&2
    exit 1
fi
echo "Port $CARLA_PORT confirmed free."

echo "=== 1/4: launching CARLA server ==="
"$CARLA_ROOT/CarlaUE4.sh" -quality-level=Epic -carla-rpc-port="$CARLA_PORT" &
CARLA_PID=$!
wait_for_carla

CENTER_ARGS=()
if [[ -n "$CENTER" ]]; then
    CENTER_ARGS=(--center $CENTER --radius "$RADIUS")
fi

echo "=== 2/4: recording scenario ($RECORD_DURATION s = ${WARMUP_SECONDS}s warmup + ${CAPTURE_DURATION}s usable) ==="
conda run -n "$CONDA_ENV" --no-capture-output python3 "$SCRIPT_DIR/01_record_scenario.py" \
    --port "$CARLA_PORT" --map "$MAP" --log "$LOG_FILE" \
    --duration "$RECORD_DURATION" --fixed-delta-seconds "$FIXED_DELTA" \
    -n "$NUM_CARS" -b "$NUM_BIKES" -w "$NUM_WALKERS" --seed "$SEED" \
    "${CENTER_ARGS[@]}"

WEATHER_ARGS=()
if [[ -n "$WEATHER_ONLY" ]]; then
    WEATHER_ARGS=(--only $WEATHER_ONLY)
fi

echo "=== 3/4: sweeping weather + capturing frames (skipping first ${WARMUP_SECONDS}s) ==="
conda run -n "$CONDA_ENV" --no-capture-output python3 "$SCRIPT_DIR/02_weather_sweep_capture.py" \
    --port "$CARLA_PORT" --map "$MAP" --log "$LOG_FILE" \
    --replay-start "$WARMUP_SECONDS" --duration "$CAPTURE_DURATION" --fixed-delta-seconds "$FIXED_DELTA" \
    --fps "$FPS" --camera-mode "$CAMERA_MODE" --out "$OUT_DIR" \
    "${WEATHER_ARGS[@]}"

echo "=== shutting down CARLA server before SAM3 (frees GPU memory) ==="
kill "$CARLA_PID" 2>/dev/null || true
wait "$CARLA_PID" 2>/dev/null || true
CARLA_PID=""

echo "=== 4/4: running SAM3 segmentation ==="
conda run -n "$CONDA_ENV" --no-capture-output python3 "$SCRIPT_DIR/03_sam3_segment.py" \
    --frames-dir "$OUT_DIR" --out "$MASKS_DIR" --prompts $SAM3_PROMPTS

echo "=== pipeline complete ==="
echo "Frames: $OUT_DIR"
echo "Masks:  $MASKS_DIR"

# ============================================================
# HOW TO FIND --center COORDINATES for tunnel / waterfront:
#   1. Launch the server: ./CarlaUE4.sh -quality-level=Epic
#   2. In the CARLA window: right-click-drag + WASD to free-fly the
#      spectator camera to the spot you want (the tunnel entrance, the
#      waterfront promenade, etc).
#   3. In a second terminal:
#        python3 -c "
#      import carla
#      w = carla.Client('127.0.0.1', 2000).get_world()
#      t = w.get_spectator().get_transform()
#      print(f'{t.location.x:.1f} {t.location.y:.1f}')
#      "
#   4. Paste that "X Y" into the matching PRESET_CENTER[...] line near the
#      top of this file, e.g.  [tunnel]="12.4 -58.9"
# ============================================================
