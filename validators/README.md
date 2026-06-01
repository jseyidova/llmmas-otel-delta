# Task validators

Standalone validators for ProgramDev / ChatDev generated software. These are **not** part of the `llmmas_otel` Python package; run them from the repo root.

## CalculatorUI (Tkinter)

Validates the ProgramDev CalculatorUI task using **pytest** with a `calculator_app` fixture (`test_ui.py` + `test_behavior.py`): logical button keys (`clear`, `backspace`, digits, operators), display checks, arithmetic, clear/backspace, chained ops, divide-by-zero.

Install test deps once:

```powershell
pip install -e ".[dev]"
```

### Run pytest on a generated project

```powershell
cd C:\Users\ayanm\Desktop\jamila\llmmas-otel

$env:CALCULATOR_PROJECT_DIR = "demos\chatdev-ollama\ChatDev-Ollama\WareHouse\CalculatorUI_ProgramDevOrg_20260528184810"

pytest validators/calculator_ui -v
```

### CLI wrapper (static checks + same pytest suite)

```powershell
python -m validators.calculator_ui $env:CALCULATOR_PROJECT_DIR
```

Exit code `0` = pass, `1` = fail.

### CI / reference app

```powershell
pytest validators/calculator_ui -q
# uses tests/fixtures/calculator_reference when CALCULATOR_PROJECT_DIR is unset
```

### Test modules

| File | What it covers |
|------|----------------|
| `test_ui.py` | Display widget, all buttons (aliases for C / ⌫), digit updates display |
| `test_behavior.py` | `2+3=5`, decimals, clear, backspace, chain add, `6*7=42`, divide-by-zero |

Behavior tests use logical keys (`press("clear")`) and accept common button labels via aliases in `harness.py`.
