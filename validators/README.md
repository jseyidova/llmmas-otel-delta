# Task validators

Standalone validators for ProgramDev / ChatDev generated software. These are **not** part of the `llmmas_otel` Python package; run them from the repo root.

## CalculatorUI (Tkinter)

Validates the ProgramDev calculator **task behaviors** without depending on generated class or function names.

### How it stays name-agnostic

| Step | What happens |
|------|----------------|
| Bootstrap | `exec` of `main.py` with `__name__ == "__main__"` (no imports of `CalculatorApp`, `ButtonGrid`, etc.) |
| Split classes | If `main.py` defines a stub `CalculatorApp` and siblings define the real methods, the harness merges missing methods into `main` before run (WareHouse files unchanged) |
| Window | First `tk.Tk` in namespace (`root`, `app`, or a `tk.Tk` subclass instance) |
| Input | `Button.invoke()` matched by **widget text** (`"2"`, `"+"`, `"C"`, `"⌫"`, …) |
| Output | First `tk.Entry` / `tk.Label` display value |

Required behaviors (from the task description) are exercised only through those labels:

- `2+3=5`, `9-4=5`, `3*4=12`, `8/2=4`, `1.5+2.5=4`
- Clear → empty or `0`
- Backspace removes one character
- `2+3+4=9` (chained)
- `1/0=` → display contains `error` or `zero`

Install test deps once:

```powershell
pip install -e ".[dev]"
```

### Run pytest on a generated project

```powershell
cd C:\Users\ayanm\Desktop\jamila\llmmas-otel

$env:CALCULATOR_PROJECT_DIR = "demos\chatdev-ollama\ChatDev-Ollama\WareHouse\calculator-14_ProgramDevOrg_20260601145603"

pytest validators/calculator_ui -v
```

The path must be under **ChatDev-Ollama\WareHouse**, not `llmmas-otel\WareHouse` (that folder does not exist). If you only set the run folder name, the resolver will try `demos\chatdev-ollama\ChatDev-Ollama\WareHouse\<name>` automatically.

To use the built-in reference app instead of a WareHouse run:

```powershell
Remove-Item Env:CALCULATOR_PROJECT_DIR -ErrorAction SilentlyContinue
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

### Static checks (also name-agnostic)

`python -m validators.calculator_ui` also verifies: `main.py` exists, `if __name__ == '__main__'`, tkinter import, Python syntax compile.

### Test module

| File | What it covers |
|------|----------------|
| `test_behavior.py` | All task behaviors via button labels only; one session check that required buttons exist |

If behavior tests fail but buttons exist, the generated logic is wrong (e.g. `=` appends `=` instead of evaluating)—not a test harness limitation.
