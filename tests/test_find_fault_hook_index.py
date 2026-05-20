from __future__ import annotations

import unittest

from llmmas_otel.injection.a2a_fault import find_fault_hook_index


class TestFindFaultHookIndex(unittest.TestCase):
    def test_matches_when_direction_only_in_hook_type(self) -> None:
        messages = [
            {
                "hook_index": 40,
                "hook_type": "a2a_receive",
                "segment": {"name": "Coding", "order": 1},
                "edge_id": "Chief Technology Officer->Programmer",
                "source_agent_id": "Chief Technology Officer",
                "target_agent_id": "Programmer",
            }
        ]
        fault_spec = {
            "enabled": True,
            "fault_type": "truncate_message",
            "selector": {
                "segment_name": "Coding",
                "edge_id": "Chief Technology Officer->Programmer",
                "direction": "receive",
                "occurrence": 0,
            },
            "truncate": {"mode": "max_chars", "max_chars": 10},
        }
        self.assertEqual(find_fault_hook_index(messages, fault_spec), 40)

    def test_matches_direction_from_operation_name(self) -> None:
        messages = [
            {
                "hook_index": 7,
                "hook_type": "a2a_message",
                "operation_name": "process Chief Technology Officer->Programmer",
                "segment": {"name": "Coding"},
                "edge_id": "Chief Technology Officer->Programmer",
                "source_agent_id": "Chief Technology Officer",
                "target_agent_id": "Programmer",
            }
        ]
        fault_spec = {
            "enabled": True,
            "fault_type": "truncate_message",
            "selector": {
                "segment_name": "Coding",
                "direction": "receive",
                "occurrence": 0,
            },
            "truncate": {"mode": "max_chars", "max_chars": 5},
        }
        self.assertEqual(find_fault_hook_index(messages, fault_spec), 7)

    def test_matches_exact_hook_index(self) -> None:
        messages = [
            {"hook_index": 3, "edge_id": "Chief Executive Officer->Chief Technology Officer", "direction": "receive"},
            {"hook_index": 5, "edge_id": "Chief Technology Officer->Programmer", "direction": "receive"},
        ]
        fault_spec = {
            "enabled": True,
            "fault_type": "truncate_message",
            "selector": {"hook_index": 3, "direction": "receive"},
            "truncate": {"mode": "max_chars", "max_chars": 1},
        }
        self.assertEqual(find_fault_hook_index(messages, fault_spec), 3)


if __name__ == "__main__":
    unittest.main()
