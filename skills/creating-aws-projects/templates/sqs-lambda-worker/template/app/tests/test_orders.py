import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orders import PoisonMessage, process_order  # noqa: E402


class ProcessOrderTest(unittest.TestCase):
    def test_processes_an_order_with_an_id(self):
        self.assertEqual({"id": "o-1", "status": "processed"}, process_order({"id": "o-1"}))

    def test_message_without_id_is_poison(self):
        with self.assertRaises(PoisonMessage):
            process_order({"action": "process"})

    def test_non_object_message_is_poison(self):
        with self.assertRaises(PoisonMessage):
            process_order(["o-1"])

    def test_fail_action_is_poison(self):
        with self.assertRaisesRegex(PoisonMessage, "o-2"):
            process_order({"id": "o-2", "action": "fail"})


if __name__ == "__main__":
    unittest.main()
