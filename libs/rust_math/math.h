#ifndef ROS2_BAZEL_DEMO_LIBS_RUST_MATH_MATH_H_
#define ROS2_BAZEL_DEMO_LIBS_RUST_MATH_MATH_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Implemented in math.rs and statically linked through the Bazel C++ interface.
uint64_t ros_demo_transform(uint64_t sequence);

#ifdef __cplusplus
}
#endif

#endif  // ROS2_BAZEL_DEMO_LIBS_RUST_MATH_MATH_H_
