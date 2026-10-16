"""Local Model Arcade HTTP server.

Pages: /<game>, /<game>/play, /benchmarks, /traces.
Common API: GET /api/<game>/{models,results}; POST /api/<game>/results.
2048: POST /api/2048/decide; legacy arcade /decide endpoints also remain available.
Dino/Flappy: POST /api/<game>/games, /games/<id>/step, /games/<id>/close.
Chess: POST /api/chess/matches, /matches/<id>/step; GET /matches/<id>/candidates.
Sudoku: POST /api/sudoku/games, /games/<id>/step.
GET /api/traces and /api/benchmarks[/<run_id>] expose the local logs.
Dino/Flappy save a result once on genuine completion; closed/unfinished sessions are not saved.
"""
import contextlib
import json
import os
import random
from pathlib import Path
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import chess

import engine2048
import enginechess
import enginedino
import engineflappy
import enginesudoku
from models import get_backend
from runs import load_runs

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = {"2048": engine2048, "dino": enginedino, "chess": enginechess, "flappy": engineflappy,
         "sudoku": enginesudoku}
RESULTS = {g: os.path.join(HERE, f"results_{g}.json") for g in GAMES}
PAGES = {
    ("2048", "arena"): "arena_2048.html", ("2048", "play"): "play_2048.html",
    ("dino", "arena"): "arena_dino.html", ("dino", "play"): "play_dino.html",
    ("chess", "arena"): "arena_chess.html", ("chess", "play"): "play_chess.html",
    ("flappy", "arena"): "arena_flappy.html", ("flappy", "play"): "play_flappy.html",
    ("sudoku", "arena"): "arena_sudoku.html", ("sudoku", "play"): "play_sudoku.html",
}
_res_lock = threading.Lock()
MATCHES = {}  # chess match_id -> {board, white, black, history, lock}
ARCADE = {}  # bounded, server-authoritative Dino/Flappy sessions
SUDOKU = {}   # sudoku game_id -> {game, model, lock}
_matches_lock = threading.Lock()

# Every model decision (2048/Dino's /decide, Chess's /step) is appended here as one JSON line:
# the exact request and response, plus game/model/game_id for the /traces page's filters.
TRACES_FILE = os.path.join(HERE, "traces.jsonl")
MAX_TRACE_LINES = 20000  # tail-read cap so a long-running session's log can't blow up a request
_trace_lock = threading.Lock()


def log_trace(game, model, game_id, request, response, latency_ms):
    rec = {"id": uuid.uuid4().hex[:12], "ts": int(time.time() * 1000), "game": game, "game_id": game_id,
           "model": model, "request": request, "response": response, "latency_ms": round(latency_ms)}
    with _trace_lock:
        with open(TRACES_FILE, "a") as f:
            f.write(json.dumps(rec) + "\n")


def read_traces(game=None, model=None, game_id=None, q=None, limit=200):
    try:
        with open(TRACES_FILE) as f:
            lines = f.readlines()[-MAX_TRACE_LINES:]
    except FileNotFoundError:
        lines = []
    qlow = q.lower() if q else None
    out = []
    for line in reversed(lines):  # newest first
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if game and rec.get("game") != game:
            continue
        if model and rec.get("model") != model:
            continue
        if game_id and game_id not in (rec.get("game_id") or ""):
            continue
        if qlow and qlow not in json.dumps(rec).lower():
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out

# Model backends (laya/jev/drex/kev) are shared across games (models.py caches by name), and torch
# models aren't safe to call concurrently. Baseline players (random/greedy/oracle) need no lock.
BACKEND_IDS = ("laya", "jev", "drex", "kev", "gliner", "bev", "dm")
_slots = {}
_slots_lock = threading.Lock()


def _slot(model):
    if model not in BACKEND_IDS:
        return contextlib.nullcontext()
    with _slots_lock:
        if model not in _slots:
            _slots[model] = threading.BoundedSemaphore(get_backend(model).max_concurrency)
        return _slots[model]


def load_results(game):
    try:
        with open(RESULTS[game]) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


class H(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json", code=200):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)

    def _page(self, name):
        self._send((Path(HERE) / name).read_bytes(), "text/html")

    def do_GET(self):
        path = self.path.split("?")[0]
        parts = [p for p in path.split("/") if p]
        if path == "/":
            self.send_response(302); self.send_header("Location", "/2048"); self.end_headers(); return
        if path in ("/arcade.css", "/arcade.js"):
            name = path[1:]
            return self._send((Path(HERE) / name).read_bytes(),
                              "text/css" if name.endswith("css") else "text/javascript")
        if path == "/style.css":
            return self._send((Path(HERE) / "style.css").read_bytes(), "text/css")
        if path == "/traces":
            return self._page("traces.html")
        if len(parts) == 2 and parts[0] == "api" and parts[1] == "traces":
            qs = parse_qs(urlsplit(self.path).query)
            get1 = lambda k: (qs.get(k) or [None])[0]
            limit = min(int(get1("limit") or 200), 1000)
            return self._send(read_traces(game=get1("game"), model=get1("model"),
                                           game_id=get1("game_id"), q=get1("q"), limit=limit))
        if len(parts) == 1 and parts[0] in GAMES:
            return self._page(PAGES[(parts[0], "arena")])
        if len(parts) == 2 and parts[0] in GAMES and parts[1] == "play":
            return self._page(PAGES[(parts[0], "play")])
        if path == "/benchmarks":
            return self._page("benchmarks.html")
        if parts[:2] == ["api", "benchmarks"]:
            runs = load_runs()
            if len(parts) == 3:
                run = next((r for r in runs if r["run_id"] == parts[2]), None)
                return self._send(run) if run else self.send_error(404)
            return self._send([{**r, "results": len(r["results"])} for r in runs])
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "chess" and parts[2] == "matches" and parts[4] == "candidates":
            return self._match_candidates(GAMES["chess"], parts[3])
        if len(parts) == 3 and parts[0] == "api" and parts[1] in GAMES:
            game, mod = parts[1], GAMES[parts[1]]
            if parts[2] == "models":
                out = []
                for n, p in mod.PLAYERS.items():
                    ok, why = p.availability()
                    out.append({"id": n, "label": p.label, "baseline": p.baseline, "available": ok, "reason": why})
                return self._send(out)
            if parts[2] == "results":
                with _res_lock:
                    return self._send(load_results(game))
        self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0]
        parts = [p for p in path.split("/") if p]
        if not (len(parts) >= 3 and parts[0] == "api" and parts[1] in GAMES):
            return self.send_error(404)
        game, mod = parts[1], GAMES[parts[1]]
        length = int(self.headers.get("Content-Length") or 0)  # /step is a bodyless POST
        try:
            req = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(req, dict):
                raise ValueError("expected a JSON object")
        except (ValueError, UnicodeDecodeError):
            return self._send({"error": "invalid JSON body"}, code=400)

        if game in ("dino", "flappy") and parts[2] == "games":
            if len(parts) == 3:
                return self._new_arcade(game, mod, req)
            if len(parts) == 5 and parts[4] in ("step", "close"):
                return self._step_arcade(game, mod, parts[3], close=parts[4] == "close")

        if game == "chess" and len(parts) == 3 and parts[2] == "matches":
            return self._new_match(mod, req)
        if game == "chess" and len(parts) == 5 and parts[2] == "matches" and parts[4] == "step":
            return self._step_match(mod, parts[3])
        if game == "sudoku" and len(parts) == 3 and parts[2] == "games":
            return self._new_sudoku(mod, req)
        if game == "sudoku" and len(parts) == 5 and parts[2] == "games" and parts[4] == "step":
            return self._step_sudoku(mod, parts[3])
        if len(parts) != 3:
            return self.send_error(404)

        if parts[2] == "results":
            if game == "chess":  # two models per game, not one
                if req.get("white") not in mod.PLAYERS or req.get("black") not in mod.PLAYERS:
                    return self._send({"error": "unknown model"}, code=400)
            elif req.get("model") not in mod.PLAYERS:
                return self._send({"error": "unknown model"}, code=400)
            rec = dict(req); rec["ts"] = int(time.time())
            with _res_lock:
                data = load_results(game); data.append(rec)
                with open(RESULTS[game], "w") as f:
                    json.dump(data, f)
            return self._send({"ok": True, "total": len(data)})

        if parts[2] == "decide":
            model = req.get("model")
            if model not in mod.PLAYERS:
                return self._send({"error": "unknown model"}, code=400)
            ok, why = mod.PLAYERS[model].availability()
            if not ok:
                return self._send({"error": why}, code=400)
            t0 = time.time()
            try:
                with _slot(model):
                    player = mod.get_player(model)
                    if game == "2048":
                        m, probs, state, illegal = player.decide(req["grid"])
                        payload = {"move": m, "probs": probs, "state": state, "illegal_pick": illegal}
                    elif game in ("dino", "flappy"):
                        a, probs, state = player.decide(req["state"])[:3]
                        payload = {"action": a, "probs": probs, "state": state}
                    else:
                        return self._send({"error": f"{game} is driven through /games, not /decide"}, code=404)
            except Exception as e:  # e.g. hosted API failure: report it instead of dropping the connection
                log_trace(game, model, req.get("game_id"), req, {"error": str(e)}, (time.time() - t0) * 1000)
                return self._send({"error": str(e)}, code=502)
            log_trace(game, model, req.get("game_id"), req, payload, (time.time() - t0) * 1000)
            return self._send(payload)
        self.send_error(404)

    def _new_arcade(self, kind, mod, req):
        model, control = req.get("model"), req.get("control", "assisted")
        if model not in mod.PLAYERS or control not in ("assisted", "raw"):
            return self._send({"error": "choose a valid player and control mode"}, code=400)
        ok, why = mod.PLAYERS[model].availability()
        if not ok:
            return self._send({"error": why}, code=400)
        try:
            seed = int(req.get("seed", 0))
        except (TypeError, ValueError):
            return self._send({"error": "seed must be an integer"}, code=400)
        rng = random.Random(seed)
        gid = uuid.uuid4().hex[:12]
        entry = {"kind": kind, "model": model, "seed": seed, "control": control,
                 "rng": rng, "state": mod.new_game(rng, control), "over": False,
                 "decisions": 0, "model_calls": 0, "ms": 0, "lock": threading.Lock()}
        with _matches_lock:
            if len(ARCADE) >= 256:
                finished = next((i for i, e in ARCADE.items() if e["over"]), None)
                if finished:
                    del ARCADE[finished]
                else:
                    return self._send({"error": "too many active runs; stop an existing run first"}, code=429)
            ARCADE[gid] = entry
        return self._send({"game_id": gid, "seed": seed, "state": entry["state"], "over": False})

    def _step_arcade(self, kind, mod, gid, close=False):
        entry = ARCADE.get(gid)
        if not entry or entry["kind"] != kind:
            return self._send({"error": "unknown run; start a new game"}, code=404)
        with entry["lock"]:
            if close:
                with _matches_lock:
                    ARCADE.pop(gid, None)
                return self._send({"ok": True})
            if entry["over"]:
                return self._send(entry["last"])
            state, model = entry["state"], entry["model"]
            before = json.loads(json.dumps(state))
            t0 = time.perf_counter()
            try:
                with _slot(model):
                    decision = mod.get_player(model).decide(state)
                action, probs, text = decision[:3]
                meta = decision[3] if len(decision) > 3 else {"choice": action, "model_called": False}
                reason = mod.step_tick(state, action, entry["rng"])
            except Exception as e:
                log_trace(kind, model, gid, {"state": before}, {"error": str(e)}, (time.perf_counter() - t0) * 1000)
                return self._send({"error": str(e)}, code=502)
            elapsed = (time.perf_counter() - t0) * 1000
            entry["decisions"] += 1
            entry["model_calls"] += int(meta.get("model_called", False))
            entry["ms"] += elapsed
            passed = state.get("passed", state.get("cleared", 0))
            cap = mod.PIPE_CAP if kind == "flappy" else mod.OBSTACLE_CAP
            over = bool(reason) or passed >= cap or state["tick"] >= mod.TICK_CAP
            payload = {"game_id": gid, "state": state, "action": action, "probs": probs,
                       "prompt": text, "decision": meta, "latency_ms": round(elapsed), "over": over,
                       "reason": reason or ("cap" if over else None), "model_calls": entry["model_calls"],
                       "decisions": entry["decisions"]}
            if over:
                rec = {"model": model, "score": state["score"], "passed": passed, "cleared": passed,
                       "ticks": state["tick"], "seed": entry["seed"], "control": entry["control"],
                       "version": mod.VERSION, "model_calls": entry["model_calls"],
                       "ms_per_move": round(entry["ms"] / entry["decisions"]),
                       "crash_on": reason, "ts": int(time.time())}
                with _res_lock:
                    results = load_results(kind)
                    results.append(rec)
                    with open(RESULTS[kind], "w") as f:
                        json.dump(results, f)
                payload["result"] = rec
                entry["over"] = True
            # JSON snapshot: later ticks must not mutate the cached response.
            entry["last"] = json.loads(json.dumps(payload))
            log_trace(kind, model, gid, {"state": before, "control": entry["control"]},
                      {"action": action, "probs": probs, "state": text, "decision": meta,
                       "score": state["score"], "over": over}, elapsed)
            return self._send(payload)

    def _new_match(self, mod, req):
        white, black = req.get("white"), req.get("black")
        if white not in mod.PLAYERS or black not in mod.PLAYERS:
            return self._send({"error": "unknown model"}, code=400)
        for color, name in (("white", white), ("black", black)):
            ok, why = mod.PLAYERS[name].availability()
            if not ok:
                return self._send({"error": f"{color}: {why}"}, code=400)
        board = mod.new_game()
        mid = uuid.uuid4().hex[:12]
        with _matches_lock:
            MATCHES[mid] = {"board": board, "white": white, "black": black, "history": [], "lock": threading.Lock()}
        return self._send({"match_id": mid, "fen": board.fen(), "turn": "white", "over": False, "history": []})

    def _match_candidates(self, mod, mid):
        """The current shortlist, with no model call — lets the browser show 'thinking' hints
        (candidate destination squares) on the board before the actual decision comes back."""
        match = MATCHES.get(mid)
        if not match:
            return self._send({"error": "unknown match (server may have restarted)"}, code=404)
        board = match["board"]
        if board.is_game_over():
            return self._send({"moves": [], "turn": "white" if board.turn else "black"})
        moves = [{"uci": m.uci(), "from": chess.square_name(m.from_square),
                  "to": chess.square_name(m.to_square), "san": board.san(m), "capture": board.is_capture(m)}
                 for m in mod.shortlist(board)]
        return self._send({"moves": moves, "turn": "white" if board.turn else "black"})

    def _step_match(self, mod, mid):
        match = MATCHES.get(mid)
        if not match:
            return self._send({"error": "unknown match (server may have restarted)"}, code=404)
        with match["lock"]:
            board = match["board"]
            if board.is_game_over():
                result, reason = mod.outcome_info(board)
                mate_square = chess.square_name(board.king(board.turn)) if reason == "checkmate" else None
                return self._send({"over": True, "result": result, "reason": reason, "mate_square": mate_square,
                                    "fen": board.fen(), "turn": "white" if board.turn else "black",
                                    "history": match["history"]})
            mover = "white" if board.turn else "black"
            model = match[mover]
            trace_req = {"match_id": mid, "white": match["white"], "black": match["black"],
                         "by": mover, "fen_before": board.fen()}
            ok, why = mod.PLAYERS[model].availability()
            if not ok:
                return self._send({"error": f"{mover}: {why}"}, code=400)
            t0 = time.time()
            try:
                with _slot(model):
                    move_uci, probs, state = mod.get_player(model).decide(board)
            except Exception as e:
                log_trace("chess", model, mid, trace_req, {"error": str(e)}, (time.time() - t0) * 1000)
                return self._send({"error": str(e)}, code=502)
            move = chess.Move.from_uci(move_uci)
            san = board.san(move)
            board.push(move)
            match["history"].append(san)
            over = board.is_game_over()
            result, reason = mod.outcome_info(board) if over else (None, None)
            mate_square = chess.square_name(board.king(board.turn)) if reason == "checkmate" else None
            payload = {"move": move_uci, "san": san, "by": mover, "probs": probs, "state": state,
                       "fen": board.fen(), "turn": "white" if board.turn else "black",
                       "over": over, "result": result, "reason": reason, "mate_square": mate_square,
                       "ply": board.ply(), "history": match["history"]}
            log_trace("chess", model, mid, trace_req, payload, (time.time() - t0) * 1000)
            return self._send(payload)

    def _new_sudoku(self, mod, req):
        model = req.get("model")
        if model not in mod.PLAYERS:
            return self._send({"error": "unknown model"}, code=400)
        ok, why = mod.PLAYERS[model].availability()
        if not ok:
            return self._send({"error": why}, code=400)
        seed = req.get("seed")
        game = mod.new_game(int(seed) if seed is not None else None)
        gid = uuid.uuid4().hex[:12]
        with _matches_lock:
            SUDOKU[gid] = {"game": game, "model": model, "lock": threading.Lock()}
        return self._send({"game_id": gid, **mod.public(game)})

    def _step_sudoku(self, mod, gid):
        entry = SUDOKU.get(gid)
        if not entry:
            return self._send({"error": "unknown game (server may have restarted)"}, code=404)
        with entry["lock"]:
            game, model = entry["game"], entry["model"]
            if game["over"]:
                return self._send({"auto": [], "decision": None, **mod.public(game)})
            flat = "".join(str(v) for row in game["grid"] for v in row)
            trace_req = {"game_id": gid, "model": model, "seed": game["seed"], "grid_before": flat}
            ok, why = mod.PLAYERS[model].availability()
            if not ok:
                return self._send({"error": why}, code=400)
            t0 = time.time()
            try:
                with _slot(model):
                    result = mod.step(game, mod.get_player(model))
            except Exception as e:
                log_trace("sudoku", model, gid, trace_req, {"error": str(e)}, (time.time() - t0) * 1000)
                return self._send({"error": str(e)}, code=502)
            payload = {**result, **mod.public(game)}
            log_trace("sudoku", model, gid, trace_req, payload, (time.time() - t0) * 1000)
            return self._send(payload)

    def log_message(self, *a): pass


if __name__ == "__main__":
    # Load each backend on its first decision so pages and baseline runs open immediately.
    print("Arcade ready at http://localhost:8048 (models load on first use)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8048), H).serve_forever()
