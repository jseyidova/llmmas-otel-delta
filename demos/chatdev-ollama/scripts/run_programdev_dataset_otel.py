import json
import argparse
import os
from pathlib import Path

from chatdev.chat_chain import ChatChain
from camel.typing import ModelType

from llmmas_otel.bootstrap import force_flush_traces, init_otlp_tracing
from llmmas_otel.message_store import enable_message_store
from llmmas_otel.span_factory import default_span_factory
from llmmas_otel import enable_fault_injection
from llmmas_otel.replay_store import enable_prefix_replay, enable_replay_recording

def get_config_paths(company: str):
    script_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    if (cwd / "CompanyConfig").exists():
        root = cwd
    elif (script_dir.parent / "ChatDev-Ollama" / "CompanyConfig").exists():
        root = script_dir.parent / "ChatDev-Ollama"
    else:
        root = script_dir
    config_dir = root / "CompanyConfig" / company
    default_dir = root / "CompanyConfig" / "Default"
    files = ["ChatChainConfig.json", "PhaseConfig.json", "RoleConfig.json"]
    paths = []
    for f in files:
        p = config_dir / f
        paths.append(str(p if p.exists() else (default_dir / f)))
    return tuple(paths)


def run_one_task(task, config_name, org_name, model_type):
    project_name = task["project_name"]
    prompt = task["description"]

    session_id = f"programdev::{project_name}"

    with default_span_factory.session(session_id=session_id):
        config_path, phase_path, role_path = get_config_paths(config_name)

        chain = ChatChain(
            config_path=config_path,
            config_phase_path=phase_path,
            config_role_path=role_path,
            task_prompt=prompt,
            project_name=project_name,
            org_name=org_name,
            model_type=model_type,
            code_path=""
        )

        chain.pre_processing()
        chain.make_recruitment()
        chain.execute_chain()
        chain.post_processing()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="programdev_dataset.json")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--config", type=str, default="Default")
    parser.add_argument("--org", type=str, default="ProgramDevOrg")
    parser.add_argument("--faults", type=str, default="../ChatDev-Ollama/faults.yaml")
    parser.add_argument("--fault-seed", type=str, default="truncate-1")
    parser.add_argument("--fault-trace-visible", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--no-fault-injection", action="store_true")
    parser.add_argument("--record-replay", type=str, default=None)
    parser.add_argument("--replay-prefix", type=str, default=None)
    parser.add_argument("--replay-until-hook-index", type=int, default=None)
    parser.add_argument("--replay-strict", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--trace-full-payloads", action="store_true")
    parser.add_argument("--ollama-timeout-seconds", type=int, default=300)
    parser.add_argument("--message-store", type=str, default="out/messages.jsonl")
    args = parser.parse_args()

    if args.trace_full_payloads:
        os.environ["LLMMAS_TRACE_FULL_PAYLOADS"] = "1"
    os.environ["OLLAMA_REQUEST_TIMEOUT_SECONDS"] = str(args.ollama_timeout_seconds)

    # OTel exporter -> Jaeger OTLP (you must run Jaeger container)
    init_otlp_tracing(service_name="chatdev-programdev", endpoint="http://localhost:4317", insecure=True)

    if not args.no_fault_injection:
        enable_fault_injection(
            args.faults,
            seed=args.fault_seed,
            trace_visible=args.fault_trace_visible,
        )

    if args.record_replay:
        enable_replay_recording(args.record_replay)

    if args.replay_prefix:
        if args.replay_until_hook_index is None:
            raise ValueError("--replay-until-hook-index is required with --replay-prefix")
        enable_prefix_replay(
            args.replay_prefix,
            until_hook_index=args.replay_until_hook_index,
            strict=args.replay_strict,
        )

    # Store full messages to JSONL for later fault injection comparisons
    enable_message_store(args.message_store)

    tasks = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    tasks = tasks[: args.limit]

    try:
        for t in tasks:
            run_one_task(t, args.config, args.org, ModelType.GPT_3_5_TURBO)
    finally:
        force_flush_traces()


if __name__ == "__main__":
    main()
