// Textured VTK preview of a character mesh (.vtk + source image).

#include <algorithm>
#include <cmath>
#include <iostream>
#include <string>

#include <vtkActor.h>
#include <vtkCamera.h>
#include <vtkDataArray.h>
#include <vtkDecimatePro.h>
#include <vtkFloatArray.h>
#include <vtkPointData.h>
#include <vtkQuadricClustering.h>
#include <vtkInteractorStyleTrackballCamera.h>
#include <vtkPolyData.h>
#include <vtkPolyDataMapper.h>
#include <vtkPolyDataReader.h>
#include <vtkProperty.h>
#include <vtkRenderWindow.h>
#include <vtkRenderWindowInteractor.h>
#include <vtkRenderer.h>
#include <vtkSmartPointer.h>
#include <vtkTexture.h>

#include "pipeline_common.hpp"

namespace {

struct Options {
    std::string mesh_path;
    std::string texture_path;
    bool flip_v = false;
    bool no_decimate = false;
    double decimate = 0.98;
    int window_w = 1200;
    int window_h = 900;
};

void PrintUsage(const char* prog) {
    std::cerr
        << "Usage: " << prog << " <mesh.vtk> <texture.jpg|png> [options]\n"
        << "  --decimate F       Fraction of polys to remove (default: 0.98, keeps ~2%)\n"
        << "  --no-decimate      Show full mesh (slow on large meshes)\n"
        << "  --flip-v           Flip texture V coordinate\n"
        << "  --window W H       Window size (default: 1200 900)\n";
}

bool ParseArgs(int argc, char* argv[], Options* opt) {
    if (argc < 3) {
        PrintUsage(argv[0]);
        return false;
    }
    opt->mesh_path = argv[1];
    opt->texture_path = argv[2];

    for (int i = 3; i < argc; ++i) {
        std::string arg = argv[i];
        auto need = [&](const char* flag) -> const char* {
            if (i + 1 >= argc) {
                std::cerr << "Missing value for " << flag << "\n";
                return nullptr;
            }
            return argv[++i];
        };

        if (arg == "--flip-v") {
            opt->flip_v = true;
        } else if (arg == "--no-decimate") {
            opt->no_decimate = true;
        } else if (arg == "--decimate") {
            const char* v = need("--decimate");
            if (!v) return false;
            opt->decimate = std::stod(v);
        } else if (arg == "--window") {
            if (i + 2 >= argc) {
                std::cerr << "Missing values for --window\n";
                return false;
            }
            opt->window_w = std::max(1, std::stoi(argv[++i]));
            opt->window_h = std::max(1, std::stoi(argv[++i]));
        } else if (arg == "--help" || arg == "-h") {
            PrintUsage(argv[0]);
            return false;
        } else {
            std::cerr << "Unknown argument: " << arg << "\n";
            PrintUsage(argv[0]);
            return false;
        }
    }

    opt->decimate = std::clamp(opt->decimate, 0.0, 0.999);
    return true;
}

void EnsureTextureCoordinates(vtkPolyData* poly) {
    if (poly->GetPointData()->GetTCoords() != nullptr) {
        return;
    }

    double bounds[6];
    poly->GetBounds(bounds);
    const double xmin = bounds[0];
    const double xmax = bounds[1];
    const double ymin = bounds[2];
    const double ymax = bounds[3];

    vtkSmartPointer<vtkFloatArray> tcoords = vtkSmartPointer<vtkFloatArray>::New();
    tcoords->SetName("TextureCoordinates");
    tcoords->SetNumberOfComponents(2);
    tcoords->SetNumberOfTuples(poly->GetNumberOfPoints());

    for (vtkIdType i = 0; i < poly->GetNumberOfPoints(); ++i) {
        double p[3];
        poly->GetPoint(i, p);
        const double u = (xmax != xmin) ? (p[0] - xmin) / (xmax - xmin) : 0.0;
        const double v = (ymax != ymin) ? (p[1] - ymin) / (ymax - ymin) : 0.0;
        tcoords->SetTuple2(i,
                           static_cast<float>(std::clamp(u, 0.0, 1.0)),
                           static_cast<float>(std::clamp(v, 0.0, 1.0)));
    }
    poly->GetPointData()->SetTCoords(tcoords);
}

vtkSmartPointer<vtkPolyData> SimplifyForPreview(vtkPolyData* input, double reduction) {
    const vtkIdType polys = input->GetNumberOfPolys();
    const vtkIdType target =
        std::max<vtkIdType>(50000, static_cast<vtkIdType>(polys * (1.0 - reduction)));

    vtkSmartPointer<vtkPolyData> output = vtkSmartPointer<vtkPolyData>::New();

    // DecimatePro on multi-million poly meshes can take hours; cluster instead.
    if (polys > 2000000) {
        std::cout << "Using fast quadric clustering for " << polys << " polys...\n";
        const int div_xy = static_cast<int>(std::clamp(std::sqrt(static_cast<double>(target)), 96.0, 384.0));
        const int div_z = std::max(8, div_xy / 8);

        vtkSmartPointer<vtkQuadricClustering> cluster = vtkSmartPointer<vtkQuadricClustering>::New();
        cluster->SetInputData(input);
        cluster->SetNumberOfDivisions(div_xy, div_xy, div_z);
        cluster->Update();
        output->DeepCopy(cluster->GetOutput());
        return output;
    }

    std::cout << "Decimating with DecimatePro...\n";
    vtkSmartPointer<vtkDecimatePro> decimate = vtkSmartPointer<vtkDecimatePro>::New();
    decimate->SetInputData(input);
    decimate->SetTargetReduction(reduction);
    decimate->PreserveTopologyOn();
    decimate->SplittingOff();
    decimate->Update();
    output->DeepCopy(decimate->GetOutput());
    return output;
}

}  // namespace

int main(int argc, char* argv[]) {
    Options opt;
    if (!ParseArgs(argc, argv, &opt)) {
        return 1;
    }

    vtkSmartPointer<vtkPolyDataReader> reader = vtkSmartPointer<vtkPolyDataReader>::New();
    reader->SetFileName(opt.mesh_path.c_str());
    reader->Update();

    vtkSmartPointer<vtkPolyData> poly = vtkSmartPointer<vtkPolyData>::New();
    poly->DeepCopy(reader->GetOutput());

    // Ignore stale scalars/normals from old ASCII exports.
    vtkDataArray* savedTcoords = poly->GetPointData()->GetTCoords();
    if (savedTcoords) {
        savedTcoords->Register(nullptr);
    }
    poly->GetPointData()->Initialize();
    if (savedTcoords) {
        poly->GetPointData()->SetTCoords(savedTcoords);
        savedTcoords->UnRegister(nullptr);
    }

    const vtkIdType orig_polys = poly->GetNumberOfPolys();
    std::cout << "Loaded: " << poly->GetNumberOfPoints() << " points, " << orig_polys << " polys\n";

    if (!opt.no_decimate && orig_polys > 50000) {
        std::cout << "Simplifying for preview (target ~" << ((1.0 - opt.decimate) * 100.0)
                  << "% of polys)...\n";
        poly = SimplifyForPreview(poly, opt.decimate);
        std::cout << "Preview mesh: " << poly->GetNumberOfPoints() << " points, "
                  << poly->GetNumberOfPolys() << " polys\n";
    }

    EnsureTextureCoordinates(poly);

    if (opt.flip_v) {
        vtkDataArray* tcoords = poly->GetPointData()->GetTCoords();
        for (vtkIdType i = 0; i < tcoords->GetNumberOfTuples(); ++i) {
            double uv[2];
            tcoords->GetTuple(i, uv);
            tcoords->SetTuple2(i, uv[0], 1.0 - uv[1]);
        }
    }

    vtkSmartPointer<vtkPolyDataMapper> mapper = vtkSmartPointer<vtkPolyDataMapper>::New();
    mapper->SetInputData(poly);
    mapper->ScalarVisibilityOff();

    vtkSmartPointer<vtkActor> actor = vtkSmartPointer<vtkActor>::New();
    actor->SetMapper(mapper);
    actor->GetProperty()->BackfaceCullingOff();
    actor->GetProperty()->LightingOff();

    vtkSmartPointer<vtkImageData> texture_img = image::ReadImage2D(opt.texture_path);
    if (!texture_img) {
        std::cerr << "Failed to read texture: " << opt.texture_path << "\n";
        return 1;
    }

    vtkSmartPointer<vtkTexture> texture = vtkSmartPointer<vtkTexture>::New();
    texture->SetInputData(texture_img);
    texture->InterpolateOn();
    actor->SetTexture(texture);

    vtkSmartPointer<vtkRenderer> renderer = vtkSmartPointer<vtkRenderer>::New();
    renderer->AddActor(actor);
    renderer->SetBackground(0.08, 0.08, 0.08);

    vtkSmartPointer<vtkRenderWindow> window = vtkSmartPointer<vtkRenderWindow>::New();
    window->AddRenderer(renderer);
    window->SetSize(opt.window_w, opt.window_h);
    window->SetMultiSamples(0);

    vtkSmartPointer<vtkRenderWindowInteractor> interactor =
        vtkSmartPointer<vtkRenderWindowInteractor>::New();
    interactor->SetRenderWindow(window);

    vtkSmartPointer<vtkInteractorStyleTrackballCamera> style =
        vtkSmartPointer<vtkInteractorStyleTrackballCamera>::New();
    interactor->SetInteractorStyle(style);

    renderer->ResetCamera();
    vtkCamera* camera = renderer->GetActiveCamera();
    camera->Azimuth(45);
    camera->Elevation(35);
    camera->Zoom(1.2);

    window->Render();
    interactor->Start();
    return 0;
}
