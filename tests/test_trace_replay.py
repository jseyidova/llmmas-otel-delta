from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llmmas_otel.injection import (
    HookType,
    ReplayEvent,
    SequentialReplayProvider,
    disable_trace_replay,
    enable_trace_replay,
    extract_replay_events,
    is_trace_replay_enabled,
    load_replay_events_from_jaeger,
    load_trace_replay_config,
)
from llmmas_otel.injection.trace_replay import apply_trace_replay_to_llm_messages, apply_trace_replay_to_message_body
from llmmas_otel.span_factory import SpanFactory


FIXTURE = Path(__file__).parent / "fixtures" / "jaeger_minimal_a2a.json"


class TraceReplayParseTest(unittest.TestCase):
    def test_load_and_extract_a2a_events(self) -> None:
        events = load_replay_events_from_jaeger(str(FIXTURE))
        self.assertEqual(len(events), 4)

        self.assertEqual(events[0].hook_type, "a2a_send")
        self.assertEqual(events[0].message_body, "SEND_BODY_1")
        self.assertEqual(events[0].sender, "Planner")
        self.assertEqual(events[0].receiver, "Coder")

        self.assertEqual(events[1].hook_type, "a2a_receive")
        self.assertEqual(events[1].message_body, "RECEIVE_BODY_1")
        self.assertEqual(events[1].segment_name, "Coding")

        send_events = [e for e in events if e.hook_type == "a2a_send"]
        receive_events = [e for e in events if e.hook_type == "a2a_receive"]
        self.assertEqual([e.message_body for e in send_events], ["SEND_BODY_1", "SEND_BODY_2"])
        self.assertEqual([e.message_body for e in receive_events], ["RECEIVE_BODY_1", "RECEIVE_BODY_2"])

    def test_extract_from_dict(self) -> None:
        doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
        events = extract_replay_events(doc)
        self.assertTrue(all(isinstance(e, ReplayEvent) for e in events))


class SequentialReplayProviderTest(unittest.TestCase):
    def test_replay_by_hook_type_order(self) -> None:
        provider = SequentialReplayProvider.from_jaeger_trace(str(FIXTURE))

        self.assertEqual(
            provider.replay_message_body(HookType.A2A_SEND, "live-1"),
            "SEND_BODY_1",
        )
        self.assertEqual(
            provider.replay_message_body(HookType.A2A_RECEIVE, "live-2"),
            "RECEIVE_BODY_1",
        )
        self.assertEqual(
            provider.replay_message_body(HookType.A2A_SEND, "live-3"),
            "SEND_BODY_2",
        )

    def test_fallback_when_exhausted(self) -> None:
        provider = SequentialReplayProvider.from_jaeger_trace(str(FIXTURE))
        for _ in range(4):
            provider.replay_message_body(HookType.A2A_SEND, "x")
        out = provider.replay_message_body(HookType.A2A_SEND, "keep-me")
        self.assertEqual(out, "keep-me")

    def test_live_from_hook_index(self) -> None:
        provider = SequentialReplayProvider.from_jaeger_trace(
            str(FIXTURE),
            live_from_hook_index=2,
        )
        self.assertEqual(provider.replay_message_body(HookType.A2A_SEND, "live-a"), "SEND_BODY_1")
        self.assertEqual(provider.replay_message_body(HookType.A2A_RECEIVE, "live-b"), "RECEIVE_BODY_1")
        self.assertEqual(provider.replay_message_body(HookType.A2A_SEND, "live-c"), "live-c")

    def test_live_from_hook_number_in_config(self) -> None:
        from llmmas_otel.injection.trace_replay import trace_replay_config_from_dict

        cfg = trace_replay_config_from_dict(
            {
                "mode": "trace_replay",
                "trace_path": str(FIXTURE),
                "live_from_hook_number": 3,
            }
        )
        self.assertEqual(cfg.live_from_hook_index, 2)

    def test_replay_inject_fault_then_live(self) -> None:
        """
        Hooks 1-2 replay baseline, hook 3 inject replacement, hook 4+ live.
        (Analogous to replay hooks 1-14, inject at 15, live from 16 on a longer trace.)
        """
        from llmmas_otel.injection.replay_provider import ReplayFaultConfig

        provider = SequentialReplayProvider.from_jaeger_trace(
            str(FIXTURE),
            fault=ReplayFaultConfig(
                inject_at_hook_index=2,
                fault_type="replace",
                replacement_message="TRUNCATED MESSAGE BODY HERE",
            ),
        )
        self.assertEqual(
            provider.replay_message_body(HookType.A2A_SEND, "live-1"),
            "SEND_BODY_1",
        )
        self.assertEqual(
            provider.replay_message_body(HookType.A2A_RECEIVE, "live-2"),
            "RECEIVE_BODY_1",
        )
        self.assertEqual(
            provider.replay_message_body(HookType.A2A_SEND, "live-3"),
            "TRUNCATED MESSAGE BODY HERE",
        )
        self.assertEqual(
            provider.replay_message_body(HookType.A2A_RECEIVE, "live-4"),
            "live-4",
        )

    def test_inject_at_hook_15_from_config(self) -> None:
        from llmmas_otel.injection.trace_replay import trace_replay_config_from_dict

        cfg = trace_replay_config_from_dict(
            {
                "mode": "trace_replay",
                "trace_path": str(FIXTURE),
                "inject_at_hook": 3,
                "fault_type": "replace",
                "replacement_message": "INJECTED_AT_HOOK_3",
            }
        )
        self.assertIsNotNone(cfg.fault)
        assert cfg.fault is not None
        self.assertEqual(cfg.fault.inject_at_hook_index, 2)
        self.assertEqual(cfg.live_from_hook_index, 3)

        provider = SequentialReplayProvider.from_jaeger_trace(
            str(FIXTURE),
            fault=cfg.fault,
        )
        self.assertEqual(provider.replay_message_body(HookType.A2A_SEND, "a"), "SEND_BODY_1")
        self.assertEqual(provider.replay_message_body(HookType.A2A_RECEIVE, "b"), "RECEIVE_BODY_1")
        self.assertEqual(
            provider.replay_message_body(HookType.A2A_SEND, "c"),
            "INJECTED_AT_HOOK_3",
        )
        self.assertEqual(provider.replay_message_body(HookType.A2A_RECEIVE, "d"), "d")

    def test_replacement_message_file(self) -> None:
        from llmmas_otel.injection.trace_replay import load_trace_replay_config

        with tempfile.TemporaryDirectory() as td:
            cfg_dir = Path(td)
            (cfg_dir / "repl.txt").write_text("FROM_FILE", encoding="utf-8")
            cfg_path = cfg_dir / "cfg.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "mode": "trace_replay",
                        "trace_path": str(FIXTURE),
                        "inject_at_hook": 2,
                        "fault_type": "replace",
                        "replacement_message_file": "repl.txt",
                    }
                ),
                encoding="utf-8",
            )
            cfg = load_trace_replay_config(cfg_path)
            assert cfg.fault is not None
            self.assertEqual(cfg.fault.replacement_message, "FROM_FILE")

    def test_truncate_a2a_task_content(self) -> None:
        from llmmas_otel.injection.replay_provider import truncate_a2a_task_content

        body = 'Phase intro\n\nTask: "FULL calculator with / and clear".\n\nWe have decided'
        out = truncate_a2a_task_content(body, "SHORT TASK ONLY")
        self.assertIn('Task: "SHORT TASK ONLY"', out)
        self.assertNotIn("/ and clear", out)

    def test_corrupt_chat_env_at_inject(self) -> None:
        from llmmas_otel.injection.chat_env_fault import (
            apply_task_prompt_corruption,
            clear_chat_env_registration,
            register_chat_env,
        )
        from llmmas_otel.injection.replay_provider import ReplayFaultConfig

        class FakeEnv:
            def __init__(self) -> None:
                self.env_dict = {"task_prompt": "FULL TASK WITH / AND = AND CLEAR"}

        fake = FakeEnv()
        register_chat_env(lambda: fake)
        try:
            provider = SequentialReplayProvider.from_jaeger_trace(
                str(FIXTURE),
                fault=ReplayFaultConfig(
                    inject_at_hook_index=2,
                    fault_type="replace",
                    replacement_message='Task: "ignored"',
                    corrupt_chat_env=True,
                    truncated_task_prompt="SHORT TASK ONLY",
                    propagate_to_llm=False,
                    llm_propagate_calls=0,
                    propagate_to_live_a2a=False,
                ),
            )
            provider.replay_message_body(HookType.A2A_SEND, "live-1")
            provider.replay_message_body(HookType.A2A_RECEIVE, "live-2")
            provider.replay_message_body(HookType.A2A_SEND, "INJECTED")
            self.assertEqual(fake.env_dict["task_prompt"], "SHORT TASK ONLY")
            self.assertNotIn("/", fake.env_dict["task_prompt"])
        finally:
            clear_chat_env_registration()

        self.assertFalse(
            apply_task_prompt_corruption("x"),
        )

    def test_inject_message_file_alias(self) -> None:
        from llmmas_otel.injection.trace_replay import load_trace_replay_config

        with tempfile.TemporaryDirectory() as td:
            cfg_dir = Path(td)
            (cfg_dir / "msg.txt").write_text("INJECTED CONTEXT", encoding="utf-8")
            cfg_path = cfg_dir / "cfg.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "mode": "trace_replay",
                        "trace_path": str(FIXTURE),
                        "inject_at_hook": 2,
                        "injection_type": "replace",
                        "inject_message_file": "msg.txt",
                    }
                ),
                encoding="utf-8",
            )
            cfg = load_trace_replay_config(cfg_path)
            assert cfg.fault is not None
            self.assertEqual(cfg.fault.replacement_message, "INJECTED CONTEXT")

    def test_live_a2a_truncates_task_after_inject(self) -> None:
        from llmmas_otel.injection.replay_provider import ReplayFaultConfig

        provider = SequentialReplayProvider.from_jaeger_trace(
            str(FIXTURE),
            fault=ReplayFaultConfig(
                inject_at_hook_index=2,
                fault_type="replace",
                replacement_message='Task: "SHORT TASK ONLY"',
                propagate_to_llm=False,
                llm_propagate_calls=0,
                propagate_to_live_a2a=True,
            ),
        )
        provider.replay_message_body(HookType.A2A_SEND, "live-1")
        provider.replay_message_body(HookType.A2A_RECEIVE, "live-2")
        provider.replay_message_body(HookType.A2A_SEND, "INJECTED")
        live_coding = (
            "According to the new user's task:\n\n"
            'Task: "FULL calculator with / and clear".\n\nWe have decided'
        )
        out = provider.replay_message_body(HookType.A2A_RECEIVE, live_coding)
        self.assertIn("SHORT TASK ONLY", out or "")
        self.assertNotIn("/ and clear", out or "")

    def test_llm_propagate_strips_system_task_after_inject(self) -> None:
        from llmmas_otel.injection.replay_provider import ReplayFaultConfig, truncate_system_task_content

        provider = SequentialReplayProvider.from_jaeger_trace(
            str(FIXTURE),
            fault=ReplayFaultConfig(
                inject_at_hook_index=1,
                fault_type="replace",
                replacement_message='Task: "SHORT TASK ONLY',
                propagate_to_llm=True,
                llm_propagate_calls=1,
            ),
        )
        provider.replay_message_body(HookType.A2A_SEND, "live-1")
        provider.replay_message_body(HookType.A2A_RECEIVE, "live-2-inject")

        system = (
            "You are CTO. Here is a new customer's task: "
            "Build a desktop calculator app with many requirements. "
            "To complete the task, you must write a response."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "SHORT USER MSG"},
        ]
        out = provider.apply_llm_messages(messages)
        self.assertIn("SHORT TASK ONLY", out[0]["content"])
        self.assertNotIn("many requirements", out[0]["content"])
        # second call no longer propagates
        out2 = provider.apply_llm_messages(messages)
        self.assertEqual(out2[0]["content"], system)

    def test_apply_trace_replay_to_llm_messages_integration(self) -> None:
        enable_trace_replay(
            {
                "mode": "trace_replay",
                "trace_path": str(FIXTURE),
                "inject_at_hook": 2,
                "fault_type": "replace",
                "replacement_message": 'Task: "TRUNCATED"',
                "propagate_to_llm": True,
                "llm_propagate_calls": 1,
            }
        )
        apply_trace_replay_to_message_body(HookType.A2A_SEND, "a")
        apply_trace_replay_to_message_body(HookType.A2A_RECEIVE, "b")

        msgs = [{"role": "system", "content": "Here is a new customer's task: FULL TASK. To complete the task, go."}]
        out = apply_trace_replay_to_llm_messages(msgs)
        self.assertIn("TRUNCATED", out[0]["content"])
        disable_trace_replay()


class TraceReplayIntegrationTest(unittest.TestCase):
    def tearDown(self) -> None:
        disable_trace_replay()

    def test_enable_from_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "replay.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "mode": "trace_replay",
                        "trace_path": str(FIXTURE),
                        "hooks": ["a2a_send", "a2a_receive"],
                    }
                ),
                encoding="utf-8",
            )
            enable_trace_replay(load_trace_replay_config(str(cfg_path)))
            self.assertTrue(is_trace_replay_enabled())

            mutated: dict[str, str] = {"body": "original"}

            def _apply(new_body: str) -> None:
                mutated["body"] = new_body

            out = apply_trace_replay_to_message_body(
                HookType.A2A_SEND,
                mutated["body"],
                apply_mutation=_apply,
            )
            self.assertEqual(out, "SEND_BODY_1")
            self.assertEqual(mutated["body"], "SEND_BODY_1")

    def test_span_factory_applies_replay(self) -> None:
        enable_trace_replay(
            {
                "mode": "trace_replay",
                "trace_path": str(FIXTURE),
                "hooks": ["a2a_send"],
            }
        )
        sf = SpanFactory(tracer_name="test-trace-replay")
        captured: dict[str, str] = {}

        with sf.a2a_send(
            source_agent_id="Planner",
            target_agent_id="Coder",
            edge_id="Planner->Coder",
            message_id="m1",
            message_body="runtime-original",
            apply_mutation=lambda b: captured.update({"body": b}),
        ):
            pass

        self.assertEqual(captured["body"], "SEND_BODY_1")


if __name__ == "__main__":
    unittest.main()
