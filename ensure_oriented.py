#!/usr/bin/env python3
"""Create <stem>_oriented.jpg for photos with EXIF rotation."""

import sys

from manga_pipeline import ensure_oriented


def main():
    if len(sys.argv) != 2:
        print("Usage: ensure_oriented.py <image.jpg>", file=sys.stderr)
        sys.exit(1)
    ensure_oriented(sys.argv[1])


if __name__ == "__main__":
    main()
