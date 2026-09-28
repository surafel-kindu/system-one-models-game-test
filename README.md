# Arcade games played by small decision models

Three games where the moves are chosen by a small **System 1 decision model** instead of a search
algorithm or an LLM: **2048**, a **Chrome-dino-style runner**, and **Chess**. Each turn the
situation is described in text, the model picks one of the options, and you watch it happen in the
browser — alone (2048, Dino Run), many at once to compare players (all three), or head-to-head
(Chess: two models play *each other*).

Six models are supported (plus baseline players) and can be switched from the UI, in every game:

| Model | Package | Checkpoint | Size |
|---|---|---|---|
| **Laya** | [`laya`](https://pypi.org/project/laya/) | [`convaiinnovations/laya`](https://huggingface.co/convaiinnovations/laya) | ~420M |
| **Jev-BERTa** | [`jev-berta`](https://github.com/leobitz/jev-berta) | [`leobitz/jev-berta-base-zeroshot-classifier`](https://huggingface.co/leobitz/jev-berta-base-zeroshot-classifier) | ~198M |
| **Drex** | hosted API, [docs](https://drex.nace.ai/docs) | `drex-latest` (via `POST /v1/systemone`) | remote |
| **Kev-0.8B** | [github.com/jaredpalmer/kev](https://github.com/jaredpalmer/kev) (run yourself) | [`jaredpalmer/kev-0.8b`](https://huggingface.co/jaredpalmer/kev-0.8b) | ~0.8B |
| **GLiNER2.5-Decide** | [`gliner2`](https://pypi.org/project/gliner2/) | [`fastino/GLiNER2.5-Decide`](https://huggingface.co/fastino/GLiNER2.5-Decide) | ~340M |
| **Bev-Decider-0.4B** | [`bev-decider`](https://pypi.org/project/bev-decider/) | [`avbiswas/bev-decider-0.4B`](https://huggingface.co/avbiswas/bev-decider-0.4B) | ~0.4B |

Laya, Jev, GLiNER and Bev are local, non-generative classifiers: they score a list of candidate
answers against a context and return probabilities. None of the six was trained on any of these
games. Each is loaded **once** and shared between all three games (`models.py`), not duplicated
per game.

## Quick start

Requires Python 3.10+. The first run downloads both local checkpoints (a few minutes).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install laya chess gliner2 peft bev-decider git+https://github.com/leobitz/jev-berta.git
python server.py
```

Open <http://localhost:8048> — it redirects to the 2048 arena. Use the nav at the top of every
page to switch game (**2048** / **Dino Run** / **Chess**) and mode:

| | Arena (many games/matches at once) | The other mode |
|---|---|---|
| **2048** | `/2048` | `/2048/play` — one move at a time |
| **Dino Run** | `/dino` | `/dino/play` — one obstacle at a time |
| **Chess** | `/chess` — every pair plays each other | `/chess/play` — pick White and Black, one ply at a time |

There's also <http://localhost:8048/traces> — every model decision across all three games, with filters (see [Traces](#traces) below).

### Drex API key

Drex is a hosted API, so it needs a key (get one from the Drex dashboard). Copy `.env.example`
to `.env` and fill it in, then restart the server:

```bash
cp .env.example .env      # then set DREX_API_KEY=...
```

`.env` is git-ignored. Without a key, Drex appears greyed out with a hint and everything else works.
Optional: `DREX_MODEL` (default `drex-latest`) and `DREX_CONCURRENCY` (default 2, the free-tier limit; paid allows 16).
The client retries on 429/529 (honouring `retry-after-ms`). **Note:** state text is sent to Drex's servers.

### Kev (run it yourself)

Kev ([github.com/jaredpalmer/kev](https://github.com/jaredpalmer/kev)) is a small, openly-released
decision model you host and run locally — no hosted API, no key. It speaks the exact same
`/v1/systemone` contract as Drex, so `models.py`'s `KevBackend` is really a Drex client pointed at
`localhost` instead of a key. Two catches worth knowing before you set it up:

- The PyPI package literally named `kev` is **a different, unrelated project** (a boto3-based
  document store) — don't `pip install kev`. The real thing only exists as the GitHub repo above.
- Its `pyproject.toml` pins `torch>=2.6,<2.9`, which conflicts with this project's own torch (used
  by Laya/Jev). Give it a **separate venv**, not this project's `.venv`.
- The first run downloads a real checkpoint (the 0.8B base model + adapter), and Hugging Face's
  newer "Xet" CDN backend has repeatedly stalled at 0 bytes on large files here. Set
  `HF_HUB_DISABLE_XET=1` before running `kev.serve` (this project's own `.venv` sets it
  automatically for its own downloads — see Notes — but Kev's separate venv needs it set by hand).

```bash
git clone https://github.com/jaredpalmer/kev.git kev-repo && cd kev-repo
python3.13 -m venv .venv && source .venv/bin/activate   # a separate venv from this project's
pip install -e ".[serve]"                                # pulls in mlx-lm on Apple Silicon
HF_HUB_DISABLE_XET=1 python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009
```

Leave that running in its own terminal (first run downloads the base model + adapter), then back
in this project's server it's picked up automatically — `KevBackend.availability()` just checks
whether `127.0.0.1:8009` is reachable. No `.env` entry is needed unless you changed the port/host
or started the Kev server with `KEV_API_KEY` (see `.env.example` for `KEV_URL`/`KEV_API_KEY`/
`KEV_MODEL`/`KEV_CONCURRENCY`). Without it running, Kev just appears greyed out like an unconfigured
Drex.

## Running the benchmarks (headless, no browser)

Each game has a small script that plays many games with no server and no browser — the quickest
way to compare players. Run them from the activated venv, from this directory:

| Script | What it does | Default players (no names given) |
|---|---|---|
| `bench.py` | Plays 2048 to the end, N times per player | `random`, `greedy`, `laya`, `jev` |
| `bench_dino.py` | Plays Dino Run to a crash or the cap, N times per player | `laya`, `jev`, `random`, `oracle` |
| `bench_chess.py` | Every pair of the given players plays once, alternating colors | `greedy`, `random` |

```bash
python bench.py 8                    # 8 games each, default players
python bench.py 8 kev gliner bev     # 8 games each, only those three (random/greedy always included)
python bench_dino.py 5 gliner
python bench_chess.py 200 greedy random laya jev kev gliner bev   # every pair plays once, 200-ply cap
```

Player names: `laya`, `jev`, `drex`, `kev`, `gliner`, `bev`, plus each game's own baselines (`random` and
`greedy` for 2048/Chess; `random` and `oracle` for Dino). The first argument is always the game
count (2048/Dino) or the max-plies cutoff (Chess). Unlike the web UI, these scripts don't check
availability first — naming `drex` without `DREX_API_KEY` set, or `kev` without its server running,
raises an error immediately and stops the whole run rather than skipping just that player.

Results print as plain text to the terminal — nothing is written to disk. This is separate from
the Arena's saved `results_*.json` and the [Traces](#traces) log, which only capture games played
through the web UI.

## Arena: many games at once

Each game's Arena page runs several auto-play games (or, for Chess, matches) side by side and
compares players.

- **2048 / Dino Run:** tick the players to include and set **games per player**; every game runs
  in parallel with a live mini board/track. **2048** starts every board in a run — every player,
  every repeat — from the same two starting tiles (regenerated fresh on each **Start**), so a lucky
  or unlucky opening doesn't decide the comparison.
- **Chess:** tick 2+ players; every unordered pair plays **matches per pairing** games, alternating
  who's White, since color is a real advantage. There's no solo baseline run — it's inherently
  head-to-head.
- Tables update as games finish: **This run**, **All time (saved)**, and a top-10/recent-results list.
- Finished games are saved to `results_2048.json` / `results_dino.json` / `results_chess.json` on
  the server, so results survive restarts. **Stopped or unfinished games are not saved** — only a
  genuine finish (crash/checkmate/no legal move, or the move/obstacle/ply cap) is recorded. Delete
  a `results_*.json` file to reset it.
- ms/move (or ms/decision) is inflated when many games share one model, because calls to a model
  backend are queued (see Concurrency below). Use it as a rough comparison only.
- The player list comes from the server (`GET /api/<game>/models`), so a newly registered model
  shows up on that game's pages automatically, with no UI changes.

## 2048

```
browser (JS game)  --grid + model-->  server.py  -->  engine2048.py  -->  models.py  -->  Laya / Jev / Drex
        ^                                                                     |
        +----------------------------- chosen move --------------------------+
```

1. **Guarded candidates.** `engine2048.candidates()` lists the legal moves and removes any that
   would pull the biggest tile out of its corner, unless that's the only option.
2. **State text.** `engine2048.describe()` renders the board and one terse line per candidate, e.g.
   `- left: KEEPS corner, ordered, empty 11 chain 64|64|0|0 chain-merges 1 scattered-merges 1 CORNER-MERGE-READY`.
3. **Decision.** The model answers "which move?" as a multiple-choice question over the candidates.
4. The browser applies the move, spawns a tile, and asks again.

**Strategy given to the model:** keep the biggest tile in a corner, line up the next-biggest along
the edge, grow the tile beside the corner until it equals it, then merge. The corner rule is
enforced in code (step 1); the rest is only described in the prompt.

**Benchmark** (`python bench.py 8`, headless, seeded games, small sample, CPU only):

| Player | Avg score | Typical best tile |
|---|---|---|
| random | ~690–1150 | 32–128 |
| Laya | ~1160 | 32–256 |
| Jev-BERTa | ~925 | 32–128 |
| Kev-0.8B | ~950 | 32–256 |
| GLiNER2.5-Decide | ~940 | 64–128 |
| Bev-Decider-0.4B | ~925 | 32–128 |
| greedy (merge score, then empty cells) | ~3340 | 256 |

**Honest takeaway:** all six models play at roughly random level, with Laya and Kev perhaps
slightly ahead. They can't plan ahead, and richer prompts made them *worse* — offering all four
directions plus per-move lookahead text (no code-enforced rules) scored much lower (Laya ~790, Jev
~645) and made them pick illegal directions 10-20% of the time, so that mode was reverted. What
helps is enforcing rules in code. A trivial greedy heuristic beats all six, so treat this as a
demo of wiring decision
models into a loop, not as a strong 2048 agent.

## Dino Run

A Chrome-dino-style runner, simplified to one decision per obstacle instead of real-time reflexes
(the models are too slow — 0.1–0.5s — for a per-frame reaction game):

```
browser (JS game)  --state+obstacle+model-->  server.py  -->  enginedino.py  -->  models.py  -->  Laya / Jev / Drex
        ^                                                                             |
        +----------------------------------- chosen action ------------------------- +
```

1. **Obstacle.** The browser generates the next obstacle (weighted by difficulty, like 2048's tile
   spawns) and asks for an action: `jump`, `duck`, or `none`.
2. **State text** names the obstacle and describes what each action generally does, e.g.
   `Obstacle ahead: a bird flying low, at head height. After that: a cactus on the ground.`
3. **Decision.** The model answers "which action?" as a multiple-choice question.
4. **Resolution.** Exactly one action clears each obstacle type — any other is a crash, no partial credit:

   | Obstacle | Correct action |
   |---|---|
   | 🌵 cactus (ground) | `jump` |
   | 🐦 bird flying low (head height) | `duck` |
   | 🐦 bird flying high (overhead) | `none` (keep running) |

   The browser plays out the result (an approach animation, then a jump/duck/crash) and, on a
   crash or the 300-obstacle cap, reports the finished game.

**Baselines:** `random` (uniform over the three actions) and `oracle` (always the correct action —
an upper bound, since it never crashes and only stops at the 300-obstacle cap).

**Benchmark:** `python bench_dino.py 5` runs the same models headless, no animation.

**Honest takeaway on Kev-0.8B:** across 24 varied obstacles it answered `duck` 21 times regardless
of the obstacle shown — 3/24 (12.5%) correct, worse than random's expected 33%. Verified this
wasn't a code bug (2048 and Chess both get varied, sensible answers from the same backend): it's a
genuine bias of this specific checkpoint on this exact task, and Kev's own README says as much —
"Use Kev-0.8B when size matters more than accuracy."

**GLiNER2.5-Decide** is more interesting: across the same 24-sample test it correctly jumped every
cactus and ducked every low bird, but across 10/10 separate checks it **never once answered `none`**
— for a high bird it always ducks too, which is wrong. Net 18/24 (75%) correct, well above random's
33%, but the one obstacle needing "keep running" is a blind spot it never gets, which explains the
volatile 5-run benchmark (`cleared [30, 0, 0, 0, 6]`): a run survives as long as no high bird shows
up early, then ends the moment one does.

**Bev-Decider-0.4B** shows a clean, consistent one-notch-off pattern across the same 24-sample
test: it **never answers `jump`** (0/24) — a ground cactus always gets `duck` (wrong), a low bird
always gets `none` (wrong), and a high bird always gets `none` (correct, 6/6). Net 6/24 (25%),
close to random and worse than GLiNER; it seems to have learned "duck or run," never "jump."

## Chess

Real chess (via [`python-chess`](https://python-chess.readthedocs.io/)) — legal moves, castling,
en passant, promotion, check/checkmate and draw detection all apply. Unlike 2048/Dino, this game is
**adversarial**: two models play each other, alternating colors, so it's a genuinely different
architecture — see below.

```
browser (JS)  --{white, black}-->  server.py  --keeps the chess.Board per match-->  enginechess.py  -->  models.py  -->  Laya / Jev / Drex
     ^                                                                                    |
     +-------------------------------- move played this ply ---------------------------- +
```

- **Server-authoritative board.** 2048 and Dino Run mirror their (simple) rules in JS so the
  browser can apply moves itself. Chess's rules are too intricate to safely duplicate, so each
  match's `chess.Board` lives on the server (`server.py`'s `MATCHES`), and the browser just asks
  `POST /api/chess/matches/<id>/step` to play the next ply and render whatever FEN comes back.
- **Shortlisted candidates, like 2048's guarded mode.** A typical position has 20-40 legal moves;
  sending all of them (with a description each) risks blowing past the local models' ~512-token
  budget, and 2048 already showed that overwhelming the model with every option plays *worse* than
  a curated subset. `enginechess.shortlist()` ranks legal moves in code (captures by value, checks,
  checkmate, mild center pull, a small penalty for heading into a draw by repetition) and caps the
  list at 14 — the model still makes the final pick, just among good candidates rather than the
  full list. Two guards live purely in code, not the model's judgment: promoting to anything but a
  queen is never offered (it's legal but almost never correct, and just an extra way to blunder —
  the same "obviously-bad option, so don't offer it" idea as 2048's corner guard), and a move that
  would trigger a draw by repetition is deprioritized (not banned — genuine repetition, like
  perpetual check, is still available if nothing better exists). A busy midgame position runs ~300
  tokens total.
- **State text** names whose pieces are whose and which way they move, e.g. *"You are playing
  White; your pieces move up the board, toward rank 8. UPPERCASE = White, lowercase = Black"* — the
  full 8×8 grid follows, then each shortlisted move as `<SAN>: <tags>`, e.g. `Bxb5: captures pawn
  (+1), advances forward` or `O-O: castles kingside, king safety`.
- **Baselines:** `random` (uniform over *every* legal move, not just the shortlist) and `greedy`
  (always the top-ranked shortlisted move — captures/checks/center — no model involved).
- **On-board feedback:** while a side is deciding, the board shows a green dot on every candidate
  destination it's weighing (a red-ringed square instead if that candidate captures) — fetched via
  `GET /api/chess/matches/<id>/candidates`, which computes the shortlist without calling any model.
  The move actually played is then outlined; a checkmate outlines the whole board and the mated
  king's square in red. Both boards are 340px (Arena) / 600px (Match) so the Arena grid holds two
  per row.

**Benchmark:** `python bench_chess.py 200 greedy random laya jev kev gliner bev` plays every pair
once and prints a W/L/D tally (`200` = max plies before calling it a draw). No strong-play baseline is
included — building a real chess engine is out of scope here — so treat match results as "which
model reasons about a shortlisted position better than another," not absolute skill.

**Honest takeaway:** captures are real and render correctly (python-chess owns the rules; nothing
is faked), but "does it play with a strategy" has a mixed answer per model. Sampling 25 midgame
positions where a capture was available and code-ranked highest: **Jev-BERTa took it 24/25 times**,
**Greedy 25/25** (by construction), **random 2/25** (as expected), but **Laya took it only 6-9/25**
— it frequently passes on an objectively good, clearly-labeled capture. Left to play a full game,
Laya vs Jev tends to drift into repeated back-and-forth moves once material settles (now nudged
away from actual repetition by the shortlist penalty, but the underlying "no multi-move plan"
limitation remains) rather than building toward anything. **Kev-0.8B** was the pleasant surprise —
in one small run it beat Random by checkmate in 30 plies and drew Greedy — noticeably more coherent
here than in Dino Run, for whatever that's worth over such a small sample. **GLiNER2.5-Decide**
drew both Greedy (fivefold repetition) and Random (ply limit) in its own small run — competent
enough to avoid losing quickly, without forcing a decisive result either. **Bev-Decider-0.4B** also
drew both Greedy and Random on ply limits in its small run — like GLiNER, safe but not sharp here,
a contrast with its weaker Dino Run showing. Treat Chess like 2048 and Dino Run: a demo of wiring
decision models into a real, rules-correct game loop, not a strong chess engine.

## Traces

<http://localhost:8048/traces> logs and lets you browse **every** model decision, across all three
games, on its own page.

- **What's captured.** Each call to `/api/2048/decide`, `/api/dino/decide`, or a chess match's
  `/step` appends one record: `game`, `model`, a `game_id` (2048/Dino: a random id the browser
  mints per game/run and sends along; Chess: the match id), the exact request and response bodies,
  and latency. It's server-side, so it captures Arena runs too, not just the single-game pages.
- **Storage:** `traces.jsonl` — one JSON object per line, append-only, git-ignored. A request
  reads at most the last 20,000 lines, so a long session can't make the page slow.
- **Filters:** game, model, game id (partial match), and free-text search over the whole record
  (matches state text, a move, an error message, anything). Click a row to expand the full request
  and response JSON. **Live** (on by default) polls every 4 seconds.
- Errors are traced too (`response.error`), so it's a reasonable first stop when a model behaves
  oddly or a hosted call (Drex) fails.

## Concurrency

Local models (Laya, Jev) aren't safe to call concurrently, and Drex's free tier allows only 2
requests at once — `server.py` enforces this with one semaphore per backend, shared across all
three games (so 2048, Dino Run, and Chess arenas running at the same time still queue correctly
behind one Laya lock, not three).

## Files

| File | Purpose |
|---|---|
| `models.py` | Shared model backends (Laya/Jev/Drex), cached by name and reused by all games |
| `engine2048.py` | 2048 rules, state description, move filtering, model-backed players |
| `enginedino.py` | Dino Run rules, state description, model-backed players |
| `enginechess.py` | Chess rules (via `python-chess`), move shortlisting, state description, model-backed players |
| `server.py` | HTTP server: page routing per game/mode, `/api/<game>/{models,decide,results}`, plus chess's `/api/chess/matches[/​<id>/step]` |
| `arena_2048.html` / `play_2048.html` | 2048 arena and single-game pages |
| `arena_dino.html` / `play_dino.html` | Dino Run arena and single-game pages |
| `arena_chess.html` / `play_chess.html` | Chess arena (round-robin) and one-match pages |
| `style.css` | Shared design for all six pages |
| `.env.example` | Template for your API key (copy to `.env`) |
| `results_2048.json` / `results_dino.json` / `results_chess.json` | Saved arena results (created on first finish, git-ignored) |
| `bench.py` / `bench_dino.py` / `bench_chess.py` | Headless benchmarks against each game's baselines |

## Notes

- **Jev on CPU:** the checkpoint contains half-precision layers, so `JevBackend` casts it to float32.
- **Jev batch size:** `jev-berta` chunks how many (state, candidate) rows it encodes in one
  forward pass per `predict()` call — `JEV_BATCH_SIZE` in `.env` (default 4). Matters most for
  Chess, which can offer up to 14 choices in a single call.
- **Laya warning:** loading prints a warning that the checkpoint has out-of-range temperatures.
  Its confidence values are uncalibrated; the choice probabilities are still usable for choosing.
- **Chess with exactly one legal move:** Jev-BERTa's `predict()` raises if given fewer than two
  choices, which a forced-move position (common near checkmate) would otherwise hit. `enginechess.
  Player.decide()` plays a single legal move directly without calling any backend, same as
  2048/Dino's "only one option" shortcuts.
- **GLiNER's public API only returns the winning label's confidence**, not a full distribution —
  `gliner2`'s `classify_text` normally reports just the argmax. `GlinerBackend` gets the full
  distribution anyway by passing the documented `multi_label=True, cls_threshold=0.0,
  class_act="softmax"` classification kwargs: every label clears the zero threshold, so the "which
  labels passed" list ends up being all of them, each with its true softmax probability.
- **Bev-Decider's `decide()` isn't wrapped in an `"answers"` key** the way Laya's `system_one()` is
  — it returns `{question_id: {...}}` directly. `BevBackend` accounts for this; worth knowing if
  you compare the two APIs directly, since they otherwise look identical (same typed-question shape).
- **Hugging Face downloads:** `models.py` sets `HF_HUB_DISABLE_XET=1` by default (a real env var
  still overrides it). HF's newer "Xet" CDN backend has repeatedly stalled at 0 bytes on large
  checkpoints here (hit this with both Kev's and Bev-Decider's weights) while the classic HTTP path
  downloads fine. This only covers downloads inside this project's own process — Kev runs as its
  own separate server/venv, so its README documents setting the same variable there too.
- **Adding a model:** add a `Backend` subclass in `models.py` implementing `answer(state,
  instructions, criteria)`, register it in `BACKENDS`, then in each game's engine call
  `model_player("your_name")` and add it to that game's `PLAYERS`. It appears on both of that
  game's pages automatically. A backend can opt out at runtime via `availability()` (Drex does
  this when no key is set).
- **Adding a game:** write `engine<name>.py` with a `Player` base class, `model_player()` built on
  `models.get_backend`, a `PLAYERS` dict and `get_player()`; add it to `GAMES` in `server.py`; add
  `arena_<name>.html` / `play_<name>.html` styled with `style.css`, and a nav entry linking to the
  other pages. If the game is adversarial or otherwise needs rules too complex to trust to JS,
  follow Chess's pattern: keep the authoritative state server-side (see `server.py`'s `MATCHES`)
  instead of 2048/Dino's client-side rule mirroring.
