# ProstaPaper

Install the project dependencies into `.venv` with:

```sh
uv sync
```

Run the local handwriting extraction with:

```sh
OPENBLAS_CORETYPE=Haswell uv run python scripts/extract_handwriting.py
```

On this QEMU host, `OPENBLAS_CORETYPE=Haswell` is required for homography.

Run the handwriting tests with:

```sh
OPENBLAS_CORETYPE=Haswell uv run pytest tests/test_handwriting.py
```

Show the Gemini REST probe options with:

```sh
uv run --env-file .env python scripts/probe_gemini.py --help
```

Prepare the default eight crop pairs without an API call:

```sh
uv run python scripts/probe_gemini.py --dry-run
```

Run both Gemini models using the local key:

```sh
OPENBLAS_CORETYPE=Haswell uv run --env-file .env python scripts/probe_gemini.py
```

The default run makes 32 independent readings, with at most one retry each.
Original and modified crops are separate requests. Raw responses, validated
results and provenance go into a new directory under `Other/output/gemini-probe/`.
`--cases 7:base --models gemini-3.8-flash` runs a smaller two-reading probe.

Run all tests with `OPENBLAS_CORETYPE=Haswell uv run pytest -q`.
