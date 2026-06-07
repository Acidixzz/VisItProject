# render.py — thin wrapper; use manga_pipeline.py for the full flow.

import sys

import vtk

from manga_pipeline import load_texture, render_mesh


def main():
    if len(sys.argv) < 3:
        print("Usage: python render.py <mesh.vtk> <texture_image>")
        sys.exit(1)

    reader = vtk.vtkPolyDataReader()
    reader.SetFileName(sys.argv[1])
    reader.Update()
    poly = reader.GetOutput()

    print("Points:", poly.GetNumberOfPoints())
    print("Polys:", poly.GetNumberOfPolys())

    if poly.GetPointData().GetTCoords() is None:
        bounds = poly.GetBounds()
        xmin, xmax, ymin, ymax, _, _ = bounds
        tcoords = vtk.vtkFloatArray()
        tcoords.SetName("TextureCoordinates")
        tcoords.SetNumberOfComponents(2)
        tcoords.SetNumberOfTuples(poly.GetNumberOfPoints())
        for i in range(poly.GetNumberOfPoints()):
            x, y, _ = poly.GetPoint(i)
            u = (x - xmin) / (xmax - xmin) if xmax != xmin else 0.0
            v = (y - ymin) / (ymax - ymin) if ymax != ymin else 0.0
            tcoords.SetTuple2(i, max(0, min(1, u)), max(0, min(1, v)))
        poly.GetPointData().SetTCoords(tcoords)

    render_mesh(poly, sys.argv[2])


if __name__ == "__main__":
    main()
