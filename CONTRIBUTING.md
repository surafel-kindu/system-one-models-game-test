# Contributing to Model Arcade

Contribute a model adapter, a reproducible console game, a browser game, or improvements to the benchmark website. A console-only game is welcome: a UI is optional.

The self-hosted website provides a visual guide at `/contribute`. Run it with `cd website && docker compose up --build -d`. See [website/README.md](website/README.md) for hosting and suggestion review.

## Propose an addition

Use the website's model/game suggestion form, or open a GitHub issue using the templates. Include a source URL, creator name/profile, description, license/access requirements, and reproducible setup or rules. Explain whether a game contribution includes console benchmarks, or both console and browser views.

A website suggestion is private to the host maintainer until its author chooses to open a public issue. Suggestions are reviewed; they do not install code or add models automatically.

## Add a model

1. Implement a backend in `models.py`, following `Backend`: `availability() -> (bool, reason)`, `answer(state, instructions, criteria) -> (chosen_id, probabilities)`. The criteria dictionary maps stable candidate IDs to descriptions; return IDs from that dictionary.
2. Keep model loading lazy and cached. Describe packages, hardware, checkpoint revision, credentials/access requirements, and supported concurrency. Do not include keys or weights in the repository.
3. Register it in `BACKENDS`. Dino, Flappy, Chess, and Sudoku generate model players from that registry. **2048 has explicit wrappers and a `PLAYERS` registry in `engine2048.py`; wire the model there too.**
4. Update `benchmark.py`'s `MODELS`, `website/catalog.py`, and README model documentation.
5. Verify legal choices, one-option situations, unavailable dependencies, error responses, and probability mapping. Explain any fallback policy or game assistance.
6. Compare against baselines using identical seeds. Include a result export, exact command, environment, model revision, and relevant tests in the PR.

## Add a console-only game

1. Add `engineyourgame.py` with rules, state description, stable legal-action IDs, scoring, terminal conditions, and a seeded environment RNG. Random policy choices should use a separate reproducible stream. Version mechanics with `VERSION`.
2. Provide model-backed players, availability checks, a `PLAYERS` registry, cached `get_player(name)`, a random baseline, and a meaningful heuristic baseline. Keep optional model dependencies lazy.
3. Register the engine in `benchmark.py`'s `MODS` and add an adapter in `play_single()`. Multiplayer games require a driver like `run_chess()`. Update CLI help and any supported metrics.
4. Use the shared run/checkpoint/result/status records and export path. Record useful game metrics, scores, seeds, control mode/version, model calls, and timing where applicable.
5. Test reproducibility, legal actions, scoring, and stopping conditions. Update the README and `website/catalog.py`. The website renders generic new-game statistics; customize `website/static/benchmarks.js` for extra columns.

After registering the game, replace `yourgame` below with its ID:

```bash
./benchmark --game yourgame --players random greedy \
  --games 10 --seed 42 --json website/benchmark-data/yourgame.json
```

A seeded engine, tests, documentation, and benchmark export form a useful contribution without a browser UI.

## Add a game with a browser UI

Complete the engine/console path first, then:

- Add validated create/step routes in `server.py`. Reuse Python rules as the source of truth, with session locking, model selection, trace records, and terminal handling.
- Add `play_yourgame.html` and `arena_yourgame.html`, plus explicit page/asset routes and game navigation.
- Reuse `arcade.css`. `arcade.js` currently handles only Dino/Flappy; provide a controller/renderer for a new game.
- Include step, autoplay/pause, reset, scores, model context, and probabilities. Arena comparisons should use the same environment seeds.
- Test pause/reset with requests in flight, errors, completed-result persistence, and responsive layouts. Playback speed must not change engine results.
- Add real screenshots and matching captions to the README.

## Verify and open a pull request

Fork this repository, clone your fork, and create a branch. Set up game dependencies as described in the root README. For website-only work, Docker Compose is sufficient.

```bash
git switch -c feat/your-contribution
.venv/bin/python -m unittest discover -s tests -v
./benchmark --quick --no-save --json website/benchmark-data/check.json

# For website changes:
cd website
docker compose up --build -d
docker compose run --rm --no-deps \
  -v "$PWD/tests:/app/tests:ro" web \
  python -m unittest discover -s tests -v
cd ..
```

Commit the relevant code, documentation, tests, and result exports, push to your fork, and open a PR against this repository's `main` branch. The PR template asks for the problem/resulting behavior, creator/license information, reproduction conditions, tests, and screenshots when relevant. Link an issue or suggestion reference if one exists.

Use explicit files with `git add`; check for credentials, local data, and model weights before committing. Keep raw/assisted and different engine versions distinguishable. Explain coverage gaps and limitations instead of presenting partial suites as equivalent comparisons.
