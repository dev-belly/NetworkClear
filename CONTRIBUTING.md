# Contributing

Use Python 3.11 or newer. Install `python -m pip install -e '.[dev]'`, then run:

```bash
python -m unittest discover -s tests -v
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_demo.py
python scripts/generate_preview.py --check
```

On Windows, use PowerShell and the environment's executables directly:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\ruff.exe format --check src tests scripts
.\.venv\Scripts\python.exe scripts/check_demo.py
.\.venv\Scripts\networkclear.exe verify examples/demo
.\.venv\Scripts\python.exe scripts/generate_preview.py --check
```

`.gitattributes` preserves LF text endings on every platform, including Windows
checkouts with `core.autocrlf=true`. Do not convert committed reports or the SVG
preview to CRLF: verification compares their exact bytes. Windows CI also installs
a wheel outside the checkout and runs its demo and verifier. The real symlink test
is skipped only when Windows denies symlink creation with error 1314; all other
filesystem checks still run, and Linux CI runs the symlink rejection test.

Keep amount and availability contracts explicit. Regression coverage must justify
changes in 100 seeded networks, clearing regimes, flows and conservation. If a change intentionally modifies output, regenerate
`examples/demo` in a separate empty directory, compare the diff, replace the
tracked evidence, regenerate the preview, and explain the changed result.
Never update expected evidence automatically inside CI. Preserve source attribution
and identify synthetic fixtures as synthetic.
