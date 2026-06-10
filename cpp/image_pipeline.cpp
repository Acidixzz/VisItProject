// End-to-end image mesh pipeline (C++ orchestrator):
//   1. Generate *_depth.png via Python (Depth-Anything still needs torch)
//   2. Build character mesh (C++)
//   3. Preview in VTK (C++)
//
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

#include "pipeline_common.hpp"

namespace {

struct Options {
    std::string image_path;
    bool skip_sidecars = false;
    std::string depth_model = "small";
    int mesh_levels = 64;
    int mesh_median = 3;
    int step = 12;
    int zdim = 48;
    double z_max = 400.0;
    double z_scale = 1.0;
    bool no_view = false;
    bool flip_v = false;
    bool lineart = false;
    bool lineart_texture = false;
};

void PrintUsage(const char* prog) {
    std::cerr
        << "Usage: " << prog << " <image.jpg|png> [options]\n"
        << "  --skip-sidecars      Use existing *_depth.png\n"
        << "  --depth-model M      small|base (default: small)\n"
        << "  --mesh-levels N      Depth quantization steps (default: 64)\n"
        << "  --mesh-median N      Median filter on depth, 0=off (default: 3)\n"
        << "  --step N             XY subsample step (default: 12, higher=fewer polys)\n"
        << "  --zdim N             Z volume resolution (default: 48)\n"
        << "  --z-max F            World Z extent (default: 400)\n"
        << "  --z-scale F          Z relief multiplier (default: 1)\n"
        << "  --no-view            Build sidecars + VTK only\n"
        << "  --flip-v             Flip texture V in the viewer\n"
        << "  --lineart            Build line-art; depth from line-art (Depth-Anything)\n"
        << "  --lineart-texture    Use line-art as mesh texture too (implies --lineart)\n"
        << "  --lowpoly            Coarse mesh preset (--step 24 --zdim 24 --mesh-levels 16)\n";
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

        if (arg == "--skip-sidecars") {
            opt->skip_sidecars = true;
        } else if (arg == "--depth-model") {
            const char* v = need("--depth-model");
            if (!v) return false;
            opt->depth_model = v;
        } else if (arg == "--mesh-levels") {
            const char* v = need("--mesh-levels");
            if (!v) return false;
            opt->mesh_levels = std::stoi(v);
        } else if (arg == "--mesh-median") {
            const char* v = need("--mesh-median");
            if (!v) return false;
            opt->mesh_median = std::stoi(v);
        } else if (arg == "--step") {
            const char* v = need("--step");
            if (!v) return false;
            opt->step = std::stoi(v);
        } else if (arg == "--zdim") {
            const char* v = need("--zdim");
            if (!v) return false;
            opt->zdim = std::stoi(v);
        } else if (arg == "--z-max") {
            const char* v = need("--z-max");
            if (!v) return false;
            opt->z_max = std::stod(v);
        } else if (arg == "--z-scale") {
            const char* v = need("--z-scale");
            if (!v) return false;
            opt->z_scale = std::stod(v);
        } else if (arg == "--no-view") {
            opt->no_view = true;
        } else if (arg == "--flip-v") {
            opt->flip_v = true;
        } else if (arg == "--lineart") {
            opt->lineart = true;
        } else if (arg == "--lineart-texture") {
            opt->lineart = true;
            opt->lineart_texture = true;
        } else if (arg == "--lowpoly") {
            opt->step = 24;
            opt->zdim = 24;
            opt->mesh_levels = 16;
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
    const std::string py_script = image::JoinPath(project_root, "image_pipeline.py");

    if (!image::FileExists(py_script)) {
        std::cerr << "Missing " << py_script << "\n";
        return 1;
    }

    {
        std::string cmd = FindPython() + " " + image::ShellQuote(py_script) + " "
                          + image::ShellQuote(opt.image_path) + " --sidecars-only --depth-model "
                          + image::ShellQuote(opt.depth_model) + " --mesh-levels "
                          + std::to_string(opt.mesh_levels) + " --mesh-median "
                          + std::to_string(opt.mesh_median);
        if (opt.skip_sidecars) {
            cmd += " --skip-sidecars";
        }
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
                           + " --zdim " + std::to_string(opt.zdim) + " --z-max "
                           + std::to_string(opt.z_max) + " --z-scale "
                           + std::to_string(opt.z_scale);

    std::cout << "Building character mesh...\n";
    if (RunCommand(mesh_cmd) != 0) {
        return 1;
    }

    if (opt.no_view) {
        return 0;
    }

    std::string view_cmd = image::ShellQuote(renderer) + " " + image::ShellQuote(vtk_path) + " "
                           + image::ShellQuote(texture_path);
    if (opt.flip_v) {
        view_cmd += " --flip-v";
    }

    std::cout << "Opening viewer...\n";
    if (RunCommand(view_cmd) != 0) {
        return 1;
    }
    return 0;
}

