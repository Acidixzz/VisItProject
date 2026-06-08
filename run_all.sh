#!/usr/bin/env bash
# All-in-one WSL pipeline: sidecars -> mesh -> C++ VTK viewer.
#
# Usage:
#   ./run_all.sh luffy.jpg
#   ./run_all.sh luffy.jpg --z-scale 2 --skip-sidecars
#   ./run_all.sh luffy.jpg --lineart
#   ./run_all.sh luffy.jpg --lineart --lineart-texture
#   ./run_all.sh luffy.jpg --lineart --lowpoly   # recommended: line-art depth + coarse mesh
#   ./run_all.sh luffy.jpg --no-view          # build only, skip viewer
#
# Poly count ~ (image_width/step) * (image_height/step). Default step=12 (~350k polys).
# Use --lowpoly (step=24) for ~50k polys, or --step 32 for even fewer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IMAGE=""
PIPELINE_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            sed -n '2,7p' "$0" | sed 's/^# \?//'
            echo "  Pass any manga_pipeline / manga_pipeline.cpp flags after the image."
            exit 0
            ;;
        *)
            if [[ -z "$IMAGE" ]]; then
                IMAGE="$1"
            else
                PIPELINE_ARGS+=("$1")
            fi
            shift
            ;;
    esac
done

if [[ -z "$IMAGE" ]]; then
    echo "Usage: $0 <image.jpg> [pipeline options] [--no-view]" >&2
    exit 1
fi

IMAGE="$(realpath "$IMAGE")"
PIPELINE="$SCRIPT_DIR/cpp/build/manga_pipeline"

echo "=== VisItProject run_all (WSL) ==="
echo "  Project: $SCRIPT_DIR"
echo "  Image:   $IMAGE"
echo

# ---------------------------------------------------------------------------
# WSL setup: Python venv (sidecars) + C++ tools (mesh + viewer)
# ---------------------------------------------------------------------------

if [[ ! -x "$SCRIPT_DIR/manga_env/bin/python" ]]; then
    echo "[1/3] Creating Python environment..."
    python3 -m venv "$SCRIPT_DIR/manga_env"
    "$SCRIPT_DIR/manga_env/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
else
    echo "[1/3] Python environment OK"
fi

export MANGA_PYTHON="$SCRIPT_DIR/manga_env/bin/python"

if [[ ! -x "$SCRIPT_DIR/cpp/build/build_character_mesh" ]] \
    || [[ ! -x "$SCRIPT_DIR/cpp/build/render_mesh" ]]; then
    echo "[2/3] Building C++ tools..."
    (cd "$SCRIPT_DIR/cpp" && ./build.sh)
else
    echo "[2/3] C++ tools OK"
fi

if [[ ! -x "$PIPELINE" ]]; then
    echo "Missing $PIPELINE" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Run full pipeline (C++ viewer)
# ---------------------------------------------------------------------------

echo "[3/3] Running pipeline..."
"$PIPELINE" "$IMAGE" "${PIPELINE_ARGS[@]}"
