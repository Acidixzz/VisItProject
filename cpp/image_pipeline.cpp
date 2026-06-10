// End-to-end image mesh pipeline (C++ orchestrator):
//   1. Generate *_depth.png via Python (Depth-Anything Base)
//   2. Build character mesh (C++)
//   3. Preview in VTK (C++)
//
#include <cstdlib>
#include <iostream>
#include <string>

#include "pipeline_common.hpp"

namespace {

constexpr int kMeshZdim = 48;
constexpr double kMeshZMax = 400.0;
constexpr double kMeshZScale = 1.0;
constexpr int kDefaultStep = 12;

struct Options {
    std::string image_path;
    int step = kDefaultStep;
    bool no_view = false;
    bool lineart = false;
    bool lineart_texture = false;
};

void PrintUsage(const char* prog) {
    std::cerr
        << "Usage: " << prog << " <image.jpg|png> [options]\n"
        << "  --step N             XY subsample step (default: " << kDefaultStep
        << ", higher=fewer polys)\n"
        << "  --no-view            Build mesh only, skip viewer\n"
        << "  --lineart            Depth from cleaned line-art (sketches)\n"
        << "  --lineart-texture    Use line-art as viewer texture (implies --lineart)\n";
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

        if (arg == "--step") {
            const char* v = need("--step");
            if (!v) return false;
            opt->step = std::max(1, std::stoi(v));
        } else if (arg == "--no-view") {
            opt->no_view = true;
        } else if (arg == "--lineart") {
            opt->lineart = true;
        } else if (arg == "--lineart-texture") {
            opt->lineart = true;
            opt->lineart_texture = true;
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

int RunCommand(const std::string& cmd) {
    std::cout << "Running: " << cmd << "\n";
    return std::system(cmd.c_str());
}

std::string FindPython() {
    const char* env = std::getenv("IMAGE_PYTHON");
    if (env && env[0] != '\0') {
        return env;
    }
#ifdef _WIN32
    return "python";
#else
    return "python3";
#endif
}

}  // namespace

int main(int argc, char* argv[]) {
    Options opt;
    if (!ParseArgs(argc, argv, &opt)) {
        return 1;
    }

    if (!image::FileExists(opt.image_path)) {
        std::cerr << "Not found: " << opt.image_path << "\n";
        return 1;
    }

    const std::string project_root = image::ProjectRootFromExecutable(argv[0]);
    const std::string stem = image::Stem(opt.image_path);
    const std::string folder = image::Dirname(opt.image_path);
    const std::string depth_path = image::JoinPath(folder, stem + "_depth.png");
    const std::string vtk_path = image::JoinPath(folder, stem + ".vtk");
    const std::string lineart_path = image::JoinPath(folder, stem + "_lineart.jpg");
    const std::string oriented_path = image::JoinPath(folder, stem + "_oriented.jpg");
    std::string mesh_image = opt.image_path;
    if (image::FileExists(oriented_path)) {
        mesh_image = oriented_path;
    }
    std::string texture_path = mesh_image;
    if (opt.lineart_texture) {
        texture_path = lineart_path;
    }

    const std::string mesh_builder = image::ResolveSiblingBinary(argv[0], "build_character_mesh");
    const std::string renderer = image::ResolveSiblingBinary(argv[0], "render_mesh");
    const std::string py_script = image::JoinPath(project_root, "depth_image_generator.py");

    if (!image::FileExists(py_script)) {
        std::cerr << "Missing " << py_script << "\n";
        return 1;
    }

    {
        std::string cmd = FindPython() + " " + image::ShellQuote(py_script) + " "
                          + image::ShellQuote(opt.image_path);
        if (opt.lineart) {
            cmd += " --lineart";
        }
        if (opt.lineart_texture) {
            cmd += " --lineart-texture";
        }
        if (RunCommand(cmd) != 0) {
            return 1;
        }
    }

    if (image::FileExists(oriented_path)) {
        mesh_image = oriented_path;
        if (!opt.lineart_texture) {
            texture_path = oriented_path;
        }
    }

    std::string mesh_cmd = image::ShellQuote(mesh_builder) + " "
                           + image::ShellQuote(mesh_image) + " --depth "
                           + image::ShellQuote(depth_path) + " --output "
                           + image::ShellQuote(vtk_path) + " --step " + std::to_string(opt.step)
                           + " --zdim " + std::to_string(kMeshZdim) + " --z-max "
                           + std::to_string(kMeshZMax) + " --z-scale "
                           + std::to_string(kMeshZScale);

    std::cout << "Building character mesh...\n";
    if (RunCommand(mesh_cmd) != 0) {
        return 1;
    }

    if (opt.no_view) {
        return 0;
    }

    std::string view_cmd = image::ShellQuote(renderer) + " " + image::ShellQuote(vtk_path) + " "
                           + image::ShellQuote(texture_path);

    std::cout << "Opening viewer...\n";
    if (RunCommand(view_cmd) != 0) {
        return 1;
    }
    return 0;
}
