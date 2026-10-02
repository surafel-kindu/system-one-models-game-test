"""Headless Flappy Bird benchmark: models vs random / greedy / the oracle. Every run uses seeded pipes
(run i uses seed i for every player), so players face identical pipe sequences.
Usage: python bench_flappy.py [games] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [greedy] [oracle]
"""
import random, sys, time
from engineflappy import get_player, play
from runs import Run

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    which = sys.argv[2:] or ["laya", "jev", "random", "greedy", "oracle"]
    run = Run("flappy", games=n, players=which)
    print(f"run {run.id}")
    for name in which:
        p = get_player(name)
        pol = lambda s, p=p: p.decide(s)[0]
        t = time.time()
        r = [play(pol, rng=random.Random(i)) for i in range(n)]
        avg = sum(x[0] for x in r) / n
        run.result(name, games=n, avg_score=avg, pipes=[x[1] for x in r], died_on=[x[2] for x in r], seconds=round(time.time()-t), scores=[x[0] for x in r])
        print(f"{name:7s} avg score {avg:7.0f}  pipes {[x[1] for x in r]}  died on {[x[2] for x in r]}  {time.time()-t:.0f}s", flush=True)
