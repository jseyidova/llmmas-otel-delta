import json
import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

from chatdev.chat_chain import ChatChain
from camel.typing import ModelType

from llmmas_otel.bootstrap import force_flush_traces, init_otlp_tracing
from llmmas_otel.jaeger_client import (
    DEFAULT_JAEGER_QUERY_URL,
    default_trace_output_path,
    fetch_and_save_latest_trace,
)
from llmmas_otel.message_store import enable_message_store
from llmmas_otel.span_factory import default_span_factory

from llmmas_otel.injection import enable_fault_injection
from llmmas_otel import enable_trace_replay, load_trace_replay_config

from run_naming import (
    allocate_run_id,
    find_warehouse_dir,
    run_paths,
    series_from_dataset,
    write_run_meta,
)

logger = logging.getLogger(__name__)
OTEL_SERVICE_NAME = "chatdev-programdev"


def str2bool(value):
    if isinstance(value, bool):
        return value
    v = value.strip().lower()
    if v in {"true", "1", "yes", "y", "on"}:
        return True
    if v in {"false", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(
        f"Invalid boolean value: {value}. Use true/false."
    )

def get_config_paths(company: str):
    root = Path(__file__).resolve().parent
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
    parser.add_argument("--faults", type=str, default=None)
    parser.add_argument("--trace-visible", type=str2bool, default=True)
    parser.add_argument(
        "--trace-full-payloads",
        action="store_true",
        help="Record full message/LLM text on spans (sets LLMMAS_TRACE_FULL_PAYLOADS=1)",
    )
    parser.add_argument(
        "--trace-replay-config",
        type=str,
        default=None,
        help="JSON/YAML config for baseline Jaeger trace replay (mode=trace_replay)",
    )
    parser.add_argument(
        "--ollama-timeout-seconds",
        type=int,
        default=18_000,
        help="Per-request Ollama HTTP read timeout (default 18000 = 5 hours). Sets OLLAMA_REQUEST_TIMEOUT_SECONDS.",
    )
    parser.add_argument(
        "--ollama-connect-timeout-seconds",
        type=int,
        default=30,
        help="Ollama HTTP connect timeout (default 30). Sets OLLAMA_CONNECT_TIMEOUT_SECONDS.",
    )
    parser.add_argument(
        "--task-timeout-seconds",
        type=int,
        default=18_000,
        help="Wall-clock limit per task (default 18000 = 5 hours). Use 0 to disable.",
    )
    parser.add_argument(
        "--fetch-jaeger-trace",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After each task, flush OTLP and save the latest Jaeger trace JSON (default: on)",
    )
    parser.add_argument(
        "--jaeger-url",
        type=str,
        default=DEFAULT_JAEGER_QUERY_URL,
        help=f"Jaeger query API base URL (default: {DEFAULT_JAEGER_QUERY_URL})",
    )
    parser.add_argument(
        "--jaeger-trace-out",
        type=str,
        default=None,
        help="Output path for fetched trace JSON (overrides --auto-run-id trace path if set)",
    )
    parser.add_argument(
        "--auto-run-id",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use incrementing run IDs (e.g. calculator-01) for WareHouse + out/<series>/ (default: on)",
    )
    parser.add_argument(
        "--run-series",
        type=str,
        default=None,
        help="Series prefix for run IDs (default: dataset stem, e.g. calculator from calculator.json)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Fixed run ID (e.g. calculator-05); skips auto-increment",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    os.environ["OLLAMA_CONNECT_TIMEOUT_SECONDS"] = str(args.ollama_connect_timeout_seconds)
    os.environ["OLLAMA_REQUEST_TIMEOUT_SECONDS"] = str(args.ollama_timeout_seconds)

    if args.trace_full_payloads:
        os.environ["LLMMAS_TRACE_FULL_PAYLOADS"] = "1"


    if args.faults:
        enable_fault_injection(
            args.faults,
            trace_visible=args.trace_visible,
        )

    if args.trace_replay_config:
        replay_cfg = load_trace_replay_config(args.trace_replay_config)
        trace_path = Path(replay_cfg.trace_path)
        if not trace_path.is_absolute():
            config_dir = Path(args.trace_replay_config).resolve().parent
            candidate = (config_dir / trace_path).resolve()
            trace_path = candidate if candidate.exists() else (Path.cwd() / trace_path).resolve()
        payload = {
            "mode": replay_cfg.mode,
            "trace_path": str(trace_path),
            "hooks": replay_cfg.hooks,
        }
        if replay_cfg.live_from_hook_index is not None:
            payload["live_from_hook_index"] = replay_cfg.live_from_hook_index
        if replay_cfg.fault is not None:
            payload["inject_at_hook_index"] = replay_cfg.fault.inject_at_hook_index
            payload["fault_type"] = replay_cfg.fault.fault_type
            if replay_cfg.fault.replacement_message is not None:
                payload["replacement_message"] = replay_cfg.fault.replacement_message
            payload["truncate_length"] = replay_cfg.fault.truncate_length
            payload["propagate_to_llm"] = replay_cfg.fault.propagate_to_llm
            payload["llm_propagate_calls"] = replay_cfg.fault.llm_propagate_calls
            payload["propagate_to_live_a2a"] = replay_cfg.fault.propagate_to_live_a2a
            if replay_cfg.fault.truncated_task_prompt is not None:
                payload["truncated_task_prompt"] = replay_cfg.fault.truncated_task_prompt
        enable_trace_replay(payload)

    init_otlp_tracing(
        service_name=OTEL_SERVICE_NAME,
        endpoint="http://localhost:4317",
        insecure=True,
    )


    tasks = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    tasks = tasks[: args.limit]
    cwd = Path.cwd()
    dataset_path = Path(args.dataset)
    series = args.run_series or series_from_dataset(dataset_path.resolve())

    for t in tasks:
        run_started_micros = int(time.time() * 1_000_000) if args.fetch_jaeger_trace else None
        base_project = t.get("project_name", "unknown")

        if args.auto_run_id:
            run_id = allocate_run_id(series, cwd=cwd, explicit_run_id=args.run_id)
            paths = run_paths(series, run_id, cwd=cwd)
            task = {**t, "project_name": run_id}
            enable_message_store(str(paths.messages_jsonl))
            print(f"Run ID: {run_id}  (WareHouse will be {run_id}_{args.org}_<timestamp>)")
            print(f"  run dir: {paths.run_dir}")
            print(f"  trace: {paths.trace_json}")
            print(f"  messages: {paths.messages_jsonl}")
        else:
            task = dict(t)
            paths = None
            enable_message_store("out/messages.jsonl")

        project_name = task.get("project_name", "unknown")

        if args.task_timeout_seconds and args.task_timeout_seconds > 0:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(run_one_task, task, args.config, args.org, ModelType.GPT_3_5_TURBO)
                try:
                    fut.result(timeout=args.task_timeout_seconds)
                except FuturesTimeoutError as exc:
                    raise TimeoutError(
                        f"Task exceeded --task-timeout-seconds={args.task_timeout_seconds} "
                        f"({args.task_timeout_seconds / 3600:.1f} hours): "
                        f"{project_name}"
                    ) from exc
        else:
            run_one_task(task, args.config, args.org, ModelType.GPT_3_5_TURBO)

        saved_trace: Path | None = None
        if args.fetch_jaeger_trace:
            force_flush_traces()
            if args.jaeger_trace_out:
                out_path = Path(args.jaeger_trace_out)
            elif paths is not None:
                out_path = paths.trace_json
            else:
                out_path = default_trace_output_path(project_name)
            try:
                saved_trace = fetch_and_save_latest_trace(
                    service=OTEL_SERVICE_NAME,
                    output_path=out_path,
                    base_url=args.jaeger_url,
                    min_start_micros=run_started_micros,
                )
                print(f"Jaeger trace saved: {saved_trace.resolve()}")
            except RuntimeError as exc:
                logger.error("%s", exc)
                raise

        if paths is not None:
            warehouse = find_warehouse_dir(cwd, paths.run_id, args.org)
            meta_path = write_run_meta(
                paths,
                cwd=cwd,
                org_name=args.org,
                dataset=str(dataset_path),
                warehouse_dir=warehouse,
                trace_saved=saved_trace,
                extra={"base_project_name": base_project},
            )
            if warehouse:
                print(f"WareHouse: {warehouse.resolve()}")
            else:
                print(f"WareHouse: (not found yet; expected {paths.warehouse_glob(args.org)})")
            print(f"Run manifest: {meta_path.resolve()}")


if __name__ == "__main__":
    main()
