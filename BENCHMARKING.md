# Benchmarking (headless, no UI)

Run any game with any players straight from the terminal — no server, no browser. Every run is saved
to `bench_runs.jsonl` as one **run** and can be browsed at **http://localhost:8048/benchmarks** (start
the server with `python server.py`). Back to the [main README](README.md).

```bash
source .venv/bin/activate          # the venv has python-chess and the model packages
python benchmark.py --game 2048 --players laya jev random greedy --games 10
```

`benchmark.py` is the unified runner described here. The older per-game scripts (`bench.py`, `bench_dino.py`,
`bench_chess.py`, `bench_flappy.py`, `bench_sudoku.py`) still work and are documented in the README; they
run one simple comparison per game, while `benchmark.py` adds competition formats and multi-game suites.

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--game` | `2048` | `2048`, `dino`, `flappy`, `sudoku`, `chess`, a comma list (`2048,flappy`), or `all` |
| `--players` | `all` | Player ids (`laya jev drex kev gliner bev dm random greedy oracle`) or `all` |
| `--format` | `average` | `average`, `versus` or `round-robin` (see below) |
| `--games` | `5` | Seeded games per player (single-player games) |
| `--rounds` | `1` | Chess: games per pair, per color |
| `--max-plies` | `200` | Chess: ply cap (reaching it is a draw) |
| `--seed` | `0` | First seed; game *i* uses seed `seed + i` for **every** player |
| `--no-save` | off | Print only; don't write `bench_runs.jsonl` |

**Players.** `all` means every model plus the baselines that game has. Baselines differ per game:
`random`/`greedy` (2048, Chess), `random`/`oracle` (Dino), `random`/`greedy`/`oracle` (Flappy, Sudoku).
A player that is unavailable (e.g. `drex` without `DREX_API_KEY`, `kev` without its server running) or that
a game doesn't have is **skipped with a note**, not a crash — so `--game all --players all` just works.

**Fair comparison.** Seeds are shared: game *i* uses the same start board / pipe sequence / puzzle / obstacle
sequence for every player, so a lucky seed can't favor one model.

## Competition formats

### `average` — many games, take the mean (default)
Each player plays the same `--games` seeded games. Reports **mean, std, median, worst, best**. Use it to
rank players by typical performance and see how consistent they are.

```bash
python benchmark.py --game sudoku --players all --games 20
```

### `versus` — everyone in one group, win each seed
All players are in a single group; on each seed the **highest score wins that seed** (ties split it).
Reports seeds won, win share and mean score. Use it when you care about "who comes first" rather than by
how much — a single huge score can't dominate it the way it can a mean.

```bash
python benchmark.py --game flappy --format versus --games 30 --players laya jev greedy oracle
```

### `round-robin` — every pair head-to-head
Every pair of players meets directly and you get **W-D-L, points (win = 1, draw = ½) and a matrix** of
each player against every other.
- *Single-player games:* a pair is compared seed by seed (higher score wins that seed).
- *Chess:* real games. Each pair plays `--rounds` games **per color** (so `--rounds 2` = 4 games per pair),
  and a game that hits `--max-plies` is a draw.

```bash
python benchmark.py --game 2048 --format round-robin --games 10 --players laya jev gliner bev
python benchmark.py --game chess --rounds 2 --players laya jev greedy random --max-plies 150
```
(Chess is two-player, so any `--format` plays as round-robin.)

### Multi-game suite — all games, one overall leaderboard
Give several games (or `all`) and the runner plays each one in the chosen format, then ranks everyone
**overall**: each game turns into 0–100 points per player (`average`: mean score relative to the game's best;
`versus`: win share; `round-robin`: points rate), and the overall score is the mean across games. A player
missing from a game (not available / no such baseline) is averaged over only the games it played.

```bash
python benchmark.py --game all --players all --games 5                      # everything
python benchmark.py --game 2048,dino,flappy --format versus --games 10 --players laya jev oracle
```

## Output

```
== sudoku · round-robin · 6 seeded games × 3 players ==
player  points  rate  oracle  greedy  random
oracle    10.5   88%       ·   3-3-0   6-0-0
greedy     7.5   62%   0-3-3       ·   6-0-0
random     0.0    0%   0-0-6   0-0-6       ·
  (matrix cells are W-D-L of the row player against the column player)
```

Each run prints `run <id>`. Saved records hold per-player mean/std/median/min/max, win share, points rate,
the raw per-seed `scores`, and game extras (`avg_best_tile`, `avg_pipes`, `avg_cleared`, `avg_mistakes`,
`avg_solved`…); chess also stores every game (white, black, result, reason, plies). The data is available at
`GET /api/benchmarks` and `GET /api/benchmarks/<run_id>`.

## Tips

- **Timing:** hosted/large models are slow (Chess especially — up to 14 candidates per move). Start with
  `--games 3` or `--max-plies 60` to sanity-check, then scale up.
- **Reproduce a run:** reuse the same `--seed` and `--games`; the run's parameters are shown on the
  Benchmarks page.
- **Baseline sanity check:** `oracle` should top Dino/Flappy/Sudoku and `random` should sit at the bottom;
  if not, something is wrong with the setup, not the models.
- **Compare across days/models:** run with `--seed 0 --games 20` each time, then compare runs on the
  Benchmarks page.
