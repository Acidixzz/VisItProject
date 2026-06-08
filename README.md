# VisItProject Photo/Sketch -> 3D Mesh Pipeline

This repo turns an input image (photo or sketch) into a relief-style 3D mesh using sidecar depth maps, then exports a `.vtk` mesh and shows it in a small C++ VTK viewer.

## Prerequisites (Linux/WSL)

1. **Python 3 + venv support**
2. **CMake** and a C++ compiler toolchain
3. **VTK dev files** (the C++ build looks for a VTK CMake config)

On Ubuntu/Debian (common case), you can try:

```bash
sudo apt update
sudo apt install -y cmake build-essential libvtk9-dev
```

If your VTK CMake config is not in the default location, set `VTK_DIR` when building C++:

```bash
export VTK_DIR=/path/to/your/VTKConfig.cmake/dir
```

## Install (Python deps)

Python dependencies are installed automatically the first time you run `./run_all.sh` (it creates `image_pipeline_env/` and installs `requirements.txt`).

## Build C++ tools (automatic)

`./run_all.sh` will also automatically build the C++ tools (mesh + viewer) if needed.

## Run with any image

From the repo root (`VisItProject/`):

```bash
./run_all.sh /path/to/your_image.jpg
```

This will generate files like:
- `*_depth.png` (used for mesh geometry)
- `*.vtk` (the exported mesh)
- optionally `*_lineart.jpg` / `*_edges.png` (sidecars)

### Helpful options

```bash
./run_all.sh /path/to/image.jpg --no-view
```
Build sidecars + `.vtk`, but skip the interactive viewer.

```bash
./run_all.sh /path/to/image.jpg --skip-sidecars
```
Reuse existing `*_depth.png` (faster). You must already have them.

Line-art mode builds line-art first, then use it for depth (recommended for pencil sketches):
```bash
./run_all.sh /path/to/image.jpg --lineart
./run_all.sh /path/to/image.jpg --lineart --lineart-texture
```

Coarser/faster mesh:
```bash
./run_all.sh /path/to/image.jpg --lowpoly
```

## Direct commands (optional)

If you want to build/run parts directly:

1. C++ build:
```bash
cd cpp
./build.sh
```

2. Mesh only:
```bash
cpp/build/build_character_mesh /path/to/image.jpg --step 12 --z-scale 1
```

3. Viewer:
```bash
cpp/build/render_mesh /path/to/image.vtk /path/to/image.jpg
```

