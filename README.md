# VisItProject — Image to 3D Relief Mesh

Turn any photo or sketch into a relief-style 3D mesh. The pipeline estimates depth from your image, builds a `.vtk` mesh, and opens it in a small C++ VTK viewer with the source image as texture.

Works with photos, pencil sketches, line art, and more — not limited to manga.

## Quick start

From the repo root:

```bash
./run_all.sh /path/to/your_image.jpg
```

`run_all.sh` handles setup for you:

1. **Python** — creates `image_pipeline_env/` and installs dependencies if needed
2. **C++** — builds `image_pipeline`, `build_character_mesh`, and `render_mesh` if missing
3. **Pipeline** — generates depth, builds mesh, opens viewer

The first run can take several minutes while pip installs PyTorch and the depth model.

### Help

```bash
./run_all.sh --help
```

Shows `run_all.sh` usage plus the full list of flags for `image_pipeline.py`.

## Prerequisites (Linux / WSL)

Install system packages once:

```bash
sudo apt update
sudo apt install -y python3 python3-venv cmake build-essential libvtk9-dev
```

If VTK is not found at the default path, set `VTK_DIR` before building:

```bash
export VTK_DIR=/path/to/your/VTKConfig.cmake/dir
```

## Common options

Build mesh only (no viewer):

```bash
./run_all.sh image.jpg --no-view
```

Reuse an existing depth map (skip depth generation):

```bash
./run_all.sh image.jpg --skip-sidecars
```

Line-art mode — build clean B/W line art first, then estimate depth from it (good for pencil sketches):

```bash
./run_all.sh image.jpg --lineart
./run_all.sh image.jpg --lineart --lineart-texture   # use line art as viewer texture too
```

Coarser / faster mesh (~50k polys instead of ~350k):

```bash
./run_all.sh image.jpg --lowpoly
```

More relief height:

```bash
./run_all.sh image.jpg --z-scale 2
```

## Output files

| File | Purpose |
|------|---------|
| `*_depth.png` | Depth map — drives mesh geometry |
| `*.vtk` | Exported 3D mesh |
| `*_oriented.jpg` | EXIF-corrected copy (when the source photo needs rotation) |
| `*_lineart.jpg` | Clean B/W line art (with `--lineart`) |

Only `*_depth.png` is required for mesh geometry. The source image (or line art with `--lineart-texture`) is used for viewer texture.

## Pipeline overview

```
image.jpg  →  depth sidecar  →  VTK mesh  →  textured viewer
              (Depth-Anything)   (marching cubes)
```

- **Sidecars** — `image_pipeline.py` / `make_sidecars.py` (Python + PyTorch)
- **Mesh** — `build_character_mesh` (C++)
- **Viewer** — `render_mesh` (C++ / VTK)

## Manual commands (optional)

Build C++ tools only:

```bash
cd cpp && ./build.sh
```

Run the full pipeline via C++ orchestrator:

```bash
cpp/build/image_pipeline image.jpg --z-scale 2
```

Python entry point (same flags as above):

```bash
image_pipeline_env/bin/python image_pipeline.py image.jpg
```

Mesh only (needs existing `*_depth.png`):

```bash
cpp/build/build_character_mesh image.jpg --step 12 --z-scale 1
```

Viewer only:

```bash
cpp/build/render_mesh image.vtk image.jpg
```
