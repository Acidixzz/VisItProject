# make_sidecars.py — thin wrapper; use manga_pipeline.py for the full flow.

import sys

from manga_pipeline import generate_sidecars


def parse_args():
    import argparse

    p = argparse.ArgumentParser(description="Generate depth and edge sidecars.")
    p.add_argument("image_path")
    p.add_argument("--depth-model", choices=("small", "base"), default="small")
    p.add_argument("--mesh-levels", type=int, default=64)
    p.add_argument("--mesh-median", type=int, default=3)
    p.add_argument("--lineart", action="store_true", help="Depth + edges from line-art (Depth-Anything on line-art)")
    p.add_argument("--lineart-texture", action="store_true")
    p.add_argument("--paper-threshold", type=int, default=242)
    p.add_argument("--line-percentile", type=int, default=82)
    p.add_argument("--shade-lo", type=int, default=95)
    p.add_argument("--shade-hi", type=int, default=205)
    return p.parse_args()


def main():
    args = parse_args()
    generate_sidecars(
        args.image_path,
        depth_model=args.depth_model,
        mesh_levels=args.mesh_levels,
        mesh_median=args.mesh_median,
        lineart=args.lineart or args.lineart_texture,
        lineart_texture=args.lineart_texture,
        paper_threshold=args.paper_threshold,
        line_percentile=args.line_percentile,
        shade_lo=args.shade_lo,
        shade_hi=args.shade_hi,
    )


if __name__ == "__main__":
    main()
