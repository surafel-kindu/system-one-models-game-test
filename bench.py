"""Headless 2048 benchmark: Laya / Jev / Drex / Kev / GLiNER2.5-Decide / Bev-Decider vs random vs greedy.
Usage: python bench.py [games] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [greedy]
"""
import random, sys, time
from engine2048 import *
from runs import Run

def play(policy, seed, cap=2000):
    rng = random.Random(seed); g = new_game(rng); score = steps = 0
    while steps < cap:
        m = policy(g)
        if not m: break
        g, gain = move(g, m); score += gain; g = spawn(g, rng); steps += 1
    return score, max(v for r in g for v in r), steps

rnd = lambda g: (lambda l: random.choice(l) if l else None)(legal(g))
def greedy(g):
    l = legal(g)
    return max(l, key=lambda m: (move(g, m)[1], sum(v == 0 for r in move(g, m)[0] for v in r))) if l else None

if __name__ == "__main__":
    from benchmark import main
    count = sys.argv[1] if len(sys.argv) > 1 else "5"
    players = sys.argv[2:] or ['laya', 'jev', 'random', 'greedy']
    players = list(dict.fromkeys(["random", "greedy"] + players))
    raise SystemExit(main(["--game", "2048", "--games", count, "--players", *players]))
