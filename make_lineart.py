#!/usr/bin/env python3
"""Create a clean B/W line-art image from a pencil sketch."""

import argparse
import os

from manga_pipeline import make_lineart_bw
from PIL import Image, ImageOps


def parse_args():
    p = argparse.ArgumentParser(
        description="Black lines, white paper, gray shading — tuned for depth/mesh relief."
    )
    p.add_argument("image_path")
    p.add_argument("-o", "--output", help="Output path (default: <stem>_lineart.jpg)")
    p.add_argument("--paper-threshold", type=int, default=242)
    p.add_argument("--line-percentile", type=int, default=82, help="Lower = more black lines")
    p.add_argument("--shade-lo", type=int, default=95)
    p.add_argument("--shade-hi", type=int, default=205)
    return p.parse_args()


def main():
    args = parse_args()
    img = ImageOps.exif_transpose(Image.open(args.image_path)).convert("RGB")
    out = make_lineart_bw(
        img,
        paper_threshold=args.paper_threshold,
        line_percentile=args.line_percentile,
        shade_lo=args.shade_lo,
        shade_hi=args.shade_hi,
    )

    if args.output:
        out_path = args.output
    else:
        folder = os.path.dirname(os.path.abspath(args.image_path))
        stem = os.path.splitext(os.path.basename(args.image_path))[0]
        out_path = os.path.join(folder, f"{stem}_lineart.jpg")

    out.save(out_path, quality=95)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
