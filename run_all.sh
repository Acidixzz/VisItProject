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
#   ./run_all.sh --help
#
# Poly count ~ (image_width/step) * (image_height/step). Default step=12 (~350k polys).
# Use --lowpoly (step=24) for ~50k polys, or --step 32 for even fewer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/image_pipeline_env"
CPP_BUILD_DIR="$SCRIPT_DIR/cpp/build"

ensure_python_env() {
    if [[ ! -x "$VENV_DIR/bin/python" ]]; then
        echo "[setup] Creating Python environment at image_pipeline_env/..."
        python3 -m venv "$VENV_DIR"
        echo "[setup] Installing Python dependencies (first run may take a few minutes)..."
        "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
    elif ! "$VENV_DIR/bin/python" -c "import cv2" >/dev/null 2>&1; then
        echo "[setup] Python environment incomplete; installing dependencies..."
        "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
    else
        echo "[setup] Python environment OK"
    fi
    export IMAGE_PYTHON="$VENV_DIR/bin/python"
}

ensure_cpp_binaries() {
    local need_build=false
    local binaries=(
        "$CPP_BUILD_DIR/image_pipeline"
        "$CPP_BUILD_DIR/build_character_mesh"
        "$CPP_BUILD_DIR/render_mesh"
    )

    for bin in "${binaries[@]}"; do
        if [[ ! -x "$bin" ]]; then
            need_build=true
            break
        fi
    done

    if [[ "$need_build" == "true" ]]; then
        echo "[setup] Building C++ tools..."
        (cd "$SCRIPT_DIR/cpp" && ./build.sh)
    else
        echo "[setup] C++ tools OK"
    fi
}

IMAGE=""
PIPELINE_ARGS=()
HELP_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            HELP_ONLY=true
            ;;
        *)
            if [[ -z "$IMAGE" ]]; then
                IMAGE="$1"
            else
                PIPELINE_ARGS+=("$1")
            fi
            ;;
    esac
    shift
done

if [[ "$HELP_ONLY" == "true" ]]; then
    sed -n '2,11p' "$0" | sed 's/^# \?//'
    echo
    ensure_python_env
    echo
    echo "Python script flags:"
    "$IMAGE_PYTHON" "$SCRIPT_DIR/image_pipeline.py" --help
    exit 0
fi

if [[ -z "$IMAGE" ]]; then
    echo "Usage: $0 <image.jpg> [pipeline options] [--no-view]" >&2
    echo "       $0 --help" >&2
    exit 1
fi

IMAGE="$(realpath "$IMAGE")"
PIPELINE="$CPP_BUILD_DIR/image_pipeline"

echo "=== VisItProject run_all (WSL) ==="
echo "  Project: $SCRIPT_DIR"
echo "  Image:   $IMAGE"
echo

ensure_python_env
ensure_cpp_binaries

if [[ ! -x "$PIPELINE" ]]; then
    echo "Missing $PIPELINE after build." >&2
    exit 1
fi

echo "[run] Starting pipeline..."
"$PIPELINE" "$IMAGE" "${PIPELINE_ARGS[@]}"
