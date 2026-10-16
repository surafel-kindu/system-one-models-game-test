# Published benchmark files

This folder is mounted read-only by the website and scanned recursively for JSON and JSONL.

- `archive.jsonl`: actual existing repository log imported on 2026-10-16. Older records lack engine/control/format metadata and are identified as legacy.
- `baseline-check.json`: actual two-seed Dino + Flappy run of Random, Greedy, and Oracle, created with `./benchmark --quick --games 2 --seed 42 --no-save --json website/benchmark-data/baseline-check.json --plain`.

The baseline run is an interface demonstration, not a model comparison. Add your own runs with `--json website/benchmark-data/unique-name.json` or copy logs using `tools/import_benchmarks.py`. Result files update without rebuilding the container. Keep private files and credentials out of this public data directory.
