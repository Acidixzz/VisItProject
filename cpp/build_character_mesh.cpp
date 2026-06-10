// Build a textured character mesh from a source image + *_depth.png sidecar.
// Direct port of VisIt avtImageFileFormat::GetCharacterMesh (with OpenMP on hot loops).

#include <algorithm>
#include <cstring>
#include <iostream>
#include <string>

#include <vtkFloatArray.h>
#include <vtkImageData.h>
#include <vtkPointData.h>
#include <vtkMarchingCubes.h>
#include <vtkPNGReader.h>
#include <vtkPolyData.h>
#include <vtkPolyDataWriter.h>
#include <vtkSmartPointer.h>

#include "pipeline_common.hpp"

#ifdef _OPENMP
#include <omp.h>
#endif

namespace {

struct Options {
    std::string image_path;
    std::string depth_path;
    std::string output_path;
    int step = 12;
    int zdim = 48;
    double z_world_max = 400.0;
    double z_scale = 1.0;
};

void PrintUsage(const char* prog) {
    std::cerr
        << "Usage: " << prog
        << " <image.jpg|png> [options]\n"
        << "  --depth PATH     Depth sidecar (default: <stem>_depth.png)\n"
        << "  --output PATH    Output .vtk path (default: <stem>.vtk)\n"
        << "  --step N         XY subsample step (default: 12, higher=fewer polys)\n"
        << "  --zdim N         Z volume resolution (default: 48)\n"
        << "  --z-max F        World Z extent (default: 400)\n"
        << "  --z-scale F      Z relief multiplier (default: 1)\n";
}

bool ParseArgs(int argc, char* argv[], Options* opt) {
    if (argc < 2 || image::StartsWith(argv[1], "--")) {
        PrintUsage(argv[0]);
        return false;
    }
    opt->image_path = argv[1];

    for (int i = 2; i < argc; ++i) {
        std::string arg = argv[i];
        auto need = [&](const char* flag) -> const char* {
            if (i + 1 >= argc) {
                std::cerr << "Missing value for " << flag << "\n";
                return nullptr;
            }
            return argv[++i];
        };

        if (arg == "--depth") {
            const char* v = need("--depth");
            if (!v) return false;
            opt->depth_path = v;
        } else if (arg == "--output") {
            const char* v = need("--output");
            if (!v) return false;
            opt->output_path = v;
        } else if (arg == "--step") {
            const char* v = need("--step");
            if (!v) return false;
            opt->step = std::max(1, std::stoi(v));
        } else if (arg == "--zdim") {
            const char* v = need("--zdim");
            if (!v) return false;
            opt->zdim = std::max(2, std::stoi(v));
        } else if (arg == "--z-max") {
            const char* v = need("--z-max");
            if (!v) return false;
            opt->z_world_max = std::stod(v);
        } else if (arg == "--z-scale") {
            const char* v = need("--z-scale");
            if (!v) return false;
            opt->z_scale = std::stod(v);
        } else if (arg == "--help" || arg == "-h") {
            PrintUsage(argv[0]);
            return false;
        } else {
            std::cerr << "Unknown argument: " << arg << "\n";
            PrintUsage(argv[0]);
            return false;
        }
    }
    return true;
}

}  // namespace

int main(int argc, char* argv[]) {
    Options opt;
    if (!ParseArgs(argc, argv, &opt)) {
        return 1;
    }

    vtkSmartPointer<vtkImageData> img = image::ReadImage2D(opt.image_path);
    if (!img) {
        std::cerr << "Failed to read image: " << opt.image_path << "\n";
        return 1;
    }

    int imageDims[3];
    img->GetDimensions(imageDims);

    if (opt.depth_path.empty()) {
        opt.depth_path = image::JoinPath(image::Dirname(opt.image_path),
                                         image::Stem(opt.image_path) + "_depth.png");
    }
    if (opt.output_path.empty()) {
        opt.output_path = image::JoinPath(image::Dirname(opt.image_path),
                                          image::Stem(opt.image_path) + ".vtk");
    }

    vtkSmartPointer<vtkPNGReader> depthReader = vtkSmartPointer<vtkPNGReader>::New();
    depthReader->SetFileName(opt.depth_path.c_str());
    depthReader->Update();
    vtkSmartPointer<vtkImageData> depthImg = vtkSmartPointer<vtkImageData>::New();
    depthImg->DeepCopy(depthReader->GetOutput());

    int depthDims[3];
    depthImg->GetDimensions(depthDims);
    // Depth sidecar is generated with correct display orientation; trust its layout.
    const int fullX = depthDims[0];
    const int fullY = depthDims[1];
    const int step = opt.step;

    if (imageDims[0] != fullX || imageDims[1] != fullY) {
        std::cerr << "Photo is " << imageDims[0] << "x" << imageDims[1]
                  << " but depth is " << fullX << "x" << fullY
                  << "; using depth layout (likely EXIF rotation — use *_oriented.jpg).\n";
    }

    const int xdim = (fullX + step - 1) / step;
    const int ydim = (fullY + step - 1) / step;

    const int zdim = opt.zdim;
    const float zWorldMax = static_cast<float>(opt.z_world_max * opt.z_scale);
    const float zSpacing = zWorldMax / static_cast<float>(zdim - 1);
    const int pad = 1;
    const int volX = xdim + 2 * pad;
    const int volY = ydim + 2 * pad;
    const int volZ = zdim + 2;

    vtkSmartPointer<vtkImageData> volume = vtkSmartPointer<vtkImageData>::New();
    volume->SetDimensions(volX, volY, volZ);
    volume->SetSpacing(static_cast<double>(step), static_cast<double>(step), static_cast<double>(zSpacing));
    volume->SetOrigin(static_cast<double>(-pad * step),
                      static_cast<double>(-pad * step),
                      static_cast<double>(-zSpacing));
    volume->AllocateScalars(VTK_UNSIGNED_CHAR, 1);

    unsigned char* voxels = static_cast<unsigned char*>(volume->GetScalarPointer(0, 0, 0));
    std::memset(voxels, 0, static_cast<std::size_t>(volX) * volY * volZ);

    std::cerr << "Mesh grid " << xdim << "x" << ydim << " (step=" << step
              << ", ~" << (xdim * ydim) << " columns)...\n";

#ifdef _OPENMP
#pragma omp parallel for collapse(2) schedule(static)
#endif
    for (int y = 0; y < ydim; ++y) {
        for (int x = 0; x < xdim; ++x) {
            int srcX = x * step;
            int srcY = y * step;
            if (srcX >= fullX) srcX = fullX - 1;
            if (srcY >= fullY) srcY = fullY - 1;

            int sidecarX = srcX;
            int sidecarY = srcY;
            // PNG sidecars from depth_image_generator.py match image (W,H); use direct sampling.
            // VisIt only transposes when VTK depth dims are swapped vs the source image.

            const float depthValue = image::SampleSidecar(depthImg, sidecarX, sidecarY);
            int height = 1 + static_cast<int>(depthValue * static_cast<float>(zdim - 1));
            height = std::clamp(height, 1, zdim - 1);

            const int vx = x + pad;
            const int vy = y + pad;
            for (int z = 1; z <= height; ++z) {
                unsigned char* ptr = static_cast<unsigned char*>(volume->GetScalarPointer(vx, vy, z));
                *ptr = 255;
            }
        }
    }

    std::cerr << "Marching cubes...\n";

    vtkSmartPointer<vtkMarchingCubes> mc = vtkSmartPointer<vtkMarchingCubes>::New();
    mc->SetInputData(volume);
    mc->SetValue(0, 127.5);
    mc->ComputeNormalsOff();
    mc->ComputeGradientsOff();
    mc->Update();

    vtkSmartPointer<vtkPolyData> poly = vtkSmartPointer<vtkPolyData>::New();
    poly->DeepCopy(mc->GetOutput());

    const vtkIdType nPoints = poly->GetNumberOfPoints();
    vtkSmartPointer<vtkFloatArray> tcoords = vtkSmartPointer<vtkFloatArray>::New();
    tcoords->SetName("TextureCoordinates");
    tcoords->SetNumberOfComponents(2);
    tcoords->SetNumberOfTuples(nPoints);

    const double denomX = std::max(fullX - 1, 1);
    const double denomY = std::max(fullY - 1, 1);

    std::cerr << "Texture coordinates (" << nPoints << " points)...\n";

#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (vtkIdType i = 0; i < nPoints; ++i) {
        double p[3];
        poly->GetPoint(i, p);
        const float u = static_cast<float>(std::clamp(p[0] / denomX, 0.0, 1.0));
        const float v = static_cast<float>(std::clamp(p[1] / denomY, 0.0, 1.0));
        tcoords->SetTuple2(i, u, v);
    }

    // Drop marching-cubes scalars/normals — they corrupt legacy ASCII POINT_DATA
    // and cause vtkPolyDataReader to mis-parse texture coordinates as "nan".
    poly->GetPointData()->Initialize();
    poly->GetPointData()->SetTCoords(tcoords);

    vtkSmartPointer<vtkPolyDataWriter> writer = vtkSmartPointer<vtkPolyDataWriter>::New();
    writer->SetFileName(opt.output_path.c_str());
    writer->SetInputData(poly);
    writer->SetFileTypeToBinary();
    writer->Write();

    std::cout << "Mesh: " << poly->GetNumberOfPoints() << " points, "
              << poly->GetNumberOfPolys() << " polys\n";
    std::cout << "Wrote " << opt.output_path << "\n";
    return 0;
}
