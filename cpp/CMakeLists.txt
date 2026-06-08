cmake_minimum_required(VERSION 3.16)
project(manga_pipeline LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(VTK REQUIRED)
find_package(OpenMP)

function(add_manga_target target source)
    add_executable(${target} ${source})
    target_link_libraries(${target} PRIVATE ${VTK_LIBRARIES})
    if(OpenMP_CXX_FOUND)
        target_link_libraries(${target} PRIVATE OpenMP::OpenMP_CXX)
    endif()
    vtk_module_autoinit(
        TARGETS ${target}
        MODULES ${VTK_LIBRARIES}
    )
endfunction()

add_manga_target(build_character_mesh build_character_mesh.cpp)
add_manga_target(render_mesh render_mesh.cpp)
add_manga_target(manga_pipeline manga_pipeline.cpp)

if(OpenMP_CXX_FOUND)
    message(STATUS "OpenMP enabled")
endif()
