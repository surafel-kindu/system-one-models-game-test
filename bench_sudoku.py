"""Headless Sudoku benchmark: models vs random / greedy / the oracle. Puzzle i is generated from seed i,
so every player solves the identical puzzles.
Usage: python bench_sudoku.py [games] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [greedy] [oracle]
"""
import sys, time
from enginesudoku import get_player, play
from runs import Run

if __name__ == "__main__":
    from benchmark import main
    count = sys.argv[1] if len(sys.argv) > 1 else "5"
    players = sys.argv[2:] or ['laya', 'jev', 'random', 'greedy', 'oracle']
    raise SystemExit(main(["--game", "sudoku", "--games", count, "--players", *players]))
