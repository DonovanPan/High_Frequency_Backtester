cmake_minimum_required(VERSION 3.10)
project(HighFreqBacktester)

set(CMAKE_BUILD_TYPE Release)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(MSVC)
    add_compile_options(/utf-8)
endif()

add_executable(Backtester
    cppmodules/main.cpp
    cppmodules/HighFreqBacktester.cpp
    cppmodules/Reporter.cpp
)