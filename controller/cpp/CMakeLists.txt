cmake_minimum_required(VERSION 3.16)
project(KIDAController CXX RC)

# KIDA Remote Controller — native Windows build (see src/main.cpp).
#   cmake -S . -B build -G "MinGW Makefiles" && cmake --build build
# or just run build.bat.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(KIDA-Controller WIN32 src/main.cpp src/app.rc)
target_compile_definitions(KIDA-Controller PRIVATE UNICODE _UNICODE)
target_link_libraries(KIDA-Controller PRIVATE winhttp windowscodecs ole32 xinput1_4 winmm msimg32 gdi32 user32 shell32)

if(MINGW)
  target_link_options(KIDA-Controller PRIVATE -municode -static -s)
endif()
