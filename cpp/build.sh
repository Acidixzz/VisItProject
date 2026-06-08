#!/usr/bin/env bash
# Build the C++ manga pipeline in WSL / Linux.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

if ! command -v cmake >/dev/null 2>&1; then
    echo "cmake not found. Install with: sudo apt install cmake"
    exit 1
fi

VTK_DIR="${VTK_DIR:-/usr/lib/x86_64-linux-gnu/cmake/vtk-9.1}"
if [[ ! -d "${VTK_DIR}" ]]; then
    echo "VTK cmake config not found at ${VTK_DIR}."
    echo "Install with: sudo apt install libvtk9-dev"
    echo "Or set VTK_DIR to your VTKConfig.cmake directory."
    exit 1
fi

cmake -S "${SCRIPT_DIR}" -B "${BUILD_DIR}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DVTK_DIR="${VTK_DIR}"
cmake --build "${BUILD_DIR}" -j"$(nproc)"

echo
echo "Built:"
echo "  ${BUILD_DIR}/build_character_mesh"
echo "  ${BUILD_DIR}/render_mesh"
echo "  ${BUILD_DIR}/manga_pipeline"
echo
echo "Linux/WSL example:"
echo "  ${BUILD_DIR}/manga_pipeline /mnt/c/path/to/luffy.jpg --z-scale 2"
echo "  ./run_all.sh luffy.jpg"
echo
echo "Mesh only:"
echo "  ${BUILD_DIR}/build_character_mesh /mnt/c/path/to/luffy.jpg --step 4 --z-scale 1"
echo
echo "Viewer only:"
echo "  ${BUILD_DIR}/render_mesh /mnt/c/path/to/luffy.vtk /mnt/c/path/to/luffy.jpg"
