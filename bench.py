"""Headless 2048 benchmark: Laya / Jev / Drex / Kev / GLiNER2.5-Decide vs random vs greedy.
Usage: python bench.py [games] [laya] [jev] [drex] [kev] [gliner] [random] [greedy]
"""
import random, sys, time
from engine2048 import *

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
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    which = sys.argv[2:] or ["laya", "jev"]
    pol = {"random": rnd, "greedy": greedy}
    for w in which:
        if w in pol:
            continue
        p = get_player(w); pol[w] = (lambda p: lambda g: p.decide(g)[0])(p)
    for name, p in pol.items():
        t = time.time(); r = [play(p, s) for s in range(n)]
        print(f"{name:7s} avg score {sum(x[0] for x in r)/n:7.0f}  best tile {[x[1] for x in r]}  {time.time()-t:.0f}s", flush=True)
