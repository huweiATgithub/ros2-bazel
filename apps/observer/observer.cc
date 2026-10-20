#include "libs/demo_protocol/protocol.h"
#include <rclcpp/rclcpp.hpp>
#include <demo_interfaces/msg/sample.hpp>
#include <vector>
#include <chrono>
#include <cstdint>
#include <iostream>
using namespace std::chrono_literals;
int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("observer");
  uint64_t count = 0, sum = 0;
  bool failed = false;
  auto subscription = node->create_subscription<demo_interfaces::msg::Sample>(
      demo_protocol::kSamplesTopic, rclcpp::QoS(100).reliable(),
      [&](const demo_interfaces::msg::Sample::SharedPtr msg) {
        // Independent C++ oracle, not another call into the Rust implementation.
        std::vector<uint64_t> history;
        for (uint64_t n = count > 2 ? count - 2 : 0; n <= count; ++n) {
          history.push_back(n * n + 3 * n + 7);
        }
        if (msg->sequence != count || msg->stamp.sec != 1700000000 ||
            msg->stamp.nanosec != count * 25000000 ||
            msg->source != "rust_transform" || msg->calculation.input != count ||
            msg->calculation.output != count * count + 3 * count + 7 ||
            msg->recent_outputs != history) {
          failed = true; rclcpp::shutdown(); return;
        }
        sum += msg->calculation.output;
        if (++count == demo_protocol::kSampleCount) {
          std::cout << "RECEIVED 40 CHECKSUM " << sum << " CUSTOM_FIELDS_OK" << std::endl;
          rclcpp::shutdown();
        }
      });
  auto timeout = node->create_wall_timer(35s, [&] { failed = true; rclcpp::shutdown(); });
  std::cout << "OBSERVER_READY" << std::endl;
  rclcpp::spin(node);
  if (rclcpp::ok()) rclcpp::shutdown();
  return !failed && count == demo_protocol::kSampleCount && sum == 23160 ? 0 : 1;
}
