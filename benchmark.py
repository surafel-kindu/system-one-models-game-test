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
import csv
import json
from pathlib import Path
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
from benchmark_console import Console

MODELS = ["laya", "jev", "drex", "kev", "gliner", "bev", "dm"]
MODS = {"2048": engine2048, "dino": enginedino, "flappy": engineflappy, "sudoku": enginesudoku, "chess": enginechess}
FORMATS = ("average", "versus", "round-robin")


# --- one game of a single-player title: (player, seed) -> (score, extra stats) ------------------------

def play_single(game, player, seed, control="assisted", progress=None):
    # The environment and stochastic policy use separate, reproducible random streams.
    random.seed(seed)
    p = MODS[game].get_player(player)
    calls, decisions, elapsed = 0, 0, 0.0

    def policy(state):
        nonlocal calls, decisions, elapsed
        if progress:
            score = state.get("score", 0) if isinstance(state, dict) else 0
            progress(f"{game}/{player} · seed {seed} · step {decisions + 1} · score {score}")
        t0 = time.perf_counter()
        result = p.decide(state)
        elapsed += time.perf_counter() - t0
        decisions += 1
        meta = result[3] if game in ("dino", "flappy") and len(result) > 3 else {}
        calls += int(meta.get("model_called", not p.baseline))
        return result[0]

    if game == "2048":
        score, best, steps = play_2048(policy, seed)
        extra = {"best_tile": best, "moves": steps}
    elif game == "dino":
        score, cleared = enginedino.play(policy, rng=random.Random(seed), control=control)
        extra = {"cleared": cleared}
    elif game == "flappy":
        score, pipes, why = engineflappy.play(policy, rng=random.Random(seed), control=control)
        extra = {"pipes": pipes, "died_on": why}
    else:
        # Sudoku's runner needs the whole decision tuple rather than just the selected digit.
        class Tracked:
            def decide(self, state):
                nonlocal calls, decisions, elapsed
                if progress:
                    progress(f"sudoku/{player} · seed {seed} · decision {decisions + 1}")
                t0 = time.perf_counter(); result = p.decide(state)
                elapsed += time.perf_counter() - t0
                calls += int(not p.baseline); decisions += 1
                return result
        score, correct, mistakes, result, _steps = enginesudoku.play(Tracked(), seed)
        extra = {"correct": correct, "mistakes": mistakes, "solved": result == "solved"}
    return score, {**extra, "decisions": decisions, "model_calls": calls,
                   "ms_per_decision": elapsed * 1000 / max(1, decisions)}


def collect(game, players, n, seed0, log, control="assisted", fail_fast=False, run=None):
    scores, extras, secs = {}, {}, {}
    for name in players:
        t, values, details = time.monotonic(), [], []
        for seed in range(seed0, seed0 + n):
            log.phase(f"{game}/{name} · seed {seed} · loading player / starting game")
            try:
                score, extra = play_single(game, name, seed, control, log.tick)
            except Exception as error:
                if fail_fast:
                    raise
                log.errors.append(f"{game}/{name}: {error}")
                log(f"  ! {name}: {error} — excluded from this game's ranking (incomplete seeds)")
                log.done += n - len(values)
                break
            values.append(score); details.append(extra); log.advance()
            log(f"  ✓ {name:<9} seed {seed:<5} score {score:>6}  · {time.monotonic()-t:.1f}s elapsed")
        else:
            scores[name], extras[name], secs[name] = values, details, round(time.monotonic() - t, 2)
            if run:
                run.checkpoint(name, game=game, format=run.records[0]["params"]["format"], games=n,
                               avg_score=statistics.mean(values), scores=values, seconds=secs[name],
                               control=control, version=getattr(MODS[game], "VERSION", "original"),
                               **stats(values))
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


def chess_round_robin(players, rounds, max_plies, log, seed0=0, fail_fast=False):
    """Every pair plays `rounds` times per color assignment. -> (per-game rows, per-player W/D/L)."""
    pol = {}
    for name in players:
        log.phase(f"chess/{name} · loading player")
        try:
            p = enginechess.get_player(name)
            def policy(board, p=p, name=name):
                log.tick(f"chess/{name} · ply {board.ply() + 1}/{max_plies}")
                return p.decide(board)[0]
            pol[name] = policy
        except Exception as error:
            if fail_fast:
                raise
            log.errors.append(f"chess/{name}: {error}")
            log(f"  ! chess/{name}: {error} — skipped")
    players = list(pol)
    log.begin(len(players) * (len(players) - 1) * rounds)
    rec = {n: {"w": 0, "l": 0, "d": 0} for n in players}
    rows = []
    for a, b in itertools.combinations(players, 2):
        for r in range(rounds):
            for white, black in ((a, b), (b, a)):
                random.seed(seed0 + len(rows))
                log.phase(f"chess · {white} vs {black} · round {r + 1}")
                try:
                    result, reason, plies = enginechess.play(pol[white], pol[black], max_plies=max_plies)
                except Exception as error:
                    if fail_fast:
                        raise
                    log.errors.append(f"chess/{white}/{black}: {error}")
                    log(f"  ! {white} vs {black}: {error} — match excluded")
                    log.advance()
                    continue
                log.advance()
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


def run_single_game(game, fmt, players, n, seed0, run, log, control="assisted", fail_fast=False):
    log(f"\n== {game} · {fmt} · {n} seeded games × {len(players)} players ==")
    log.begin(n * len(players))
    scores, extras, secs = collect(game, players, n, seed0, log, control, fail_fast, run)
    players = list(scores)
    if not players:
        log("  No complete results for this game.")
        return {}
    st = {p: stats(scores[p]) for p in players}
    order = sorted(players, key=lambda p: -st[p]["mean"])
    share = versus_table(scores)
    pairs = {(a, b): pair_record(scores, a, b) for a in players for b in players if a != b}
    pts = {p: sum(w + d / 2 for (a, _), (w, d, l) in pairs.items() if a == p) / (n * max(1, len(players) - 1)) for p in players}

    if fmt == "average":
        rows = [[str(i + 1), p, "█" * max(0, round(st[p]['mean'] / max(1, max(x['mean'] for x in st.values())) * 12)), f"{st[p]['mean']:.1f}", f"{st[p]['std']:.1f}", f"{st[p]['median']:.0f}", f"{st[p]['min']:.0f}", f"{st[p]['max']:.0f}"] for i, p in enumerate(order)]
        log(table(["#", "player", "score", "mean", "std", "median", "worst", "best"], rows))
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
                   scores=scores[p], seeds=list(range(seed0, seed0+n)), control=control,
                   version=getattr(MODS[game], "VERSION", "original"),
                   died_on=[x["died_on"] for x in extras[p] if "died_on" in x],
                   **{f"avg_{k}": mean(k) for k in sorted(extra_keys)})
    top = max(overall_key.values()) or 1
    bounded = fmt != "average"   # win share / points rate are already 0..1; scores are relative to the best
    return {p: (overall_key[p] * 100 if bounded else overall_key[p] / top * 100) for p in players}


def run_chess(fmt, players, rounds, max_plies, run, log, seed0=0, fail_fast=False):
    log(f"\n== chess · round-robin · {rounds} round(s), both colors, {max_plies}-ply cap ==")
    if fmt != "round-robin":
        log(f"  (chess is two-player, so '{fmt}' plays as round-robin)")
    t = time.time()
    rows, rec = chess_round_robin(players, rounds, max_plies, log, seed0, fail_fast)
    players = list(rec)
    for r in rows:
        run.result(r["white"], game="chess", vs=r["black"], result=r["result"], reason=r["reason"], plies=r["plies"], winner=r["winner"])
    pts = {p: rec[p]["w"] + rec[p]["d"] / 2 for p in players}
    played = {p: rec[p]["w"] + rec[p]["l"] + rec[p]["d"] for p in players}
    order = sorted(players, key=lambda p: -pts[p])
    log(table(["player", "W", "D", "L", "points", "rate"], [[p, rec[p]["w"], rec[p]["d"], rec[p]["l"], f"{pts[p]:.1f}", f"{pts[p] / max(1, played[p]) * 100:.0f}%"] for p in order]))
    for p in players:
        run.result(p, game="chess", summary=True, wins=rec[p]["w"], losses=rec[p]["l"], draws=rec[p]["d"],
                   points_rate=pts[p] / max(1, played[p]), seconds=round(time.time() - t))
    return {p: pts[p] / played[p] * 100 for p in players if played[p]}


# --- CLI -------------------------------------------------------------------------------------------------

def resolve_players(names, game):
    """'all' = every model + every baseline this game has; unavailable players are skipped with a note."""
    mod = MODS[game]
    wanted = list(mod.PLAYERS) if names == ["all"] else ([n for n,p in mod.PLAYERS.items() if p.baseline] if names == ["baselines"] else list(dict.fromkeys(names)))
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


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def wizard():
    print("\nMODEL ARCADE / BENCHMARK\n")
    print("  1  Quick check     Dino + Flappy · baselines · 3 seeds")
    print("  2  Compare models  Dino + Flappy · choose players")
    print("  3  Full suite      All five games · choose players")
    choice = input("\nChoose a preset [1]: ").strip() or "1"
    if choice not in ("1", "2", "3"):
        raise ValueError("choose preset 1, 2, or 3")
    args = ["--game", "all" if choice == "3" else "dino,flappy"]
    players = "random greedy oracle" if choice == "1" else input("Players [laya jev greedy]: ").strip() or "laya jev greedy"
    args += ["--players", *players.split()]
    args += ["--games", input("Seeds per player [3]: ").strip() or "3"]
    mode = input("Control: assisted or raw [assisted]: ").strip() or "assisted"
    args += ["--control", mode]
    print("\nRepeat this run: python benchmark.py " + " ".join(args) + "\n")
    return args


def export_results(run, json_path=None, csv_path=None):
    if json_path:
        target = Path(json_path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"run_id": run.id, "records": run.records}, indent=2) + "\n")
    if csv_path:
        rows = [r for r in run.records if r["type"] == "result"]
        finished = {(r.get("game"), r.get("player")) for r in rows}
        rows += [r for r in run.records if r["type"] == "checkpoint" and (r.get("game"), r.get("player")) not in finished]
        columns = list(dict.fromkeys(k for row in rows for k in row))
        target = Path(csv_path); target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k,v in row.items()} for row in rows)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if (not argv and sys.stdin.isatty()) or "--interactive" in argv:
        try:
            argv = wizard()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled."); return 130
        except ValueError as error:
            print(str(error), file=sys.stderr); return 2
    ap = argparse.ArgumentParser(description="Model Arcade benchmarks — live progress, seeded comparisons, saved leaderboards.")
    ap.add_argument("--game", default="2048", help="2048, dino, flappy, sudoku, chess, comma list, or all")
    ap.add_argument("--players", nargs="+", default=["all"], help="player ids, baselines, or all")
    ap.add_argument("--format", choices=FORMATS, default="average")
    ap.add_argument("--games", type=positive, default=5)
    ap.add_argument("--rounds", type=positive, default=1, help="chess games per pair per color")
    ap.add_argument("--max-plies", type=positive, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--control", choices=("assisted", "raw"), default="assisted", help="Dino/Flappy model control; baselines keep their own policies")
    ap.add_argument("--quick", action="store_true", help="3 seeds of Dino + Flappy, baselines only")
    ap.add_argument("--list", action="store_true", help="list games, players and availability without loading weights")
    ap.add_argument("--plain", action="store_true", help="disable live terminal rendering")
    ap.add_argument("--fail-fast", action="store_true", help="stop on first player error instead of excluding incomplete results")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--json", metavar="PATH", help="export complete run records as JSON")
    ap.add_argument("--csv", metavar="PATH", help="export result rows as CSV")
    args = ap.parse_args(argv)
    if args.quick:
        args.game, args.players = "dino,flappy", ["random", "greedy", "oracle"]
        if "--games" not in argv:
            args.games = 3
    games = list(MODS) if args.game == "all" else list(dict.fromkeys(g.strip() for g in args.game.split(",")))
    bad = [g for g in games if g not in MODS]
    if bad:
        ap.error(f"unknown game(s): {', '.join(bad)}")
    if args.list:
        for game in games:
            print(f"\n{game}")
            for name,p in MODS[game].PLAYERS.items():
                ok, reason = p.availability()
                print(f"  {name:<9} {p.label:<24} {'ready' if ok else 'unavailable: ' + reason}")
        return 0
    for name in args.players:
        if name not in ("all", "baselines") and not any(name in mod.PLAYERS for mod in MODS.values()):
            ap.error(f"unknown player: {name}")
    run = Run("multi" if len(games)>1 else games[0], save=not args.no_save, format=args.format,
              games=args.games, rounds=args.rounds, max_plies=args.max_plies, seed=args.seed,
              players=args.players, control=args.control, versions={g:getattr(MODS[g], "VERSION", "original") for g in games},
              **({"suites": games} if len(games)>1 else {}))
    result_code, status, points = 0, "complete", {}
    started = time.monotonic()
    try:
        with Console(args.plain) as log:
            log.heading("MODEL ARCADE / BENCHMARK")
            log(f"  Run {run.id} · {args.format} · {args.control} control")
            log(f"  Games: {', '.join(games)} · {args.games} seeds from {args.seed}")
            log("  First use of a local model may take time to load its weights. Ctrl+C stops safely.")
            for game in games:
                players = resolve_players(args.players, game)
                if len(players)<2 and not (game!="chess" and args.format=="average" and players):
                    log(f"  {game}: not enough available players — skipped"); continue
                scores = (run_chess(args.format, players, args.rounds, args.max_plies, run, log, args.seed, args.fail_fast)
                          if game=="chess" else run_single_game(game, args.format, players, args.games, args.seed, run, log, args.control, args.fail_fast))
                if scores:
                    points[game] = scores
            if len(games)>1 and points:
                everyone = sorted({p for d in points.values() for p in d})
                overall = {p:statistics.mean(d[p] for d in points.values() if p in d) for p in everyone}
                order = sorted(everyone, key=lambda p:-overall[p])
                log.heading("OVERALL LEADERBOARD · mean of per-game 0–100 points")
                log(table(["#", "player", "overall"] + list(points), [[i+1,p,f"{overall[p]:.1f}"]+[f"{points[g][p]:.0f}" if p in points[g] else "–" for g in points] for i,p in enumerate(order)]))
                log("  Missing games are excluded from a player's mean; baselines use their own policies.")
                for p in everyone:
                    run.result(p, game="overall", avg_score=overall[p], games=sum(p in d for d in points.values()), seconds=0,
                               per_game={g:points[g][p] for g in points if p in points[g]})
            if log.errors:
                status, result_code = "partial", 1
                log(f"  {len(log.errors)} player/match error(s); incomplete results were excluded.")
            if not points:
                status, result_code = "empty", 1
                log("  No complete games were available to rank.")
            log(f"\n  Finished in {time.monotonic()-started:.1f}s · {len(points)}/{len(games)} games ranked")
    except KeyboardInterrupt:
        status, result_code = "interrupted", 130
        print("\nInterrupted. Completed player results are preserved.")
    except Exception as error:
        status, result_code = "failed", 1
        print(f"\nBenchmark failed: {error}", file=sys.stderr)
    finally:
        run.finish(status)
        export_results(run, args.json, args.csv)
        if not args.no_save:
            print(f"Results: http://localhost:8048/benchmarks · run {run.id}")
        if args.json:
            print(f"JSON: {args.json}")
        if args.csv:
            print(f"CSV: {args.csv}")
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
