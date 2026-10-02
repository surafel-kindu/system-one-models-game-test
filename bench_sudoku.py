"""Headless Sudoku benchmark: models vs random / greedy / the oracle. Puzzle i is generated from seed i,
so every player solves the identical puzzles.
Usage: python bench_sudoku.py [games] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [greedy] [oracle]
"""
import sys, time
from enginesudoku import get_player, play
from runs import Run

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    which = sys.argv[2:] or ["laya", "jev", "random", "greedy", "oracle"]
    run = Run("sudoku", games=n, players=which)
    print(f"run {run.id}")
    for name in which:
        p = get_player(name)
        t = time.time()
        r = [play(p, seed) for seed in range(n)]
        solved = sum(x[3] == "solved" for x in r)
        run.result(name, games=n, avg_score=sum(x[0] for x in r)/n, solved=solved, avg_mistakes=sum(x[2] for x in r)/n,
                   avg_correct=sum(x[1] for x in r)/n, seconds=round(time.time()-t), scores=[x[0] for x in r])
        print(f"{name:7s} avg score {sum(x[0] for x in r)/n:6.1f}  solved {solved}/{n}  avg mistakes {sum(x[2] for x in r)/n:.2f}  "
              f"avg correct {sum(x[1] for x in r)/n:.1f}  {time.time()-t:.0f}s", flush=True)
