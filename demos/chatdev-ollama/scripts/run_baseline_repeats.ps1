# Run the same single-task ProgramDev baseline N times (no fault injection).
# Usage (from ChatDev-Ollama/):
#   ..\scripts\run_baseline_repeats.ps1 -Dataset ..\data\strands_game.json -Repeats 5

param(
    [string]$Dataset = "..\data\strands_game.json",
    [int]$Repeats = 5,
    [int]$OllamaTimeoutSeconds = 1800,
    [string]$Model = "qwen2.5-coder:7b"
)

$ErrorActionPreference = "Stop"

$env:PYTHONPATH = "."
$env:OPENAI_API_KEY = "ollama"
$env:OLLAMA_MODEL = $Model
$env:LLMMAS_TRACE_FULL_PAYLOADS = "1"

for ($i = 1; $i -le $Repeats; $i++) {
    $outDir = Join-Path "out" ("baseline-run-{0:D2}" -f $i)
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null

    $a2a = Join-Path $outDir "a2a-messages.jsonl"
    $replay = Join-Path $outDir "llm-replay.jsonl"
    $log = Join-Path $outDir "run.log"

    Write-Host "=== Baseline run $i / $Repeats -> $outDir ===" -ForegroundColor Cyan

    python ..\scripts\run_programdev_dataset_otel.py `
        --dataset $Dataset `
        --limit 1 `
        --no-fault-injection `
        --record-replay $replay `
        --a2a-messages $a2a `
        --trace-full-payloads `
        --ollama-timeout-seconds $OllamaTimeoutSeconds `
        2>&1 | Tee-Object -FilePath $log

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Run $i failed (exit $LASTEXITCODE). Stopping." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host "All $Repeats baseline runs finished." -ForegroundColor Green
