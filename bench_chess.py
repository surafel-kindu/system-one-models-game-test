"""Headless chess benchmark: every pair plays both colors.
Usage: python bench_chess.py [max_plies] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [greedy]
"""
import sys, time
from enginechess import get_player, play
from runs import Run

if __name__ == "__main__":
    from benchmark import main
    count = sys.argv[1] if len(sys.argv) > 1 else "200"
    players = sys.argv[2:] or ['greedy', 'random']
    raise SystemExit(main(["--game", "chess", "--max-plies", count, "--players", *players]))
