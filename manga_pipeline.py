#!/usr/bin/env python3
"""
End-to-end manga mesh pipeline:
  1. Generate *_depth.png and *_edges.png sidecars
  2. Build character mesh from depth (VisIt GetCharacterMesh logic)
  3. Preview in VTK with the source image as texture (C++ viewer)

Usage:
  python manga_pipeline.py luffy.jpg
  python manga_pipeline.py luffy.jpg --step 2 --z-scale 2.0 --depth-model base
  python manga_pipeline.py luffy.jpg --skip-sidecars --no-view
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

import cv2
import numpy as np
import vtk
from PIL import Image, ImageFilter, ImageOps
from transformers import pipeline
from vtk.util import numpy_support

DEPTH_MODELS = {
    "small": "depth-anything/Depth-Anything-V2-Small-hf",
    "base": "depth-anything/Depth-Anything-V2-Base-hf",
}

_depth_pipeline = None


# ---------------------------------------------------------------------------
# Sidecars (from make_sidecars.py)
# ---------------------------------------------------------------------------


def normalize_u8(arr, lo_pct=2, hi_pct=98):
    arr = arr.astype(np.float32)
    lo, hi = np.percentile(arr, [lo_pct, hi_pct])
    if hi <= lo:
        lo, hi = arr.min(), arr.max()
    arr = np.clip(arr, lo, hi)
    if hi > lo:
        arr = (arr - lo) / (hi - lo)
    return (arr * 255).astype(np.uint8)


def _get_depth_pipeline(model_key="small"):
    global _depth_pipeline
    model_id = DEPTH_MODELS.get(model_key, DEPTH_MODELS["small"])
    if _depth_pipeline is None or getattr(_depth_pipeline, "_model_id", None) != model_id:
        _depth_pipeline = pipeline("depth-estimation", model=model_id)
        _depth_pipeline._model_id = model_id
    return _depth_pipeline


def prepare_depth_for_mesh(depth_u8, median_ksize=3, levels=64):
    depth = depth_u8.copy()
    if median_ksize > 1:
        k = int(median_ksize) | 1
        depth = cv2.medianBlur(depth, k)
    levels = int(np.clip(levels, 16, 256))
    quantized = np.round(depth.astype(np.float32) / 255.0 * (levels - 1))
    return (quantized / (levels - 1) * 255).astype(np.uint8)


def make_depth(
    img,
    model_key="small",
    inference_max_side=1280,
    mesh_levels=64,
    mesh_median=3,
):
    w, h = img.size
    work = img
    if max(w, h) > inference_max_side:
        scale = inference_max_side / max(w, h)
        work = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    pipe = _get_depth_pipeline(model_key)
    result = pipe(work)
    pred = result["predicted_depth"]
    if hasattr(pred, "squeeze"):
        pred = pred.squeeze().detach().cpu().numpy()

    depth = normalize_u8(pred)
    depth = np.array(Image.fromarray(depth).resize(img.size, Image.Resampling.LANCZOS))
    depth = prepare_depth_for_mesh(depth, median_ksize=mesh_median, levels=mesh_levels)
    return Image.fromarray(depth)

def make_lineart_bw(
    img,
    paper_threshold=242,
    paper_percentile=58,
    line_percentile=82,
    shade_lo=95,
    shade_hi=205,
    line_dilate=1,
):
    """
    Convert a pencil sketch to clean B/W for depth estimation:
      - linework -> black (0)
      - open paper / unfilled areas -> white (255)
      - tonal shading -> mid grays (shade_lo .. shade_hi)
    """
    rgb = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    tone = cv2.GaussianBlur(gray, (5, 5), 0)
    blackhat = cv2.morphologyEx(tone, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    gx = cv2.Sobel(tone, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(tone, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(gx, gy)

    # Photo paper is often off-white; use adaptive bright-pixel cutoff.
    adaptive_paper = np.percentile(tone, paper_percentile)
    paper_cutoff = min(paper_threshold, adaptive_paper)
    paper = tone >= paper_cutoff

    stroke = np.maximum(blackhat.astype(np.float32), grad)
    if np.any(~paper):
        thresh = np.percentile(stroke[~paper], line_percentile)
    else:
        thresh = np.percentile(stroke, line_percentile)
    lines = (stroke >= thresh) & ~paper

    if line_dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * line_dilate + 1, 2 * line_dilate + 1))
        lines = cv2.dilate(lines.astype(np.uint8), k, iterations=1).astype(bool)

    shading = ~paper & ~lines

    out = np.full_like(gray, 255, dtype=np.uint8)
    if np.any(shading):
        s_vals = tone[shading].astype(np.float32)
        lo, hi = np.percentile(s_vals, [3, 97])
        if hi <= lo:
            mapped = np.full(s_vals.shape, 0.5, dtype=np.float32)
        else:
            mapped = np.clip((s_vals - lo) / (hi - lo), 0.0, 1.0)
            # Darker pencil tone -> darker gray (more depth relief).
            mapped = 1.0 - mapped
        out[shading] = (shade_lo + mapped * (shade_hi - shade_lo)).astype(np.uint8)

    out[lines] = 0
    out[paper] = 255
    return Image.fromarray(out).convert("RGB")


def _resolve_mesh_image_path(image_path, source, folder, stem):
    """
    C++ reads JPEGs without EXIF rotation; save an oriented copy when needed so
    depth sidecars and mesh geometry share the same pixel layout.
    """
    raw = Image.open(image_path)
    exif_orient = raw.getexif().get(274)
    oriented_path = os.path.join(folder, f"{stem}_oriented.jpg")
    if exif_orient not in (None, 1):
        source.save(oriented_path, quality=95)
        print(f"Wrote {oriented_path} (EXIF orientation {exif_orient})")
        return oriented_path
    return image_path


def resolve_mesh_image_path(image_path):
    """Pick oriented JPEG for mesh/texture if a prior run created one."""
    folder = os.path.dirname(os.path.abspath(image_path))
    stem = os.path.splitext(os.path.basename(image_path))[0]
    oriented_path = os.path.join(folder, f"{stem}_oriented.jpg")
    if os.path.isfile(oriented_path):
        return oriented_path
    return image_path


def ensure_oriented(image_path):
    """Create <stem>_oriented.jpg when EXIF rotation is present."""
    image_path = os.path.abspath(image_path)
    folder = os.path.dirname(image_path)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    oriented_path = os.path.join(folder, f"{stem}_oriented.jpg")
    raw = Image.open(image_path)
    exif_orient = raw.getexif().get(274)
    if exif_orient in (None, 1):
        return image_path
    source = ImageOps.exif_transpose(raw).convert("RGB")
    source.save(oriented_path, quality=95)
    print(f"Wrote {oriented_path} (EXIF orientation {exif_orient})")
    return oriented_path


def generate_sidecars(
    image_path,
    depth_model="small",
    mesh_levels=64,
    mesh_median=3,
    lineart=False,
    lineart_texture=False,
    paper_threshold=242,
    line_percentile=82,
    shade_lo=95,
    shade_hi=205,
):
    raw = Image.open(image_path)
    source = ImageOps.exif_transpose(raw).convert("RGB")
    img = source
    folder = os.path.dirname(os.path.abspath(image_path))
    stem = os.path.splitext(os.path.basename(image_path))[0]
    mesh_image_path = _resolve_mesh_image_path(image_path, source, folder, stem)

    depth_path = os.path.join(folder, f"{stem}_depth.png")
    edges_path = os.path.join(folder, f"{stem}_edges.png")

    lineart_img = None
    if lineart:
        print("Building line-art B/W (black lines, white paper, gray shading)...")
        lineart_img = make_lineart_bw(
            source,
            paper_threshold=paper_threshold,
            line_percentile=line_percentile,
            shade_lo=shade_lo,
            shade_hi=shade_hi,
        )
        lineart_path = os.path.join(folder, f"{stem}_lineart.jpg")
        lineart_img.save(lineart_path, quality=95)
        print(f"Wrote {lineart_path}")
        if lineart_texture:
            img = lineart_img

    depth_source = lineart_img if lineart_img is not None else source
    if lineart_img is not None:
        print("Generating depth map (Depth-Anything on line-art)...")
    else:
        print("Generating depth map (Depth-Anything on source photo)...")
    depth = make_depth(
        depth_source,
        model_key=depth_model,
        mesh_levels=mesh_levels,
        mesh_median=mesh_median,
    )

    depth.save(depth_path)
    print(f"Wrote {depth_path}")
    return depth_path, mesh_image_path


# ---------------------------------------------------------------------------
# Character mesh (VisIt avtImageFileFormat::GetCharacterMesh)
# ---------------------------------------------------------------------------


def _depth_sample_grid(depth_hw, full_x, full_y, step):
    """Sample depth on the characterStep grid (matches VisIt GetCharacterMesh)."""
    dh, dw = depth_hw.shape
    if dh != full_y or dw != full_x:
        depth_hw = cv2.resize(depth_hw, (full_x, full_y), interpolation=cv2.INTER_LINEAR)

    xdim = (full_x + step - 1) // step
    ydim = (full_y + step - 1) // step
    src_x = np.minimum(np.arange(xdim) * step, full_x - 1)
    src_y = np.minimum(np.arange(ydim) * step, full_y - 1)

    # NumPy is (row, col) = (src_y, src_x). VisIt only swaps when depth VTK dims
    # are transposed (depthDims[0]==fullY && depthDims[1]==fullX); PIL sidecars
    # match the source image, so use direct sampling.
    sampled = depth_hw[src_y[:, None], src_x[None, :]]

    return sampled.astype(np.float32) / 255.0


def _build_character_mesh_python(
    image_path,
    depth_path=None,
    step=4,
    zdim=96,
    z_world_max=400.0,
    z_scale=1.0,
):
    """
    Port of GetCharacterMesh(): extrude depth columns into a volume, marching cubes.
    """
    img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    full_x, full_y = img.size

    if depth_path is None:
        stem = os.path.splitext(os.path.basename(image_path))[0]
        folder = os.path.dirname(os.path.abspath(image_path))
        depth_path = os.path.join(folder, f"{stem}_depth.png")

    depth_img = Image.open(depth_path).convert("L")
    depth_hw = np.array(depth_img)

    xdim = (full_x + step - 1) // step
    ydim = (full_y + step - 1) // step

    z_world_max = float(z_world_max) * float(z_scale)
    z_spacing = z_world_max / float(zdim - 1)
    pad = 1
    vol_x = xdim + 2 * pad
    vol_y = ydim + 2 * pad
    vol_z = zdim + 2

    depth_values = _depth_sample_grid(depth_hw, full_x, full_y, step)
    heights = 1 + (depth_values * (zdim - 1)).astype(np.int32)
    np.clip(heights, 1, zdim - 1, out=heights)

    volume = np.zeros((vol_z, vol_y, vol_x), dtype=np.uint8)
    for z in range(1, zdim):
        volume[z, pad : pad + ydim, pad : pad + xdim] = np.where(
            heights >= z, np.uint8(255), np.uint8(0)
        )

    vtk_volume = vtk.vtkImageData()
    vtk_volume.SetDimensions(vol_x, vol_y, vol_z)
    vtk_volume.SetSpacing(float(step), float(step), z_spacing)
    vtk_volume.SetOrigin(float(-pad * step), float(-pad * step), -z_spacing)
    vtk_volume.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)

    # VTK expects Fortran (x fastest) ordering for SetDimensions(x,y,z).
    flat = np.asfortranarray(volume).ravel(order="F")
    scalars = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
    vtk_volume.GetPointData().SetScalars(scalars)

    mc = vtk.vtkMarchingCubes()
    mc.SetInputData(vtk_volume)
    mc.SetValue(0, 127.5)
    mc.ComputeNormalsOff()
    mc.ComputeGradientsOff()
    mc.Update()

    poly = vtk.vtkPolyData()
    poly.DeepCopy(mc.GetOutput())

    tcoords = vtk.vtkFloatArray()
    tcoords.SetName("TextureCoordinates")
    tcoords.SetNumberOfComponents(2)
    tcoords.SetNumberOfTuples(poly.GetNumberOfPoints())

    denom_x = max(full_x - 1, 1)
    denom_y = max(full_y - 1, 1)

    for i in range(poly.GetNumberOfPoints()):
        p = poly.GetPoint(i)
        u = float(np.clip(p[0] / denom_x, 0.0, 1.0))
        v = float(np.clip(p[1] / denom_y, 0.0, 1.0))
        tcoords.SetTuple2(i, u, v)

    poly.GetPointData().Initialize()
    poly.GetPointData().SetTCoords(tcoords)

    folder = os.path.dirname(os.path.abspath(image_path))
    stem = os.path.splitext(os.path.basename(image_path))[0]
    vtk_path = os.path.join(folder, f"{stem}.vtk")

    writer = vtk.vtkPolyDataWriter()
    writer.SetFileName(vtk_path)
    writer.SetInputData(poly)
    writer.SetFileTypeToBinary()
    writer.Write()

    print(f"Mesh: {poly.GetNumberOfPoints()} points, {poly.GetNumberOfPolys()} polys")
    print(f"Wrote {vtk_path}")
    return vtk_path, poly


def _find_cpp_mesh_builder():
    """Return path to C++ build_character_mesh if built, else None."""
    env = os.environ.get("MESH_BUILDER")
    if env and os.path.isfile(env):
        return env

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "cpp", "build", "build_character_mesh"),
        os.path.join(here, "cpp", "build", "build_character_mesh.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def build_character_mesh_cpp(
    image_path,
    depth_path=None,
    step=4,
    zdim=96,
    z_world_max=400.0,
    z_scale=1.0,
    mesh_builder=None,
):
    """Run the C++ mesh builder (fast path for WSL/Linux)."""
    mesh_builder = mesh_builder or _find_cpp_mesh_builder()
    if not mesh_builder:
        raise FileNotFoundError(
            "C++ mesh builder not found. Build in WSL: cd cpp && ./build.sh"
        )

    image_path = os.path.abspath(image_path)
    folder = os.path.dirname(image_path)
    stem = os.path.splitext(os.path.basename(image_path))[0]
    vtk_path = os.path.join(folder, f"{stem}.vtk")

    if depth_path is None:
        depth_path = os.path.join(folder, f"{stem}_depth.png")
    depth_path = os.path.abspath(depth_path)

    cmd = [
        mesh_builder,
        image_path,
        "--depth",
        depth_path,
        "--output",
        vtk_path,
        "--step",
        str(step),
        "--zdim",
        str(zdim),
        "--z-max",
        str(z_world_max),
        "--z-scale",
        str(z_scale),
    ]
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    return vtk_path, None


def build_character_mesh(
    image_path,
    depth_path=None,
    step=4,
    zdim=96,
    z_world_max=400.0,
    z_scale=1.0,
    use_cpp=False,
    mesh_builder=None,
):
    if use_cpp:
        return build_character_mesh_cpp(
            image_path,
            depth_path=depth_path,
            step=step,
            zdim=zdim,
            z_world_max=z_world_max,
            z_scale=z_scale,
            mesh_builder=mesh_builder,
        )

    return _build_character_mesh_python(
        image_path,
        depth_path=depth_path,
        step=step,
        zdim=zdim,
        z_world_max=z_world_max,
        z_scale=z_scale,
    )


def _find_cpp_renderer():
    """Return path to C++ render_mesh if built, else None."""
    env = os.environ.get("RENDER_MESH")
    if env and os.path.isfile(env):
        return env

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "cpp", "build", "render_mesh"),
        os.path.join(here, "cpp", "build", "render_mesh.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def view_mesh(vtk_path, image_path, flip_v=False):
    """Open the C++ VTK viewer."""
    renderer = _find_cpp_renderer()
    if not renderer:
        raise FileNotFoundError(
            "C++ viewer not found. Build in WSL: cd cpp && ./build.sh"
        )

    cmd = [renderer, os.path.abspath(vtk_path), os.path.abspath(image_path)]
    if flip_v:
        cmd.append("--flip-v")
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser(
        description="Sidecars -> VTK character mesh -> textured preview (one command)."
    )
    p.add_argument("image_path", help="Source image (e.g. luffy.jpg)")
    p.add_argument("--skip-sidecars", action="store_true", help="Use existing *_depth.png / *_edges.png")
    p.add_argument("--depth-model", choices=("small", "base"), default="small")
    p.add_argument("--mesh-levels", type=int, default=64, help="Depth quantization steps (default 64)")
    p.add_argument("--mesh-median", type=int, default=3, help="Median filter on depth (0=off)")
    p.add_argument("--step", type=int, default=12, help="XY subsample step (higher=fewer polys, default 12)")
    p.add_argument("--zdim", type=int, default=48, help="Depth volume Z resolution (default 48)")
    p.add_argument("--z-max", type=float, default=400.0, help="World Z extent (VisIt zWorldMax)")
    p.add_argument(
        "--z-scale",
        type=float,
        default=1.0,
        help="Multiply Z relief for preview/export (try 2-5 if mesh looks flat)",
    )
    p.add_argument("--no-view", action="store_true", help="Build sidecars + VTK only, skip interactive viewer")
    p.add_argument("--flip-v", action="store_true", help="Flip texture V in the viewer")
    p.add_argument("--sidecars-only", action="store_true", help="Only generate depth/edges, no mesh")
    p.add_argument(
        "--mesh-cpp",
        action="store_true",
        help="Use C++ mesh builder (build in WSL: cd cpp && ./build.sh)",
    )
    p.add_argument(
        "--mesh-python",
        action="store_true",
        help="Force Python mesh builder even if C++ binary exists",
    )
    p.add_argument(
        "--lineart",
        action="store_true",
        help="Build B/W line-art; depth and edges from line-art (Depth-Anything on line-art)",
    )
    p.add_argument(
        "--lineart-texture",
        action="store_true",
        help="Use line-art image as mesh texture too (implies --lineart)",
    )
    p.add_argument("--paper-threshold", type=int, default=242, help="Line-art: luminance for white paper")
    p.add_argument("--line-percentile", type=int, default=82, help="Line-art: edge sensitivity (lower=more lines)")
    p.add_argument("--shade-lo", type=int, default=95, help="Line-art: darkest gray for shading")
    p.add_argument("--shade-hi", type=int, default=205, help="Line-art: lightest gray for shading")
    p.add_argument(
        "--lowpoly",
        action="store_true",
        help="Coarse mesh preset: --step 24 --zdim 24 --mesh-levels 16",
    )
    return p.parse_args()


def main():
    args = parse_args()
    if args.lowpoly:
        args.step = 24
        args.zdim = 24
        args.mesh_levels = 16
        print("Low-poly preset: step=24, zdim=24, mesh_levels=16")

    image_path = os.path.abspath(args.image_path)
    if not os.path.isfile(image_path):
        print(f"Not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    depth_path = None
    mesh_image_path = ensure_oriented(image_path)
    texture_path = mesh_image_path
    if args.skip_sidecars:
        stem = os.path.splitext(os.path.basename(image_path))[0]
        folder = os.path.dirname(image_path)
        depth_path = os.path.join(folder, f"{stem}_depth.png")
        if not os.path.isfile(depth_path):
            print(f"Missing {depth_path}; drop --skip-sidecars", file=sys.stderr)
            sys.exit(1)
        print(f"Using existing sidecars under {folder}")
    else:
        lineart = args.lineart or args.lineart_texture
        depth_path, mesh_image_path = generate_sidecars(
            image_path,
            depth_model=args.depth_model,
            mesh_levels=args.mesh_levels,
            mesh_median=args.mesh_median,
            lineart=lineart,
            lineart_texture=args.lineart_texture,
            paper_threshold=args.paper_threshold,
            line_percentile=args.line_percentile,
            shade_lo=args.shade_lo,
            shade_hi=args.shade_hi,
        )
        texture_path = mesh_image_path
        if args.lineart_texture:
            texture_path = os.path.join(
                os.path.dirname(image_path),
                f"{os.path.splitext(os.path.basename(image_path))[0]}_lineart.jpg",
            )

    if args.sidecars_only:
        return

    use_cpp = args.mesh_cpp
    if not args.mesh_python and not use_cpp and _find_cpp_mesh_builder():
        use_cpp = True
        print("Using C++ mesh builder (cpp/build/build_character_mesh)")

    print("Building character mesh...")
    vtk_path, _poly = build_character_mesh(
        mesh_image_path,
        depth_path=depth_path,
        step=args.step,
        zdim=args.zdim,
        z_world_max=args.z_max,
        z_scale=args.z_scale,
        use_cpp=use_cpp,
    )

    if args.no_view:
        return

    print("Opening viewer...")
    view_mesh(vtk_path, texture_path, flip_v=args.flip_v)


if __name__ == "__main__":
    main()
