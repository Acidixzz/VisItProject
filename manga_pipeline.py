#!/usr/bin/env python3
"""
End-to-end manga mesh pipeline:
  1. Generate *_depth.png and *_edges.png sidecars
  2. Build character mesh from depth (VisIt GetCharacterMesh logic)
  3. Preview in VTK with the source image as texture

Usage:
  python manga_pipeline.py luffy.jpg
  python manga_pipeline.py luffy.jpg --step 2 --z-scale 2.0 --depth-model base
  python manga_pipeline.py luffy.jpg --skip-sidecars --no-view
"""

from __future__ import annotations

import argparse
import os
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


def make_edges(img):
    return img.convert("L").filter(ImageFilter.FIND_EDGES)


def generate_sidecars(
    image_path,
    depth_model="small",
    mesh_levels=64,
    mesh_median=3,
):
    img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    folder = os.path.dirname(os.path.abspath(image_path))
    stem = os.path.splitext(os.path.basename(image_path))[0]

    depth_path = os.path.join(folder, f"{stem}_depth.png")
    edges_path = os.path.join(folder, f"{stem}_edges.png")

    print("Generating depth map...")
    depth = make_depth(
        img,
        model_key=depth_model,
        mesh_levels=mesh_levels,
        mesh_median=mesh_median,
    )
    print("Generating edges...")
    edges = make_edges(img)

    depth.save(depth_path)
    edges.save(edges_path)
    print(f"Wrote {depth_path}")
    print(f"Wrote {edges_path}")
    return depth_path, edges_path, img


# ---------------------------------------------------------------------------
# Character mesh (VisIt avtImageFileFormat::GetCharacterMesh)
# ---------------------------------------------------------------------------


def _depth_sample_grid(depth_hw, full_x, full_y, step):
    """Sample depth on the characterStep grid (matches VisIt GetCharacterMesh)."""
    xdim = (full_x + step - 1) // step
    ydim = (full_y + step - 1) // step
    src_x = np.minimum(np.arange(xdim) * step, full_x - 1)
    src_y = np.minimum(np.arange(ydim) * step, full_y - 1)

    dh, dw = depth_hw.shape
    if dh == full_y and dw == full_x:
        # Transposed depth sidecar (VisIt axis swap).
        sampled = depth_hw[(dw - 1 - src_y)[:, None], src_x[None, :]]
    else:
        sampled = depth_hw[src_y[:, None], src_x[None, :]]

    return sampled.astype(np.float32) / 255.0


def build_character_mesh(
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
    mc.ComputeNormalsOn()
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

    poly.GetPointData().SetTCoords(tcoords)

    folder = os.path.dirname(os.path.abspath(image_path))
    stem = os.path.splitext(os.path.basename(image_path))[0]
    vtk_path = os.path.join(folder, f"{stem}.vtk")

    writer = vtk.vtkPolyDataWriter()
    writer.SetFileName(vtk_path)
    writer.SetInputData(poly)
    writer.Write()

    print(f"Mesh: {poly.GetNumberOfPoints()} points, {poly.GetNumberOfPolys()} polys")
    print(f"Wrote {vtk_path}")
    return vtk_path, poly


# ---------------------------------------------------------------------------
# Render (from render.py)
# ---------------------------------------------------------------------------


def load_texture(path):
    with open(path, "rb") as f:
        header = f.read(12)

    if header.startswith(b"\xff\xd8\xff"):
        reader = vtk.vtkJPEGReader()
    elif header.startswith(b"\x89PNG\r\n\x1a\n"):
        reader = vtk.vtkPNGReader()
    else:
        rgb = np.array(Image.open(path).convert("RGB"))
        h, w, _ = rgb.shape
        vtk_data = vtk.vtkImageData()
        vtk_data.SetDimensions(w, h, 1)
        vtk_data.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 3)
        flat = np.flipud(rgb).reshape(-1, 3)
        scalars = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
        vtk_data.GetPointData().SetScalars(scalars)
        return vtk_data

    reader.SetFileName(path)
    reader.Update()
    return reader.GetOutput()


def render_mesh(
    polydata,
    texture_path,
    flip_v=False,
    window_size=(1200, 900),
):
    if polydata.GetPointData().GetTCoords() is None:
        raise RuntimeError("Mesh has no texture coordinates")

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(polydata)
    mapper.ScalarVisibilityOff()

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)

    texture = vtk.vtkTexture()
    texture.SetInputData(load_texture(texture_path))
    texture.InterpolateOn()
    actor.SetTexture(texture)

    if flip_v:
        # Re-flip V if preview looks upside down vs VisIt.
        tcoords = polydata.GetPointData().GetTCoords()
        for i in range(tcoords.GetNumberOfTuples()):
            u, v = tcoords.GetTuple2(i)
            tcoords.SetTuple2(i, u, 1.0 - v)

    renderer = vtk.vtkRenderer()
    renderer.AddActor(actor)
    renderer.SetBackground(0.08, 0.08, 0.08)

    window = vtk.vtkRenderWindow()
    window.AddRenderer(renderer)
    window.SetSize(*window_size)

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

    renderer.ResetCamera()
    camera = renderer.GetActiveCamera()
    camera.Azimuth(45)
    camera.Elevation(35)
    camera.Zoom(1.2)

    window.Render()
    interactor.Start()


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
    p.add_argument("--step", type=int, default=4, help="XY subsample step for mesh (VisIt characterStep)")
    p.add_argument("--zdim", type=int, default=96, help="Depth volume Z resolution")
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
    return p.parse_args()


def main():
    args = parse_args()
    image_path = os.path.abspath(args.image_path)
    if not os.path.isfile(image_path):
        print(f"Not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    depth_path = None
    if args.skip_sidecars:
        stem = os.path.splitext(os.path.basename(image_path))[0]
        folder = os.path.dirname(image_path)
        depth_path = os.path.join(folder, f"{stem}_depth.png")
        if not os.path.isfile(depth_path):
            print(f"Missing {depth_path}; drop --skip-sidecars", file=sys.stderr)
            sys.exit(1)
        print(f"Using existing sidecars under {folder}")
    else:
        depth_path, _, _ = generate_sidecars(
            image_path,
            depth_model=args.depth_model,
            mesh_levels=args.mesh_levels,
            mesh_median=args.mesh_median,
        )

    if args.sidecars_only:
        return

    print("Building character mesh...")
    vtk_path, poly = build_character_mesh(
        image_path,
        depth_path=depth_path,
        step=args.step,
        zdim=args.zdim,
        z_world_max=args.z_max,
        z_scale=args.z_scale,
    )

    if args.no_view:
        print(f"Done. Open with: python render.py {vtk_path} {image_path}")
        return

    print("Opening viewer...")
    render_mesh(poly, image_path, flip_v=args.flip_v)


if __name__ == "__main__":
    main()
