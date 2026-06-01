"""One-off: extract hook-9 replacement text from agent transcript into data/."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CHATDEV_DEMO = Path(__file__).resolve().parents[1]
TRANSCRIPT = Path(
    r"C:\Users\ayanm\.cursor\projects\c-Users-ayanm-Desktop-jamila-llmmas-otel"
    r"\agent-transcripts\321d1db2-92f9-4fb8-b2b8-43b433dabdb0"
    r"\321d1db2-92f9-4fb8-b2b8-43b433dabdb0.jsonl"
)
OUT = CHATDEV_DEMO / "data" / "trace_replay_hook9_replacement.txt"


def main() -> None:
    for line in TRANSCRIPT.read_text(encoding="utf-8").splitlines():
        if "inject fault on hook 9" not in line:
            continue
        obj = json.loads(line)
        body = obj["message"]["content"][0]["text"]
        m = re.search(r'"value":\s*"(.*)"\s*-->', body, re.DOTALL)
        if not m:
            raise SystemExit("could not find value in transcript line")
        text = json.loads('"' + m.group(1) + '"')
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT} ({len(text)} chars)")
        return
    raise SystemExit("transcript line not found")


if __name__ == "__main__":
    main()
