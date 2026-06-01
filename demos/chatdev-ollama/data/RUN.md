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

# Replay + inject fault at hook 2, then live
python run_programdev_dataset_otel.py `
  --dataset ..\data\calculator.json `
  --limit 1 `
  --trace-replay-config ..\data\trace_replay_inject_hook2.json `
  --trace-full-payloads `
  --ollama-timeout-seconds 3600 `
  --task-timeout-seconds 3600
```
