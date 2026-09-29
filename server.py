"""Serves all games' pages, their decision APIs, and persisted arena results.

Routes:
  /                 redirect to /2048
  /2048             2048 arena (landing)         /2048/play   single 2048 game
  /dino             Dino Run arena               /dino/play   single Dino Run game
  /chess            Chess arena                  /chess/play  one match, two chosen models
  /style.css        shared stylesheet
  GET  /api/<game>/models    player list + availability
  GET  /api/<game>/results   saved arena results
  POST /api/<game>/decide    {model, ...game state} -> the chosen move/action (2048, dino)
  POST /api/<game>/results   append one finished game's result
  Chess only (the board is adversarial and stateful, so it's kept server-side per match):
  POST /api/chess/matches            {white, black} -> {match_id, fen, turn, over, history}
  POST /api/chess/matches/<id>/step  -> plays the side-to-move's next move, returns the new state
  /traces                     the trace browser page
  GET  /api/traces?game=&model=&game_id=&q=&limit=   filtered trace log, newest first
"""
import contextlib
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import chess

import engine2048
import enginechess
import enginedino
from models import get_backend

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = {"2048": engine2048, "dino": enginedino, "chess": enginechess}
RESULTS = {g: os.path.join(HERE, f"results_{g}.json") for g in GAMES}
PAGES = {
    ("2048", "arena"): "arena_2048.html", ("2048", "play"): "play_2048.html",
    ("dino", "arena"): "arena_dino.html", ("dino", "play"): "play_dino.html",
    ("chess", "arena"): "arena_chess.html", ("chess", "play"): "play_chess.html",
}
_res_lock = threading.Lock()
MATCHES = {}  # chess match_id -> {board, white, black, history, lock}
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
BACKEND_IDS = ("laya", "jev", "drex", "kev", "gliner", "bev")
_slots = {}


def _slot(model):
    if model not in BACKEND_IDS:
        return contextlib.nullcontext()
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
        self._send(open(os.path.join(HERE, name), "rb").read(), "text/html")

    def do_GET(self):
        path = self.path.split("?")[0]
        parts = [p for p in path.split("/") if p]
        if path == "/":
            self.send_response(302); self.send_header("Location", "/2048"); self.end_headers(); return
        if path == "/style.css":
            return self._send(open(os.path.join(HERE, "style.css"), "rb").read(), "text/css")
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
        req = json.loads(self.rfile.read(length)) if length else {}

        if game == "chess" and len(parts) == 3 and parts[2] == "matches":
            return self._new_match(mod, req)
        if game == "chess" and len(parts) == 5 and parts[2] == "matches" and parts[4] == "step":
            return self._step_match(mod, parts[3])
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
                    else:
                        a, probs, state = player.decide(req["state"])
                        payload = {"action": a, "probs": probs, "state": state}
            except Exception as e:  # e.g. hosted API failure: report it instead of dropping the connection
                log_trace(game, model, req.get("game_id"), req, {"error": str(e)}, (time.time() - t0) * 1000)
                return self._send({"error": str(e)}, code=502)
            log_trace(game, model, req.get("game_id"), req, payload, (time.time() - t0) * 1000)
            return self._send(payload)
        self.send_error(404)

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

    def log_message(self, *a): pass


if __name__ == "__main__":
    for game, mod in GAMES.items():  # preload so the first move isn't slow; backends are shared/cached
        for n, p in mod.PLAYERS.items():
            ok, why = p.availability()
            print(f"{game}/{n}: {'ready' if ok else 'skipped (' + why + ')'}", flush=True) if not ok else mod.get_player(n)
    print("http://localhost:8048  (2048: /2048, /2048/play — dino: /dino, /dino/play — chess: /chess, /chess/play)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8048), H).serve_forever()
