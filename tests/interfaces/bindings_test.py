"""Verify generated schema and real CDR serialization, without DDS networking."""
import unittest

from demo_interfaces.msg import Calculation, Sample
from rclpy.serialization import deserialize_message, serialize_message


class GeneratedBindingsTests(unittest.TestCase):
    def test_schema(self):
        self.assertEqual(Calculation.get_fields_and_field_types(), {
            "input": "uint64", "output": "uint64",
        })
        self.assertEqual(Sample.get_fields_and_field_types(), {
            "sequence": "uint64",
            "stamp": "builtin_interfaces/Time",
            "source": "string",
            "calculation": "demo_interfaces/Calculation",
            "recent_outputs": "sequence<uint64>",
        })

    def test_nested_round_trip(self):
        sample = Sample()
        sample.sequence = 39
        sample.stamp.sec = 1_700_000_000
        sample.stamp.nanosec = 975_000_000
        sample.source = "rust_transform"
        sample.calculation = Calculation(input=39, output=1645)
        for history in ([], [1487, 1565, 1645], [0, 2**64 - 1]):
            with self.subTest(history=history):
                sample.recent_outputs = history
                decoded = deserialize_message(serialize_message(sample), Sample)
                self.assertEqual(decoded, sample)
                self.assertEqual(list(decoded.recent_outputs), history)


if __name__ == "__main__":
    unittest.main()
