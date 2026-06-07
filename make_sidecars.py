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
    return p.parse_args()


def main():
    args = parse_args()
    generate_sidecars(
        args.image_path,
        depth_model=args.depth_model,
        mesh_levels=args.mesh_levels,
        mesh_median=args.mesh_median,
    )


if __name__ == "__main__":
    main()
