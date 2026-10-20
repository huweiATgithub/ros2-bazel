#include "libs/demo_protocol/protocol.h"
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/u_int64_multi_array.hpp>
#include <chrono>
#include <cstdint>
#include <iostream>
using namespace std::chrono_literals;
int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("observer");
  uint64_t count = 0, sum = 0;
  bool failed = false;
  auto subscription = node->create_subscription<std_msgs::msg::UInt64MultiArray>(
      demo_protocol::kSamplesTopic, rclcpp::QoS(100).reliable(),
      [&](const std_msgs::msg::UInt64MultiArray::SharedPtr msg) {
        // Independent C++ oracle, not another call into the Rust implementation.
        if (msg->data.size() != 2 || msg->data[0] != count ||
            msg->data[1] != count * count + 3 * count + 7) {
          failed = true; rclcpp::shutdown(); return;
        }
        sum += msg->data[1];
        if (++count == demo_protocol::kSampleCount) {
          std::cout << "RECEIVED 40 CHECKSUM " << sum << std::endl;
          rclcpp::shutdown();
        }
      });
  auto timeout = node->create_wall_timer(35s, [&] { failed = true; rclcpp::shutdown(); });
  std::cout << "OBSERVER_READY" << std::endl;
  rclcpp::spin(node);
  if (rclcpp::ok()) rclcpp::shutdown();
  return !failed && count == demo_protocol::kSampleCount && sum == 23160 ? 0 : 1;
}
