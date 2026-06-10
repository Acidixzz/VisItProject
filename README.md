# VisItProject — Image to 3D Relief Mesh

Turn any photo or sketch into a relief-style 3D mesh and view it interactively.

## Quick start

From the repo root:

```bash
./run_all.sh /path/to/your_image.jpg
```

`run_all.sh` handles everything:

1. **Python** — creates `image_pipeline_env/` and installs dependencies if needed
2. **C++** — builds `image_pipeline`, `build_character_mesh`, and `render_mesh` if missing
3. **Pipeline** — generates depth, builds mesh, opens viewer

The first run can take several minutes while pip installs PyTorch and the depth model.

### Help

```bash
./run_all.sh --help
```

Shows usage plus all pipeline flags.

## Prerequisites (Linux / WSL)

```bash
sudo apt update
sudo apt install -y python3 python3-venv cmake build-essential libvtk9-dev
```

If VTK is not found at the default path:

```bash
export VTK_DIR=/path/to/your/VTKConfig.cmake/dir
```

## Common options

```bash
./run_all.sh image.jpg --no-view          # build mesh, skip viewer
./run_all.sh image.jpg --skip-sidecars    # reuse existing *_depth.png
./run_all.sh image.jpg --lineart          # depth from cleaned line art (sketches)
./run_all.sh image.jpg --lineart --lineart-texture
./run_all.sh image.jpg --lowpoly          # coarser / faster mesh
./run_all.sh image.jpg --z-scale 2        # taller relief
```

## Output files

| File | Purpose |
|------|---------|
| `*_depth.png` | Depth map — drives mesh geometry |
| `*.vtk` | Exported 3D mesh |
| `*_oriented.jpg` | EXIF-corrected copy (when the source photo needs rotation) |
| `*_lineart.jpg` | Clean B/W line art (with `--lineart`) |

## How it works

```
image.jpg  →  depth sidecar  →  VTK mesh  →  textured viewer
              (Depth-Anything)   (marching cubes)
```

All logic lives in `image_pipeline.py` (Python depth/line-art) and the C++ tools under `cpp/build/`.
