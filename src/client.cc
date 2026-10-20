#include <rclcpp/rclcpp.hpp>
#include <std_srvs/srv/set_bool.hpp>
#include <chrono>
#include <iostream>
using namespace std::chrono_literals;
int main(int argc, char** argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("service_verifier");
  auto absent = node->create_client<std_srvs::srv::SetBool>("deliberately_absent");
  if (absent->wait_for_service(300ms)) return 1;
  std::cout << "ABSENT_SERVICE_TIMEOUT_OK" << std::endl;
  auto client = node->create_client<std_srvs::srv::SetBool>("calculate");
  if (!client->wait_for_service(25s)) return 2;
  for (int i = 0; i < 12; ++i) {
    auto request = std::make_shared<std_srvs::srv::SetBool::Request>();
    request->data = i % 2 != 0;
    auto future = client->async_send_request(request);
    if (rclcpp::spin_until_future_complete(node, future, 3s) !=
        rclcpp::FutureReturnCode::SUCCESS) return 3;
    auto response = future.get();
    if (!response->success || response->message != (request->data ? "425" : "35")) return 4;
  }
  std::cout << "SERVICE_PASS 12" << std::endl;
  rclcpp::shutdown();
  return 0;
}
