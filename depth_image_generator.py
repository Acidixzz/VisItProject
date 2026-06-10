#!/usr/bin/env python3
"""
Generate a *_depth.png sidecar from an input image using Depth-Anything V2 Base.

Optional --lineart builds clean B/W line art first and runs depth on that instead.
Mesh build and viewer are handled by the C++ tools (see run_all.sh).
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageOps
from transformers import pipeline

DEPTH_MODEL_ID = "depth-anything/Depth-Anything-V2-Base-hf"
DEPTH_LEVELS = 64
DEPTH_MEDIAN = 3

_depth_pipeline = None


def normalize_u8(arr, lo_pct=2, hi_pct=98):
    arr = arr.astype(np.float32)
    lo, hi = np.percentile(arr, [lo_pct, hi_pct])
    if hi <= lo:
        lo, hi = arr.min(), arr.max()
    arr = np.clip(arr, lo, hi)
    if hi > lo:
        arr = (arr - lo) / (hi - lo)
    return (arr * 255).astype(np.uint8)


def _get_depth_pipeline():
    global _depth_pipeline
    if _depth_pipeline is None:
        _depth_pipeline = pipeline("depth-estimation", model=DEPTH_MODEL_ID)
    return _depth_pipeline


def prepare_depth_for_mesh(depth_u8, median_ksize=DEPTH_MEDIAN, levels=DEPTH_LEVELS):
    depth = depth_u8.copy()
    if median_ksize > 1:
        k = int(median_ksize) | 1
        depth = cv2.medianBlur(depth, k)
    levels = int(np.clip(levels, 16, 256))
    quantized = np.round(depth.astype(np.float32) / 255.0 * (levels - 1))
    return (quantized / (levels - 1) * 255).astype(np.uint8)


def make_depth(img, inference_max_side=1280):
    w, h = img.size
    work = img
    if max(w, h) > inference_max_side:
        scale = inference_max_side / max(w, h)
        work = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    pipe = _get_depth_pipeline()
    result = pipe(work)
    pred = result["predicted_depth"]
    if hasattr(pred, "squeeze"):
        pred = pred.squeeze().detach().cpu().numpy()

    depth = normalize_u8(pred)
    depth = np.array(Image.fromarray(depth).resize(img.size, Image.Resampling.LANCZOS))
    depth = prepare_depth_for_mesh(depth)
    return Image.fromarray(depth)


def make_lineart_bw(
    img,
    paper_threshold=242,
    paper_percentile=58,
    line_percentile=82,
    shade_lo=95,
    shade_hi=205,
    line_dilate=1,
):
    """Convert a pencil sketch to clean B/W for depth estimation."""
    rgb = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    tone = cv2.GaussianBlur(gray, (5, 5), 0)
    blackhat = cv2.morphologyEx(
        tone, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    )

    gx = cv2.Sobel(tone, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(tone, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(gx, gy)

    adaptive_paper = np.percentile(tone, paper_percentile)
    paper_cutoff = min(paper_threshold, adaptive_paper)
    paper = tone >= paper_cutoff

    stroke = np.maximum(blackhat.astype(np.float32), grad)
    if np.any(~paper):
        thresh = np.percentile(stroke[~paper], line_percentile)
    else:
        thresh = np.percentile(stroke, line_percentile)
    lines = (stroke >= thresh) & ~paper

    if line_dilate > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * line_dilate + 1, 2 * line_dilate + 1)
        )
        lines = cv2.dilate(lines.astype(np.uint8), k, iterations=1).astype(bool)

    shading = ~paper & ~lines

    out = np.full_like(gray, 255, dtype=np.uint8)
    if np.any(shading):
        s_vals = tone[shading].astype(np.float32)
        lo, hi = np.percentile(s_vals, [3, 97])
        if hi <= lo:
            mapped = np.full(s_vals.shape, 0.5, dtype=np.float32)
        else:
            mapped = np.clip((s_vals - lo) / (hi - lo), 0.0, 1.0)
            mapped = 1.0 - mapped
        out[shading] = (shade_lo + mapped * (shade_hi - shade_lo)).astype(np.uint8)

    out[lines] = 0
    out[paper] = 255
    return Image.fromarray(out).convert("RGB")


def _write_oriented_jpeg_if_needed(image_path, source, folder, stem):
    """C++ JPEG reader ignores EXIF; bake rotation into *_oriented.jpg when needed."""
    raw = Image.open(image_path)
    exif_orient = raw.getexif().get(274)
    oriented_path = os.path.join(folder, f"{stem}_oriented.jpg")
    if exif_orient not in (None, 1):
        source.save(oriented_path, quality=95)
        print(f"Wrote {oriented_path} (EXIF orientation {exif_orient})")


def generate_depth(image_path, lineart=False):
    raw = Image.open(image_path)
    source = ImageOps.exif_transpose(raw).convert("RGB")
    folder = os.path.dirname(os.path.abspath(image_path))
    stem = os.path.splitext(os.path.basename(image_path))[0]
    _write_oriented_jpeg_if_needed(image_path, source, folder, stem)

    depth_path = os.path.join(folder, f"{stem}_depth.png")

    lineart_img = None
    if lineart:
        print("Building line-art B/W (black lines, white paper, gray shading)...")
        lineart_img = make_lineart_bw(source)
        lineart_path = os.path.join(folder, f"{stem}_lineart.jpg")
        lineart_img.save(lineart_path, quality=95)
        print(f"Wrote {lineart_path}")

    depth_source = lineart_img if lineart_img is not None else source
    if lineart_img is not None:
        print("Generating depth map (Depth-Anything on line-art)...")
    else:
        print("Generating depth map (Depth-Anything on source image)...")
    depth = make_depth(depth_source)

    depth.save(depth_path)
    print(f"Wrote {depth_path}")
    return depth_path


def parse_args():
    p = argparse.ArgumentParser(description="Generate *_depth.png from an input image.")
    p.add_argument("image_path", help="Source image (e.g. luffy.jpg)")
    p.add_argument(
        "--lineart",
        action="store_true",
        help="Build B/W line-art first, then estimate depth from it",
    )
    p.add_argument(
        "--lineart-texture",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return p.parse_args()


def main():
    args = parse_args()
    image_path = os.path.abspath(args.image_path)
    if not os.path.isfile(image_path):
        print(f"Not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    generate_depth(image_path, lineart=args.lineart or args.lineart_texture)


if __name__ == "__main__":
    main()
