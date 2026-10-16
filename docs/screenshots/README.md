# README screenshots

Captured from the real local app on 2026-10-16 at a 1280 px desktop viewport. Full-page JPEGs preserve the complete browser content. Game seeds, actions, probabilities, scores, and timing are real; timing varies with hardware and concurrency.

| Image | Page | How to reproduce the view |
|---|---|---|
| [flappy-decision.jpg](flappy-decision.jpg) | `/flappy/play` | Choose Jev-BERTa, Assisted, seed 42. Auto-play, pause after a few pipes, then expand the model context. |
| [dino-arena.jpg](dino-arena.jpg) | `/dino` | Choose Jev-BERTa, Greedy, and Oracle; one run each; Assisted; seed 42. Start and capture the live comparison before stopping. |
| [2048-decision.jpg](2048-decision.jpg) | `/2048/play` | Choose Jev-BERTa. Auto-play until several tiles have merged, then pause with a decision and its probabilities visible. |
| [chess-match.jpg](chess-match.jpg) | `/chess/play` | Choose Greedy as White and Jev-BERTa as Black. Auto-play, pause after development/captures, and retain the move context and history. |
| [sudoku-decision.jpg](sudoku-decision.jpg) | `/sudoku/play` | Choose Jev-BERTa, wait for the new puzzle to load, then use One step. Capture a model placement with the grid, highlighted target, probabilities, and state text. The pictured run has two earlier mistakes. |
| [benchmark-results.jpg](benchmark-results.jpg) | `/benchmarks` | Run the CLI command below without --no-save. Select that completed run; show overall and both per-game tables. |
| [decision-traces.jpg](decision-traces.jpg) | `/traces` | Filter Game to flappy and Model to Jev-BERTa; set Limit to 3, turn Live off, refresh, and expand one trace. |

The arcade examples use **assisted** control. Its collision/flight-planning helpers are described in the main README; do not interpret assisted scores as unaided model skill. The Dino screenshot shows players at different points on the same seeded course because inference speeds differ.

The 2048 and Sudoku pages create fresh random games, and a chess opening depends on the players’ choices. Repeating the UI steps reproduces the type of view, not necessarily the exact board pictured.

The 2048, Chess, and Sudoku captures include the shared arcade redesign used by both their single-game and arena pages. The gray boards, orange selection highlights, decision panels, and geometric headers match Dino Run and Flappy Bird.

## Recorded benchmark

```bash
./benchmark --game dino,flappy --players jev greedy oracle --games 1 --seed 42
```

The saved-results screenshot and [console transcript](benchmark-output.txt) come from the same completed run. It is a one-seed interface demonstration. Use more seeds and compare raw/assisted modes separately for performance analysis. Console progress is documented as recorded text; no native Terminal screenshot is included.

## Adding or replacing captures

Save browser screenshots as `.jpg`, preserve the full page or enough surrounding controls to explain the state, and keep API credentials, private terminal content, and unrelated windows out of captures. Update the matching caption in the main README when the visible state changes. Keep links relative so they render in GitHub and local checkouts.
