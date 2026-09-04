# Contributing

Thanks for taking a look. This project is small on purpose; keep changes
focused and covered by tests.

## Setup

```bash
git clone https://github.com/andreruizloera/testsniper
cd testsniper
uv sync
```

## Checks

All of these must pass before a pull request:

```bash
uv run ruff format .
uv run ruff check .
uv run pytest -q
```

CI runs the same three commands on Python 3.12 and 3.13.

## Guidelines

- Full type annotations on new code.
- Expected failures (bad revision, not a git repo) must exit nonzero with
  a one-line message, never a traceback.
- The selection algorithm must never silently under-select: if a change
  cannot be traced statically, either over-select or degrade the printed
  confidence with a reason.
- The example project under `examples/fixture_project/` is generated; edit
  `scripts/gen_fixture.py` and regenerate rather than editing it by hand.
- If you change output formats, update the README example by rerunning
  `demo.sh` and pasting the real output.

## Reporting bugs

Open a GitHub issue with the smallest repository layout that reproduces
the wrong selection, plus the exact command and output.
