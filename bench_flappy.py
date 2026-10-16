"""Headless Flappy Bird benchmark: models vs random / greedy / the oracle. Every run uses seeded pipes
(run i uses seed i for every player), so players face identical pipe sequences.
Usage: python bench_flappy.py [games] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [greedy] [oracle]
"""
import random, sys, time
from engineflappy import get_player, play
from runs import Run

if __name__ == "__main__":
    from benchmark import main
    count = sys.argv[1] if len(sys.argv) > 1 else "5"
    players = sys.argv[2:] or ['laya', 'jev', 'random', 'greedy', 'oracle']
    raise SystemExit(main(["--game", "flappy", "--games", count, "--players", *players]))
