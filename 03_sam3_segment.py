"""
03_sam3_segment.py  (STAGE 3 of 3 — run via run_pipeline.sh, or standalone)

Run SAM3 (Meta's Segment Anything Model 3) over every captured frame from
02_weather_sweep_capture.py, producing a segmentation mask per class-prompt
per frame. Because frames are matched by simulation frame number across
weather folders, the masks you get for "ClearNoon/frame_000123.png" and
"HardRainNoon/frame_000123.png" describe the exact same underlying scene
under different weather.

SAM3 setup (do this once, separately — heavy dependencies):
    conda create -n sam3 python=3.12 && conda activate sam3
    pip install torch==2.10.0 torchvision --index-url https://download.pytorch.org/whl/cu128
    git clone https://github.com/facebookresearch/sam3.git && cd sam3
    pip install -e .
    hf auth login   # checkpoints are gated on Hugging Face - request access first

Usage:
    python3 03_sam3_segment.py --frames-dir ./captures --out ./masks \
        --prompts road car person bicycle
"""

import argparse
import os
from pathlib import Path

import numpy as np
from PIL import Image

from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor


def save_mask(mask, path):
    # mask: HxW boolean/float array -> single-channel PNG, 255 = foreground
    arr = (np.asarray(mask) > 0.5).astype(np.uint8) * 255
    Image.fromarray(arr).save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--frames-dir', required=True,
                     help='Root folder from 02_weather_sweep_capture.py '
                          '(contains one subfolder per weather preset).')
    ap.add_argument('--out', required=True)
    ap.add_argument('--prompts', nargs='+', default=['road', 'car', 'person', 'bicycle'],
                     help='Text prompts to segment per frame.')
    ap.add_argument('--score-threshold', type=float, default=0.5)
    args = ap.parse_args()

    print("Loading SAM3...")
    model = build_sam3_image_model()
    processor = Sam3Processor(model)

    frames_root = Path(args.frames_dir)
    weather_dirs = sorted(p for p in frames_root.iterdir() if p.is_dir())
    if not weather_dirs:
        raise SystemExit(f"No weather subfolders found under {frames_root}")

    for weather_dir in weather_dirs:
        frame_paths = sorted(weather_dir.glob('frame_*.png'))
        print(f"\n=== {weather_dir.name}: {len(frame_paths)} frames ===")

        for frame_path in frame_paths:
            image = Image.open(frame_path).convert('RGB')
            inference_state = processor.set_image(image)

            for prompt in args.prompts:
                output = processor.set_text_prompt(state=inference_state, prompt=prompt)
                masks, scores = output['masks'], output['scores']

                out_dir = Path(args.out) / weather_dir.name / prompt
                out_dir.mkdir(parents=True, exist_ok=True)

                kept = 0
                for i, (mask, score) in enumerate(zip(masks, scores)):
                    if float(score) < args.score_threshold:
                        continue
                    mask_path = out_dir / f"{frame_path.stem}_{i:02d}.png"
                    save_mask(mask, mask_path)
                    kept += 1

            print(f"  {frame_path.name}: done")

    print("\nAll frames segmented.")


if __name__ == '__main__':
    main()
