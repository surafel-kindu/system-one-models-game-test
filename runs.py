"""Groups headless benchmark results by run. Every bench invocation creates one run (a run_id, the
game, the CLI parameters, a start time) and each per-player / per-game result is appended to
`bench_runs.jsonl` tagged with that run_id, so a UI can list runs and render each as a benchmark.
Line shapes: {"type":"run", run_id, game, params, ts} then {"type":"result", run_id, player, ...}.
"""
import json, os, threading, time, uuid

_lock = threading.Lock()
FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_runs.jsonl")


class Run:
    def __init__(self, game, **params):
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.game = game
        self._write({"type": "run", "run_id": self.id, "game": game, "params": params, "ts": int(time.time())})

    def _write(self, rec):
        with _lock, open(FILE, "a") as f:   # one write per record, so concurrent benches can't interleave
            f.write("\n" + json.dumps(rec) + "\n")

    def result(self, player, **fields):
        self._write({"type": "result", "run_id": self.id, "game": self.game, "player": player, **fields})


def _records():
    """Yield every JSON object in the file, tolerating blank lines and objects glued onto one line."""
    dec = json.JSONDecoder()
    try:
        for line in open(FILE):
            line, i = line.strip(), 0
            while i < len(line):
                try:
                    rec, i = dec.raw_decode(line, i)
                except ValueError:
                    break
                if isinstance(rec, dict) and "type" in rec and "run_id" in rec:
                    yield rec
    except FileNotFoundError:
        return


def load_runs():
    """-> [{run_id, game, params, ts, results:[...]}] newest first."""
    runs, order = {}, []
    for rec in _records():
        if rec["type"] == "run":
            runs[rec["run_id"]] = {**rec, "results": []}; order.append(rec["run_id"])
        elif rec["run_id"] in runs:
            runs[rec["run_id"]]["results"].append(rec)
    return [runs[i] for i in reversed(order)]
