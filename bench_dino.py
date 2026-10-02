"""Headless Dino Run benchmark: Laya / Jev / Drex / Kev / GLiNER2.5-Decide / Bev-Decider vs random vs the oracle.
Usage: python bench_dino.py [games] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [oracle]
"""
import sys, time
from enginedino import CORRECT, PLAYERS, get_player, play

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    which = sys.argv[2:] or ["laya", "jev", "random", "oracle"]
    for name in which:
        p = get_player(name)
        pol = lambda s, p=p: p.decide(s)[0]
        t = time.time(); r = [play(pol) for _ in range(n)]
        avg = sum(x[0] for x in r) / n
        print(f"{name:7s} avg score {avg:7.0f}  cleared {[x[1] for x in r]}  {time.time()-t:.0f}s", flush=True)
