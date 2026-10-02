"""Headless chess benchmark: every pair among the given players plays once (alternating colors).
Usage: python bench_chess.py [max_plies] [laya] [jev] [drex] [kev] [gliner] [bev] [dm] [random] [greedy]
"""
import sys, time
from enginechess import get_player, play
from runs import Run

if __name__ == "__main__":
    max_plies = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    which = sys.argv[2:] or ["greedy", "random"]
    players = {n: get_player(n) for n in which}
    record = {n: {"w": 0, "l": 0, "d": 0} for n in which}
    run = Run("chess", max_plies=max_plies, players=which)
    print(f"run {run.id}")
    t = time.time()
    for i, a in enumerate(which):
        for b in which[i + 1:]:
            pol_a = lambda board, p=players[a]: p.decide(board)[0]
            pol_b = lambda board, p=players[b]: p.decide(board)[0]
            result, reason, plies = play(pol_a, pol_b, max_plies=max_plies)
            outcome = {"1-0": (a, b), "0-1": (b, a)}.get(result)
            if outcome:
                record[outcome[0]]["w"] += 1; record[outcome[1]]["l"] += 1
            else:
                record[a]["d"] += 1; record[b]["d"] += 1
            run.result(a, vs=b, result=result, reason=reason, plies=plies, winner=(outcome[0] if outcome else None))
            print(f"{a:7s} vs {b:7s}  {result:8s} {reason:22s} {plies} plies", flush=True)
    print(f"-- {time.time()-t:.0f}s --")
    for n, r in record.items():
        run.result(n, summary=True, wins=r['w'], losses=r['l'], draws=r['d'])
        print(f"{n:7s} W{r['w']} L{r['l']} D{r['d']}", flush=True)
