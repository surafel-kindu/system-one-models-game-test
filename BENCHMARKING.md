# Benchmarking

From this folder, use the launcher. It finds this checkout's `.venv`, so you do not need to activate it.
No extra terminal UI packages are required.

```bash
./benchmark
```

With no flags in an interactive terminal, a short wizard offers a quick baseline check, a model
comparison on Dino + Flappy, or a five-game suite. Choose players, seed count and assisted/raw
control. It prints the equivalent command so you can repeat it later.

For a quick run with no questions:

```bash
./benchmark --quick
```

This plays three seeded games per baseline (`random`, `greedy`, `oracle`) on Dino + Flappy.
It does not load model weights or make hosted API calls. To invoke Python directly, use
`python benchmark.py` from the activated venv. With no flags in a non-interactive shell, the
original 2048/all-players defaults apply; use explicit flags in scripts and CI.

## Console display

In a terminal, a live status line shows a progress bar, completed games, current player, seed,
step/ply, score, elapsed time and an approximate ETA. It keeps updating while a model is loading
or answering. Each completed seed prints its score; each game ends with a ranked table including
score bars, mean, standard deviation, median, worst and best. Multi-game suites end with an overall
leaderboard. ETA is based on completed games, so mixed model speeds can make it inaccurate.

Redirected output and `--plain` use clean line-based progress. `NO_COLOR` disables ANSI color.
Ctrl+C exits with status 130. Completed player checkpoints remain in the saved run, marked
`interrupted`; incomplete players do not appear in final paired rankings.

## Commands

```bash
# See player availability without loading weights
./benchmark --game all --list

# Compare a few players on identical courses
./benchmark --game dino,flappy --players jev greedy oracle --games 10 --seed 42

# All games, using only their baselines
./benchmark --game all --players baselines --games 5 --max-plies 100

# Every available model and each game's baselines
./benchmark --game all --players all --games 5

# Unaided model controls, saved separately from assisted runs
./benchmark --game flappy --players jev greedy --control raw --games 10

# A seed-by-seed competition
./benchmark --game sudoku --players jev random greedy oracle --format versus --games 20

# Pairwise competition (Chess always plays real matches in both colors)
./benchmark --game 2048 --players laya jev greedy --format round-robin --games 10
./benchmark --game chess --players jev greedy random --rounds 2 --max-plies 150

# Exports also work with --no-save
./benchmark --quick --json results/quick.json --csv results/quick.csv
./benchmark --quick --plain --no-save
```

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--game` | `2048` | A game, comma-separated games, or `all` |
| `--players` | `all` | Space-separated ids, `all`, or `baselines` |
| `--games` | `5` | Seeded runs per player; `--quick` defaults to 3 |
| `--seed` | `0` | Run *i* uses seed `seed + i` for every player |
| `--control` | `assisted` | `assisted` or `raw` for Dino/Flappy models |
| `--format` | `average` | `average`, `versus`, `round-robin` |
| `--rounds` | `1` | Chess games per pair **per color** |
| `--max-plies` | `200` | Chess draw cutoff |
| `--quick` | off | Dino + Flappy with baselines, no questions |
| `--list` | off | Player availability, no weights loaded |
| `--plain` | off | Line-based console output |
| `--fail-fast` | off | Stop on the first failed player/match |
| `--no-save` | off | Do not append to `bench_runs.jsonl` |
| `--json PATH` | none | Full run metadata, checkpoints, result rows and status |
| `--csv PATH` | none | Result rows; lists/dicts are JSON inside CSV cells |

Player ids: `laya`, `jev`, `drex`, `kev`, `gliner`, `bev`, `dm`. Each game also has `random` and
`greedy`; Dino, Flappy and Sudoku have `oracle`. Missing or unconfigured players are skipped
with a reason. An error while playing excludes that player's incomplete seed set, prints the error,
and continues the others. A partial or empty run returns exit status 1; success returns 0.
Counts must be positive; invalid games and player names return a CLI error.

## What the formats mean

- **average:** compare mean score over the same seeds; spread statistics show consistency.
- **versus:** the best score on each seed wins; ties split that seed. Rank by win share.
- **round-robin:** compare every pair seed by seed, with win = 1 and draw = ½. The matrix shows
  row-player W-D-L against the column player. Chess plays actual matches instead, alternating colors.

A multi-game suite turns each game's result into 0–100 points (`average`: relative to that game's
best mean; `versus`: win share; `round-robin`: points rate), then averages them. A player missing
from a game is averaged over only the games it played; the per-game columns expose this. Do not
interpret a one-game oracle's overall score as a fair five-game comparison to a model in all games.

## Fair courses and assisted control

The environment has its own seeded RNG; randomized policies use a separate reproducible stream.
Browser and CLI Dino/Flappy use the **same Python engines**. Their results record `arcade-v2` and
control mode, while older results remain identifiable as earlier mechanics. Caps are 100 obstacles
or pipes and 2400 ticks. Baselines always use their own policy in either control mode.

**Assisted Dino:** coasts on empty track and filters immediately fatal controls. The model times
nearby obstacles with jump momentum and real collision bounds. Idle/forced ticks skip the model.

**Assisted Flappy:** the model ranks three-tick flight paths. A physics helper filters paths that
collide or leave no reachable continuation through visible pipe gaps; future spawns are unknown.
Only the first control is applied before replanning. This measures the model with assistance,
not unaided motor control. **Raw** mode removes these guards and asks every tick. Compare the
modes separately. Saved rows include average decisions, model calls, and ms/decision; the latter
includes local policy work and excludes browser playback delays.

## Saved results

Each run has an id, parameters, versions, control mode, seed range, per-player raw scores,
summary statistics and final status in `bench_runs.jsonl`. Completed player checkpoints survive
interruption. Final rows replace checkpoints in the browser display. Chess saves every match plus
per-player standings. These are separate from Arena scores and decision traces.

Start `python server.py`, then open **http://localhost:8048/benchmarks** to inspect runs.
The same data is at `GET /api/benchmarks` and `GET /api/benchmarks/<run_id>`.

The older commands (`bench.py`, `bench_dino.py`, `bench_flappy.py`, `bench_sudoku.py`,
`bench_chess.py`) keep their positional arguments and now delegate to this runner for progress,
availability checks and persistence. `bench.py` still includes Random and Greedy automatically.
Chess now plays both colors per pair. Use the unified CLI for exports and additional flags.
