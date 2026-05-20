import json

import argparse

import os

from pathlib import Path



from chatdev.chat_chain import ChatChain

from camel.typing import ModelType



from llmmas_otel.bootstrap import force_flush_traces, init_otlp_tracing

from llmmas_otel.experiment import configure_chatdev_run



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



    from llmmas_otel.span_factory import default_span_factory



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

    parser = argparse.ArgumentParser(

        description="Run ChatDev ProgramDev tasks with llmmas-otel tracing and optional faults/replay.",

    )

    parser.add_argument("--dataset", type=str, default="programdev_dataset.json")

    parser.add_argument("--limit", type=int, default=3)

    parser.add_argument("--config", type=str, default="Default")

    parser.add_argument("--org", type=str, default="ProgramDevOrg")



    fault_group = parser.add_argument_group("fault injection")

    fault_group.add_argument(

        "--hook-faults",

        "--faults",

        type=str,

        default=None,

        dest="hook_faults",

        help="YAML hook fault specs (llm_call, a2a_send, tool_call, …)",

    )

    fault_group.add_argument(

        "--a2a-fault",

        type=str,

        default=None,

        help="JSON truncate_message spec; requires --replay-jaeger-trace or --replay-a2a-trace",

    )

    fault_group.add_argument("--fault-seed", type=str, default="truncate-1")

    fault_group.add_argument(

        "--fault-trace-visible",

        action=argparse.BooleanOptionalAction,

        default=True,

    )



    replay_group = parser.add_argument_group("replay")

    replay_group.add_argument(

        "--replay-a2a-trace",

        type=str,

        default=None,

        help="Baseline a2a-messages.jsonl to replay (with optional --a2a-fault)",

    )

    replay_group.add_argument(

        "--a2a-replay-strict",

        action=argparse.BooleanOptionalAction,

        default=True,

    )

    replay_group.add_argument(
        "--record-replay",
        type=str,
        default=None,
        help="Legacy: write llm-replay.jsonl (not needed if you use --fetch-jaeger-trace)",
    )

    replay_group.add_argument("--replay-prefix", type=str, default=None)

    replay_group.add_argument("--replay-events", type=str, default=None)

    replay_group.add_argument("--replay-until-hook-index", type=int, default=None)

    replay_group.add_argument(

        "--replay-strict",

        action=argparse.BooleanOptionalAction,

        default=True,

    )



    parser.add_argument("--trace-full-payloads", action="store_true")

    parser.add_argument("--ollama-timeout-seconds", type=int, default=300)

    parser.add_argument(

        "--temperature",

        type=float,

        default=None,

        help="Ollama sampling temperature (sets OLLAMA_TEMPERATURE)",

    )

    parser.add_argument(

        "--a2a-messages",

        "--message-store",

        type=str,

        default=None,

        dest="a2a_messages",

        help="Optional legacy JSONL A2A log (baseline replay uses --fetch-jaeger-trace JSON instead)",

    )

    parser.add_argument(

        "--llm-messages",

        "--llm-calls",

        type=str,

        default=None,

        dest="llm_messages",

        help="Optional legacy JSONL LLM log (not needed with Jaeger trace JSON)",

    )

    replay_group.add_argument(

        "--record-timeline",

        type=str,

        default=None,

        help="Optional hook-order JSONL (Jaeger trace JSON is enough for replay)",

    )

    replay_group.add_argument(

        "--replay-jaeger-trace",

        type=str,

        default=None,

        metavar="PATH",

        help="Baseline Jaeger trace JSON (from fetch_jaeger_trace.py); replays LLM+A2A from it",

    )

    replay_group.add_argument(

        "--fetch-jaeger-trace",

        type=str,

        default=None,

        metavar="PATH",

        help="After the run, fetch latest trace from Jaeger API and save JSON to PATH",

    )

    replay_group.add_argument(

        "--jaeger-session-contains",

        type=str,

        default=None,

        help="When fetching, pick trace whose llmmas.session.id contains this (e.g. MonopolyGo)",

    )

    args = parser.parse_args()



    if args.trace_full_payloads:

        os.environ["LLMMAS_TRACE_FULL_PAYLOADS"] = "1"

    os.environ["OLLAMA_REQUEST_TIMEOUT_SECONDS"] = str(args.ollama_timeout_seconds)

    if args.temperature is not None:

        os.environ["OLLAMA_TEMPERATURE"] = str(args.temperature)



    init_otlp_tracing(service_name="chatdev-programdev", endpoint="http://localhost:4317", insecure=True)



    configure_chatdev_run(

        hook_faults=args.hook_faults,

        a2a_fault=args.a2a_fault,

        fault_seed=args.fault_seed,

        fault_trace_visible=args.fault_trace_visible,

        replay_a2a_trace=args.replay_a2a_trace,

        a2a_replay_strict=args.a2a_replay_strict,

        record_llm_replay=args.record_replay,

        replay_llm_prefix=args.replay_prefix,

        replay_llm_until_hook_index=args.replay_until_hook_index,

        replay_llm_events=args.replay_events,

        replay_llm_strict=args.replay_strict,

        a2a_messages_log=args.a2a_messages,

        llm_calls_log=args.llm_messages,

        record_hook_timeline=args.record_timeline,

        replay_jaeger_trace=args.replay_jaeger_trace,

    )



    tasks = json.loads(Path(args.dataset).read_text(encoding="utf-8"))

    tasks = tasks[: args.limit]



    try:

        for t in tasks:

            run_one_task(t, args.config, args.org, ModelType.GPT_3_5_TURBO)

    finally:

        force_flush_traces()

        if args.fetch_jaeger_trace:
            from llmmas_otel.jaeger_client import fetch_and_save_trace

            info = fetch_and_save_trace(
                args.fetch_jaeger_trace,
                session_contains=args.jaeger_session_contains,
            )
            print(f"Fetched Jaeger baseline trace: {info}")





if __name__ == "__main__":

    main()

