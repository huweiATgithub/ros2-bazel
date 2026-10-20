#ifndef ROS2_BAZEL_DEMO_LIBS_DEMO_PROTOCOL_PROTOCOL_H_
#define ROS2_BAZEL_DEMO_LIBS_DEMO_PROTOCOL_PROTOCOL_H_

#include <cstddef>
#include <cstdint>

// Wire-level names and workload sizes shared by the independent applications.
// Expected values and checksums deliberately stay in the verifiers, not here.
namespace demo_protocol {
constexpr char kSamplesTopic[] = "samples";
constexpr char kCalculateService[] = "calculate";
constexpr std::uint64_t kSampleCount = 40;
constexpr std::size_t kSubscriberCount = 3;
constexpr std::size_t kServiceCallCount = 12;
}  // namespace demo_protocol

#endif  // ROS2_BAZEL_DEMO_LIBS_DEMO_PROTOCOL_PROTOCOL_H_
