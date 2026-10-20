"""Real DDS, two independent receivers and repeated Rust-backed service calls."""
import os
import unittest
import launch
from launch.actions import ExecuteProcess, TimerAction
import launch_testing
from launch_testing.actions import ReadyToTest
from launch_testing.asserts import assertExitCodes


def generate_test_description():
    environment = {
        "ROS_DOMAIN_ID": "93",
        "ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST",
        "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
    }
    def process(name, executable):
        return ExecuteProcess(
            cmd=[os.environ[executable], "--ros-args", "-r", f"__node:={name}"],
            name=name, additional_env=environment, output="screen",
            sigterm_timeout="5", sigkill_timeout="5",
        )
    first = process("observer_one", "DEMO_OBSERVER")
    second = process("observer_two", "DEMO_OBSERVER")
    client = process("service_verifier", "DEMO_CLIENT")
    producer = process("rust_producer", "DEMO_PRODUCER")
    return launch.LaunchDescription([
        first, second, client,
        # Exercise clients waiting for late server discovery, not just happy startup order.
        TimerAction(period=1.0, actions=[producer]), ReadyToTest(),
    ]), {"first": first, "second": second, "client": client, "producer": producer}


class CommunicationTests(unittest.TestCase):
    def test_pubsub_and_services(self, proc_output, proc_info, first, second, client, producer):
        proc_output.assertWaitFor("ABSENT_SERVICE_TIMEOUT_OK", process=client, stream="stdout", timeout=15)
        proc_output.assertWaitFor("PUBLISHED 40", process=producer, stream="stdout", timeout=40)
        for observer in (first, second):
            proc_output.assertWaitFor("RECEIVED 40 CHECKSUM 23160", process=observer, stream="stdout", timeout=15)
            proc_info.assertWaitForShutdown(process=observer, timeout=10)
        proc_output.assertWaitFor("SERVICE_PASS 12", process=client, stream="stdout", timeout=15)
        proc_info.assertWaitForShutdown(process=client, timeout=10)


@launch_testing.post_shutdown_test()
class ShutdownTests(unittest.TestCase):
    def test_clean_exit(self, proc_info):
        # Includes producer: SIGINT must gracefully exit after all messages and requests.
        assertExitCodes(proc_info, allowable_exit_codes=[0])
