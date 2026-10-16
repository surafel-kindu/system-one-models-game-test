"""Headless Dino Run benchmark: Laya / Jev / Drex / Kev / GLiNER2.5-Decide / Bev-Decider vs random vs the oracle.
Usage: python bench_dino.py [games] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [oracle]
"""
import sys, time
from enginedino import CORRECT, PLAYERS, get_player, play
from runs import Run

if __name__ == "__main__":
    from benchmark import main
    count = sys.argv[1] if len(sys.argv) > 1 else "5"
    players = sys.argv[2:] or ['laya', 'jev', 'random', 'greedy', 'oracle']
    raise SystemExit(main(["--game", "dino", "--games", count, "--players", *players]))
