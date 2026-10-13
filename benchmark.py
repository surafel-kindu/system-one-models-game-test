"""Headless benchmark runner: play any game(s) with any players, no server and no browser.

    python benchmark.py --game 2048 --players all --games 10
    python benchmark.py --game flappy --format versus --games 20 --players laya jev oracle
    python benchmark.py --game chess --format round-robin --rounds 2 --players laya jev greedy
    python benchmark.py --game all --games 5 --players all            # every game, overall leaderboard

Formats (see BENCHMARKING.md):
  average       every player plays the same N seeded games; compare mean / std / median / best / worst
  versus        all players in one group: on each seed the best score wins that seed (ties share it)
  round-robin   every pair meets head-to-head (single-player games: seed by seed; chess: real games,
                both colors); W/D/L and points per pair
Every run is saved to bench_runs.jsonl (see runs.py) and shows up on the /benchmarks page.
"""
import argparse
import itertools
import random
import statistics
import sys
import time

import engine2048
import enginechess
import enginedino
import engineflappy
import enginesudoku
from bench import play as play_2048
from runs import Run

MODELS = ["laya", "jev", "drex", "kev", "gliner", "bev", "dm"]
MODS = {"2048": engine2048, "dino": enginedino, "flappy": engineflappy, "sudoku": enginesudoku, "chess": enginechess}
FORMATS = ("average", "versus", "round-robin")


# --- one game of a single-player title: (player, seed) -> (score, extra stats) ------------------------

def play_single(game, player, seed):
    p = MODS[game].get_player(player)
    pol = lambda s: p.decide(s)[0]
    if game == "2048":
        score, best, steps = play_2048(pol, seed)
        return score, {"best_tile": best, "moves": steps}
    if game == "dino":
        score, cleared = enginedino.play(pol, rng=random.Random(seed))
        return score, {"cleared": cleared}
    if game == "flappy":
        score, pipes, why = engineflappy.play(pol, rng=random.Random(seed))
        return score, {"pipes": pipes, "died_on": why}
    score, correct, mistakes, result, _steps = enginesudoku.play(p, seed)
    return score, {"correct": correct, "mistakes": mistakes, "solved": result == "solved"}


def collect(game, players, n, seed0, log):
    """scores[player] = [score per seed]; extras[player] = [extra dict per seed]. Same seeds for all."""
    scores, extras, secs = {}, {}, {}
    for name in players:
        t, scores[name], extras[name] = time.time(), [], []
        for seed in range(seed0, seed0 + n):
            s, x = play_single(game, name, seed)
            scores[name].append(s); extras[name].append(x)
        secs[name] = round(time.time() - t)
        log(f"  {name:7s} done  mean {statistics.mean(scores[name]):8.1f}  ({secs[name]}s)")
    return scores, extras, secs


# --- formats -------------------------------------------------------------------------------------------

def stats(vals):
    return {"mean": statistics.mean(vals), "std": statistics.pstdev(vals), "median": statistics.median(vals),
            "min": min(vals), "max": max(vals)}


def versus_table(scores):
    """Per-seed winner among ALL players; a tie splits the seed. -> {player: win share 0..1}"""
    names, n = list(scores), len(next(iter(scores.values())))
    share = dict.fromkeys(names, 0.0)
    for i in range(n):
        top = max(scores[p][i] for p in names)
        winners = [p for p in names if scores[p][i] == top]
        for p in winners:
            share[p] += 1 / len(winners) / n
    return share


def pair_record(scores, a, b):
    """a vs b over the shared seeds -> (wins, draws, losses) for a."""
    w = sum(x > y for x, y in zip(scores[a], scores[b]))
    d = sum(x == y for x, y in zip(scores[a], scores[b]))
    return w, d, len(scores[a]) - w - d


def chess_round_robin(players, rounds, max_plies, log):
    """Every pair plays `rounds` times per color assignment. -> (per-game rows, per-player W/D/L)."""
    pol = {n: (lambda board, p=enginechess.get_player(n): p.decide(board)[0]) for n in players}
    rec = {n: {"w": 0, "l": 0, "d": 0} for n in players}
    rows = []
    for a, b in itertools.combinations(players, 2):
        for r in range(rounds):
            for white, black in ((a, b), (b, a)):
                result, reason, plies = enginechess.play(pol[white], pol[black], max_plies=max_plies)
                winner = {"1-0": white, "0-1": black}.get(result)
                if winner:
                    rec[winner]["w"] += 1; rec[black if winner == white else white]["l"] += 1
                else:
                    rec[white]["d"] += 1; rec[black]["d"] += 1
                rows.append({"white": white, "black": black, "result": result, "reason": reason, "plies": plies, "winner": winner})
                log(f"  {white:7s} vs {black:7s}  {result:8s} {reason:22s} {plies} plies")
    return rows, rec


# --- per-game drivers: print a table, save to the run, return {player: 0..100 overall points} ------------

def table(headers, rows):
    w = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  ".join(str(x).ljust(w[i]) if i == 0 else str(x).rjust(w[i]) for i, x in enumerate(r))
    return "\n".join([line(headers), line(["-" * k for k in w])] + [line(r) for r in rows])


def run_single_game(game, fmt, players, n, seed0, run, log):
    log(f"\n== {game} · {fmt} · {n} seeded games × {len(players)} players ==")
    scores, extras, secs = collect(game, players, n, seed0, log)
    st = {p: stats(scores[p]) for p in players}
    order = sorted(players, key=lambda p: -st[p]["mean"])
    share = versus_table(scores)
    pairs = {(a, b): pair_record(scores, a, b) for a in players for b in players if a != b}
    pts = {p: sum(w + d / 2 for (a, _), (w, d, l) in pairs.items() if a == p) / (n * max(1, len(players) - 1)) for p in players}

    if fmt == "average":
        rows = [[p, f"{st[p]['mean']:.1f}", f"{st[p]['std']:.1f}", f"{st[p]['median']:.0f}", f"{st[p]['min']:.0f}", f"{st[p]['max']:.0f}"] for p in order]
        log(table(["player", "mean", "std", "median", "worst", "best"], rows))
        overall_key = {p: st[p]["mean"] for p in players}
    elif fmt == "versus":
        order = sorted(players, key=lambda p: -share[p])
        log(table(["player", "seeds won", "win share", "mean score"], [[p, f"{share[p] * n:.1f}/{n}", f"{share[p] * 100:.0f}%", f"{st[p]['mean']:.1f}"] for p in order]))
        overall_key = share
    else:
        order = sorted(players, key=lambda p: -pts[p])
        log(table(["player", "points", "rate"] + [q[:7] for q in order],
                  [[p, f"{pts[p] * n * (len(players) - 1):.1f}", f"{pts[p] * 100:.0f}%"] + ["·" if p == q else "{}-{}-{}".format(*pair_record(scores, p, q)) for q in order] for p in order]))
        log("  (matrix cells are W-D-L of the row player against the column player)")
        overall_key = pts

    extra_keys = {k for x in extras[players[0]] for k in x if isinstance(x[k], (int, float))}
    for p in players:
        mean = lambda k: statistics.mean(float(x[k]) for x in extras[p] if k in x)
        run.result(p, game=game, format=fmt, games=n, avg_score=st[p]["mean"], std=st[p]["std"], median=st[p]["median"],
                   min=st[p]["min"], max=st[p]["max"], win_share=share[p], points_rate=pts[p], seconds=secs[p],
                   scores=scores[p], **{f"avg_{k}": mean(k) for k in sorted(extra_keys)})
    top = max(overall_key.values()) or 1
    bounded = fmt != "average"   # win share / points rate are already 0..1; scores are relative to the best
    return {p: (overall_key[p] * 100 if bounded else overall_key[p] / top * 100) for p in players}


def run_chess(fmt, players, rounds, max_plies, run, log):
    log(f"\n== chess · round-robin · {rounds} round(s), both colors, {max_plies}-ply cap ==")
    if fmt != "round-robin":
        log(f"  (chess is two-player, so '{fmt}' plays as round-robin)")
    t = time.time()
    rows, rec = chess_round_robin(players, rounds, max_plies, log)
    for r in rows:
        run.result(r["white"], game="chess", vs=r["black"], result=r["result"], reason=r["reason"], plies=r["plies"], winner=r["winner"])
    pts = {p: rec[p]["w"] + rec[p]["d"] / 2 for p in players}
    played = {p: rec[p]["w"] + rec[p]["l"] + rec[p]["d"] for p in players}
    order = sorted(players, key=lambda p: -pts[p])
    log(table(["player", "W", "D", "L", "points", "rate"], [[p, rec[p]["w"], rec[p]["d"], rec[p]["l"], f"{pts[p]:.1f}", f"{pts[p] / max(1, played[p]) * 100:.0f}%"] for p in order]))
    for p in players:
        run.result(p, game="chess", summary=True, wins=rec[p]["w"], losses=rec[p]["l"], draws=rec[p]["d"],
                   points_rate=pts[p] / max(1, played[p]), seconds=round(time.time() - t))
    return {p: pts[p] / max(1, played[p]) * 100 for p in players}


# --- CLI -------------------------------------------------------------------------------------------------

def resolve_players(names, game):
    """'all' = every model + every baseline this game has; unavailable players are skipped with a note."""
    mod = MODS[game]
    wanted = list(mod.PLAYERS) if names == ["all"] else names
    out = []
    for n in wanted:
        if n not in mod.PLAYERS:
            if names != ["all"]:
                print(f"  note: {game} has no player '{n}' — skipped", file=sys.stderr)
            continue
        ok, why = mod.PLAYERS[n].availability()
        if ok:
            out.append(n)
        else:
            print(f"  note: {game}/{n} unavailable ({why}) — skipped", file=sys.stderr)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--game", default="2048", help="2048 | dino | flappy | sudoku | chess | a comma list | all")
    ap.add_argument("--players", nargs="+", default=["all"], help="player ids, or 'all' (default)")
    ap.add_argument("--format", choices=FORMATS, default="average")
    ap.add_argument("--games", type=int, default=5, help="seeded games per player (single-player games)")
    ap.add_argument("--rounds", type=int, default=1, help="chess: games per pair per color")
    ap.add_argument("--max-plies", type=int, default=200, help="chess ply cap")
    ap.add_argument("--seed", type=int, default=0, help="first seed; game i uses seed+i for every player")
    ap.add_argument("--no-save", action="store_true", help="don't write to bench_runs.jsonl")
    a = ap.parse_args(argv)

    games = list(MODS) if a.game == "all" else [g.strip() for g in a.game.split(",")]
    bad = [g for g in games if g not in MODS]
    if bad:
        ap.error(f"unknown game(s): {', '.join(bad)}")
    log = lambda s="": print(s, flush=True)
    multi = len(games) > 1
    run = Run("multi" if multi else games[0], save=not a.no_save, format=a.format, games=a.games, rounds=a.rounds, seed=a.seed,
              players=a.players, **({"suites": games} if multi else {}))
    log(f"run {run.id}")

    points = {}   # game -> {player: 0..100}
    for g in games:
        players = resolve_players(a.players, g)
        if len(players) < 2 and not (g != "chess" and a.format == "average" and players):
            log(f"\n== {g} == skipped: need at least 2 players for '{a.format}' (got {players})"); continue
        points[g] = (run_chess(a.format, players, a.rounds, a.max_plies, run, log) if g == "chess"
                     else run_single_game(g, a.format, players, a.games, a.seed, run, log))

    if multi and points:
        everyone = sorted({p for d in points.values() for p in d})
        overall = {p: statistics.mean(d[p] for d in points.values() if p in d) for p in everyone}
        order = sorted(everyone, key=lambda p: -overall[p])
        log("\n== overall leaderboard (mean of per-game 0-100 points; players missing from a game are averaged over the games they played) ==")
        log(table(["player", "overall"] + list(points), [[p, f"{overall[p]:.1f}"] + [f"{points[g][p]:.0f}" if p in points[g] else "–" for g in points] for p in order]))
        for p in everyone:
            run.result(p, game="overall", avg_score=overall[p], games=len(points), seconds=0,
                       per_game={g: points[g][p] for g in points if p in points[g]})
    log(f"\nsaved as run {run.id} — open /benchmarks" if not a.no_save else "")


if __name__ == "__main__":
    main()
