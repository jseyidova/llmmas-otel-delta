# ChatDev calculator runs (from `ChatDev-Ollama/`)

Standard flags used in this repo:

- `--ollama-timeout-seconds 3600` — 1 hour per Ollama HTTP request
- `--task-timeout-seconds 3600` — 1 hour wall-clock per task

```powershell
cd demos\chatdev-ollama\ChatDev-Ollama
.venv\Scripts\Activate.ps1
Copy-Item ..\scripts\run_programdev_dataset_otel.py . -Force
Copy-Item ..\scripts\run_naming.py . -Force
pip install -e ..\..\..
$env:OPENAI_API_KEY = "ollama"
$env:PYTHONPATH = "."

Each run auto-allocates **calculator-01**, **calculator-02**, … (default on):

- Trace: `out/calculator/calculator-NN-jaeger-trace.json`
- WareHouse: `WareHouse/calculator-NN_ProgramDevOrg_<timestamp>/`
- Manifest: `out/calculator/calculator-NN-run.json`
- Latest pointer: `out/calculator/latest-run.txt`

Disable with `--no-auto-run-id` (uses `CalculatorUI` from dataset).

# Trace replay only (no fault): calculator-17 baseline, replay hooks 1–5, live from hook 6
# live_from_hook_number: 6 = first *live* hook is #6 (hooks 1..5 replayed from jaeger-trace.json)
python run_programdev_dataset_otel.py `
  --dataset ..\data\calculator.json `
  --limit 1 `
  --trace-replay-config ..\data\trace_replay_calculator17_until_hook5.json `
  --trace-full-payloads `
  --fetch-jaeger-trace `
  --ollama-timeout-seconds 3600 `
  --task-timeout-seconds 3600

# Baseline (no replay / no faults)
python run_programdev_dataset_otel.py `
  --dataset ..\data\calculator.json `
  --limit 1 `
  --trace-full-payloads `
  --fetch-jaeger-trace `
  --ollama-timeout-seconds 3600 `
  --task-timeout-seconds 3600

# Trace replay: calculator-14 baseline, replace hook 4 (Coding send: Programmer → CTO)
# Faulty code: no `C` branch in on_button_click; no ZeroDivisionError handler in evaluate_expression
python run_programdev_dataset_otel.py `
  --dataset ..\data\calculator.json `
  --limit 1 `
  --trace-replay-config ..\data\trace_replay_inject_hook4_calculator14.json `
  --trace-full-payloads `
  --fetch-jaeger-trace `
  --ollama-timeout-seconds 3600 `
  --task-timeout-seconds 3600

# Same hook 4, but corrupt chat_env.task_prompt (CodeReview {task} placeholder) + live A2A Task: lines
# truncated_task ends at '*' (no / . = clear backspace or behavioral reqs)
python run_programdev_dataset_otel.py `
  --dataset ..\data\calculator.json `
  --limit 1 `
  --trace-replay-config ..\data\trace_replay_inject_hook4_calculator14_corrupt_env_only.json `
  --trace-full-payloads `
  --fetch-jaeger-trace `
  --ollama-timeout-seconds 3600 `
  --task-timeout-seconds 3600

# Hook 4: faulty code replacement AND corrupt chat_env (combined fault)
python run_programdev_dataset_otel.py `
  --dataset ..\data\calculator.json `
  --limit 1 `
  --trace-replay-config ..\data\trace_replay_inject_hook4_calculator14_corrupt_env.json `
  --trace-full-payloads `
  --fetch-jaeger-trace `
  --ollama-timeout-seconds 3600 `
  --task-timeout-seconds 3600
```
