"""Independent Python consumer of the C++ publisher's generated ROS messages."""
import sys
import time

import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy
from demo_interfaces.msg import Sample


def main():
    rclpy.init()
    node = rclpy.create_node("python_observer")
    count = 0
    checksum = 0
    failed = False

    def receive(message):
        nonlocal count, checksum, failed
        # This oracle never calls Rust or shares the C++ verifier's code.
        expected = count * count + 3 * count + 7
        history = [n * n + 3 * n + 7 for n in range(max(0, count - 2), count + 1)]
        valid = (
            message.sequence == count
            and message.stamp.sec == 1_700_000_000
            and message.stamp.nanosec == count * 25_000_000
            and message.source == "rust_transform"
            and message.calculation.input == count
            and message.calculation.output == expected
            and list(message.recent_outputs) == history
        )
        if not valid:
            print(f"PYTHON_SAMPLE_MISMATCH sequence={count}: {message}", flush=True)
            failed = True
            return
        checksum += message.calculation.output
        count += 1

    subscription = node.create_subscription(
        Sample, "samples", receive,
        QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE),
    )
    print("PYTHON_OBSERVER_READY", flush=True)
    deadline = time.monotonic() + 35
    while rclpy.ok() and not failed and count < 40 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    success = not failed and count == 40 and checksum == 23160
    if success:
        print("PYTHON_RECEIVED 40 CHECKSUM 23160 CUSTOM_FIELDS_OK", flush=True)
    else:
        print(f"PYTHON_FAILED count={count} checksum={checksum}", flush=True)
    node.destroy_subscription(subscription)
    node.destroy_node()
    rclpy.shutdown()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
