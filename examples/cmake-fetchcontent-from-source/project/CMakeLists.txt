cmake_minimum_required(VERSION 3.14.0 FATAL_ERROR)
    
project(dqcsim-cmake-example
    VERSION 0.0.1
    DESCRIPTION "Example for linking to DQCsim with CMake"
    LANGUAGES CXX
)

# You might want to read the simple example first, if you haven't already.

# First things first: DQCsim's C++ header requires C++11. So unless you're only
# using the C interface, you'll need to set this.
set(CMAKE_CXX_STANDARD 11)

# This is added to support running examples on forks in our GitHub actions workflow.
if (DEFINED ENV{REPO_OWNER})
  set(DQCSIM_REPO "$ENV{GITHUB_SERVER_URL}/$ENV{REPO_OWNER}/dqcsim.git")
else()
  set(DQCSIM_REPO "https://github.com/qe-lab/dqcsim.git")
endif()
if (DEFINED ENV{GITHUB_HEAD_REF})
  set(DQCSIM_TAG $ENV{GITHUB_HEAD_REF})
else()
  set(DQCSIM_TAG "master")
endif()

# You can use the FetchContent module (added in CMake 3.14!) with DQCsim like
# this:
include(FetchContent)
FetchContent_Declare(dqcsim
  GIT_REPOSITORY  ${DQCSIM_REPO}
  GIT_TAG         ${DQCSIM_TAG}
)
set(DQCSIM_FROM_SOURCE "yes")
FetchContent_MakeAvailable(dqcsim)

# This will do the following things:
#  - clone the DQCsim git repository in a temporary folder;
#  - run its CMakeLists.txt, which will;
#  - depending on DQCSIM_FROM_SOURCE (set with -DDQCSIM_FROM_SOURCE=... on
#    the CMake command line):
#     - if not specified: look for DQCsim in the system path;
#     - if DQCSIM_FROM_SOURCE=yes: build DQCsim from the downloaded sources;
#     - if DQCSIM_FROM_SOURCE=<srcdir>: build DQCsim from the given source
#       directory.
#  - provide an (imported) library named dqcsim for you to link against.

# If DQCsim is being built from source, -DDQCSIM_OPTIONS=... can be used to add
# options to DQCsim's CMake command line.

# Building DQCsim from source is only to be used for testing. Your plugin will
# be linked against the compiled version, but you still need a DQCsim
# installation if you want to use the DQCsim command line or other plugins
# (even the ones provided by default). What's unfortunately important is that
# your plugin is run from the directory it was built into, otherwise the
# relative path to DQCsim's shared object file will be wrong. In general, your
# mileage may vary when building from source.

# Now we can define an executable. In this example, this is really simple...
# but this can be as intricate as you need it to be for your project.
add_executable(main main.cpp)

# You do have to remember to link against DQCsim though, in the usual way.
target_link_libraries(main dqcsim)
