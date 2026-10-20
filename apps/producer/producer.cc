#include "libs/demo_protocol/protocol.h"
#include "libs/rust_math/math.h"
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/u_int64_multi_array.hpp>
#include <std_srvs/srv/set_bool.hpp>
#include <chrono>
#include <cstdint>
#include <iostream>
using namespace std::chrono_literals;
int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("rust_backed_producer");
  auto publisher = node->create_publisher<std_msgs::msg::UInt64MultiArray>(
      demo_protocol::kSamplesTopic, rclcpp::QoS(100).reliable());
  size_t requests = 0;
  auto service = node->create_service<std_srvs::srv::SetBool>(demo_protocol::kCalculateService,
      [&requests](const std_srvs::srv::SetBool::Request::SharedPtr req,
                  std_srvs::srv::SetBool::Response::SharedPtr response) {
        const uint64_t input = req->data ? 19 : 4;
        response->success = true;
        response->message = std::to_string(ros_demo_transform(input));
        std::cout << "SERVICE " << ++requests << " " << response->message << std::endl;
      });
  uint64_t sequence = 0;
  auto timer = node->create_wall_timer(25ms, [&] {
    // No samples are sent until both independent subscribers are discovered.
    if (publisher->get_subscription_count() < demo_protocol::kSubscriberCount ||
        sequence == demo_protocol::kSampleCount) return;
    std_msgs::msg::UInt64MultiArray msg;
    msg.data = {sequence, ros_demo_transform(sequence)};
    publisher->publish(msg);
    if (++sequence == demo_protocol::kSampleCount) std::cout << "PUBLISHED 40" << std::endl;
  });
  std::cout << "PRODUCER_READY" << std::endl;
  rclcpp::spin(node);
  rclcpp::shutdown();
  return sequence == demo_protocol::kSampleCount &&
                 requests == demo_protocol::kServiceCallCount
             ? 0 : 1;
}
