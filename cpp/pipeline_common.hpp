#pragma once

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

#include <vtkImageData.h>
#include <vtkJPEGReader.h>
#include <vtkPNGReader.h>
#include <vtkSmartPointer.h>

namespace image {

inline bool StartsWith(const std::string& s, const char* prefix) {
    return s.rfind(prefix, 0) == 0;
}

inline std::string Stem(const std::string& path) {
    const auto slash = path.find_last_of("/\\");
    const auto dot = path.find_last_of('.');
    const std::size_t start = (slash == std::string::npos) ? 0 : slash + 1;
    const std::size_t end = (dot == std::string::npos || dot <= start) ? path.size() : dot;
    return path.substr(start, end - start);
}

inline std::string Dirname(const std::string& path) {
    const auto slash = path.find_last_of("/\\");
    return (slash == std::string::npos) ? std::string(".") : path.substr(0, slash);
}

inline char PathSep() {
#ifdef _WIN32
    return '\\';
#else
    return '/';
#endif
}

inline std::string JoinPath(const std::string& dir, const std::string& name) {
    if (dir.empty() || dir == ".") return name;
    const char last = dir.back();
    if (last == '/' || last == '\\') return dir + name;
    return dir + PathSep() + name;
}

inline std::string ExecutableDir(const char* argv0) {
    const std::string path = argv0 ? argv0 : "";
    return Dirname(path);
}

inline bool FileExists(const std::string& path) {
    std::ifstream in(path);
    return in.good();
}

// cpp/build[/Release] -> project root (VisItProject/)
inline std::string ProjectRootFromExecutable(const char* argv0) {
    std::string dir = ExecutableDir(argv0);
    for (int depth = 0; depth < 5; ++depth) {
        if (FileExists(JoinPath(dir, "image_pipeline.py"))) {
            return dir;
        }
        const std::string parent = Dirname(dir);
        if (parent == dir) {
            break;
        }
        dir = parent;
    }
    return ExecutableDir(argv0);
}

inline std::string ResolveSiblingBinary(const char* argv0, const std::string& name) {
    const char* env = std::getenv("MESH_BUILDER");
    if (env && name == "build_character_mesh") {
        return env;
    }
    env = std::getenv("RENDER_MESH");
    if (env && name == "render_mesh") {
        return env;
    }

    const std::string exe_dir = ExecutableDir(argv0);
#ifdef _WIN32
    const std::string candidate = JoinPath(exe_dir, name + ".exe");
#else
    const std::string candidate = JoinPath(exe_dir, name);
#endif
    if (FileExists(candidate)) {
        return candidate;
    }
    return candidate;
}

inline bool IsJpegPath(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    unsigned char h[3] = {};
    in.read(reinterpret_cast<char*>(h), 3);
    return in.gcount() == 3 && h[0] == 0xff && h[1] == 0xd8 && h[2] == 0xff;
}

inline bool IsPngPath(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    unsigned char h[8] = {};
    in.read(reinterpret_cast<char*>(h), 8);
    static const unsigned char kPngSig[8] = {0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a};
    return in.gcount() == 8 && std::equal(std::begin(h), std::end(h), std::begin(kPngSig));
}

inline vtkSmartPointer<vtkImageData> ReadImage2D(const std::string& path) {
    vtkSmartPointer<vtkImageData> img = vtkSmartPointer<vtkImageData>::New();
    if (IsJpegPath(path)) {
        vtkSmartPointer<vtkJPEGReader> reader = vtkSmartPointer<vtkJPEGReader>::New();
        reader->SetFileName(path.c_str());
        reader->Update();
        img->DeepCopy(reader->GetOutput());
    } else {
        vtkSmartPointer<vtkPNGReader> reader = vtkSmartPointer<vtkPNGReader>::New();
        reader->SetFileName(path.c_str());
        reader->Update();
        img->DeepCopy(reader->GetOutput());
    }
    return img;
}

inline float SampleSidecar(vtkImageData* img, int x, int y) {
    if (!img) return 0.f;
    int dims[3];
    img->GetDimensions(dims);
    x = std::clamp(x, 0, dims[0] - 1);
    y = std::clamp(y, 0, dims[1] - 1);
    return static_cast<float>(img->GetScalarComponentAsDouble(x, y, 0, 0) / 255.0);
}

inline std::string ShellQuote(const std::string& s) {
#ifdef _WIN32
    std::string out = "\"";
    for (char c : s) {
        if (c == '"') {
            out += "\\\"";
        } else {
            out += c;
        }
    }
    out += "\"";
    return out;
#else
    std::string out = "'";
    for (char c : s) {
        if (c == '\'') {
            out += "'\\''";
        } else {
            out += c;
        }
    }
    out += "'";
    return out;
#endif
}

}  // namespace image
