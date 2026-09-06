# MOVED — the stage tests live in `tests/`

These tests now live at [`tests/test_stage_naming.py`](../../../tests/test_stage_naming.py),
next to the rest of the suite, so `make test` and a bare `pytest` collect them with
everything else.

```
python3 -m pytest tests/test_stage_naming.py -q
```

This directory holds no tests. Keeping a second copy under `tools/stages/tests/` would let
the two drift, which is the defect class the audit found throughout this repo.

**Why this is a `.md` and not a `.py`.** It was `tools/stages/tests/test_stage_naming.py`
— a file with a docstring and no tests, carrying the same basename as the real suite's
`tests/test_stage_naming.py`. `make test` passes `tests` explicitly and never saw it, but a
bare `pytest` from the repository root collected both, and pytest's rootdir import mode
resolves a test module by basename:

```
ERROR collecting tools/stages/tests/test_stage_naming.py
import file mismatch:
imported module 'test_stage_naming' has this __file__ attribute:
  /data/media_curate/tests/test_stage_naming.py
which is not the same as the test file we want to collect:
  /data/media_curate/tools/stages/tests/test_stage_naming.py
```

Collection was interrupted, so a contributor running `pytest` directly got an import error
instead of a test suite. The pointer is the whole content of the file, so it is a README;
`pytest.ini` at the repository root sets `--import-mode=importlib` as well, which stops the
next duplicate basename from doing the same thing.
