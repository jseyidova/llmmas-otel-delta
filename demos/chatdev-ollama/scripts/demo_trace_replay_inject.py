#!/usr/bin/env python3
"""
Demonstrate replay → inject fault at hook N → live execution.

Usage (from repo root, with baseline trace available):
  python demos/chatdev-ollama/scripts/demo_trace_replay_inject.py \\
    tests/fixtures/jaeger_minimal_a2a.json

Shows hooks 1-2 replayed, hook 3 injected, hook 4+ live (fixture has 4 A2A hooks).
For hook 15 on a real calculator trace, use trace_replay_inject_hook15.json with ChatDev.
"""

from __future__ import annotations

import sys
from pathlib import Path

from llmmas_otel.injection import HookType, SequentialReplayProvider
from llmmas_otel.injection.replay_provider import ReplayFaultConfig
from llmmas_otel.injection.trace_replay import trace_replay_config_from_dict


def main() -> int:
    trace_path = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "jaeger_minimal_a2a.json"
    )
    inject_hook = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    cfg = trace_replay_config_from_dict(
        {
            "mode": "trace_replay",
            "trace_path": trace_path,
            "inject_at_hook": inject_hook,
            "fault_type": "replace",
            "replacement_message": "TRUNCATED MESSAGE BODY HERE",
        }
    )
    assert cfg.fault is not None
    provider = SequentialReplayProvider.from_jaeger_trace(
        cfg.trace_path,
        hooks=cfg.hooks,
        fault=cfg.fault,
    )

    print(f"Baseline trace: {trace_path}")
    print(f"Inject at hook #{inject_hook} (index {cfg.fault.inject_at_hook_index})")
    print(f"Live from hook #{inject_hook + 1} (index {cfg.live_from_hook_index})")
    print()

    for n in range(1, 7):
        hook_type = HookType.A2A_SEND if n % 2 == 1 else HookType.A2A_RECEIVE
        live_label = f"live-{n}"
        out = provider.replay_message_body(hook_type, live_label)
        if out == live_label:
            mode = "LIVE"
        elif out == "TRUNCATED MESSAGE BODY HERE":
            mode = "FAULT"
        else:
            mode = "REPLAY"
        print(f"hook #{n:2d} ({hook_type.value:12s}) -> [{mode:6s}] {out!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
