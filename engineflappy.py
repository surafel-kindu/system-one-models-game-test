"""Flappy Bird on a grid: a 10-row x 12-column board that shifts one column per tick (400ms), with
a fresh flap/none decision asked every tick. Unlike Dino Run's lookup-table rule, this one is real
physics: the bird has a row and a vertical speed, pipes have a gap, and hitting a pipe, the
ceiling or the floor ends the run.

Same shape as the other games: describe the situation, ask a typed choice question, apply it.
"""
import functools
import random

from models import BACKENDS, get_backend

ACTIONS = ["flap", "none"]
ROWS = 10               # row 0 is the top, row 9 the bottom
COLS = 12               # columns on the board; pipes spawn at the right edge and move left
BIRD_COL = 2            # the bird never moves horizontally
GAP = 4                 # rows in each pipe's gap
FLAP_VY = -2            # a flap sets the vertical speed to this (rows per tick, negative = up)
MAX_FALL = 2            # gravity adds 1 per tick up to this
SPAWN_EVERY = 6         # ticks between pipes
MAX_GAP_SHIFT = 2       # a pipe's gap moves at most this many rows from the previous one
TICK_MS = 400
PIPE_CAP = 300          # run ends here even if nothing crashed
TICK_CAP = 4000         # hard safety cap for headless runs

ACTION_DESC = {
    "flap": "flap — rise 2 rows this tick and reset the falling speed",
    "none": "do nothing — fall faster (up to 2 rows per tick)",
}
INSTRUCTIONS = (
    "You control a bird on a grid (row 0 is the top). Pick flap or none for this tick. The bird "
    "must be inside the next pipe's gap rows on the tick the pipe reaches it; hitting a pipe, the "
    "ceiling or the floor ends the run. Each option states where the bird will be next tick.")


def next_motion(row, vy, action):
    vy2 = FLAP_VY if action == "flap" else min(vy + 1, MAX_FALL)
    return row + vy2, vy2


def new_game(rng=random):
    return {"score": 0, "tick": 0, "passed": 0, "bird_row": ROWS // 2, "vy": 0, "pipes": [],
            "next_spawn_in": SPAWN_EVERY + 1, "last_gap": (ROWS - GAP) // 2}


def step_tick(state, action, rng=random):
    """Advance one tick. Returns why the run ended ("ceiling", "floor" or "pipe"), else None."""
    row, vy = next_motion(state["bird_row"], state["vy"], action)
    state["bird_row"], state["vy"] = max(0, min(ROWS - 1, row)), vy
    if row < 0:
        return "ceiling"
    if row > ROWS - 1:
        return "floor"
    for p in state["pipes"]:
        p["col"] -= 1
    for p in state["pipes"]:
        if p["col"] == BIRD_COL:
            if p["gap"] <= row < p["gap"] + GAP:
                state["passed"] += 1
                state["score"] += 10
            else:
                return "pipe"
    state["pipes"] = [p for p in state["pipes"] if p["col"] >= 0]
    state["next_spawn_in"] -= 1
    if state["next_spawn_in"] <= 0:
        gap = state["last_gap"] + rng.randint(-MAX_GAP_SHIFT, MAX_GAP_SHIFT)
        gap = max(0, min(ROWS - GAP, gap))
        state["pipes"].append({"col": COLS - 1, "gap": gap})
        state["last_gap"] = gap
        state["next_spawn_in"] = SPAWN_EVERY
    state["tick"] += 1
    return None


def upcoming(state):
    return sorted((p for p in state["pipes"] if p["col"] > BIRD_COL), key=lambda p: p["col"])


def describe(state):
    row, vy = state["bird_row"], state["vy"]
    lines = [f"Flappy Bird. Score {state['score']}, pipes passed {state['passed']}.",
             f"Grid has {ROWS} rows (row 0 = top, row {ROWS - 1} = bottom). "
             f"Bird: row {row}, vertical speed {vy} (negative = rising, positive = falling)."]
    ups = upcoming(state)
    if not ups:
        lines.append("No pipe ahead yet.")
    for i, p in enumerate(ups[:2]):
        n = p["col"] - BIRD_COL
        lines.append(f"{'Next' if i == 0 else 'Then'} pipe: reaches the bird in {n} tick{'s' if n != 1 else ''} "
                     f"(1 = this tick), gap is rows {p['gap']}-{p['gap'] + GAP - 1}.")
    crit = {}
    for a, desc in ACTION_DESC.items():
        r, _ = next_motion(row, vy, a)
        where = "hits the ceiling" if r < 0 else "hits the floor" if r > ROWS - 1 else f"bird will be at row {r}"
        crit[a] = f"{desc} ({where})"
    return "\n".join(lines), crit


class Player:
    name = "base"
    max_concurrency = 1
    baseline = False

    @classmethod
    def availability(cls):
        return True, ""

    def decide(self, state):
        state_text, crit = describe(state)
        pick, probs = self.choose(state_text, crit)
        if pick not in crit:  # safety net; shouldn't happen with well-behaved backends
            pick = max(crit, key=lambda k: probs.get(k, 0))
        return pick, probs, state_text

    def choose(self, state, crit):
        raise NotImplementedError


def model_player(backend_name):
    """Build a Player subclass that answers via the named shared backend (models.py)."""
    class P(Player):
        name = backend_name

        @classmethod
        def availability(cls):
            return BACKENDS[backend_name].availability()

        def __init__(self):
            self.backend = get_backend(backend_name)
            self.max_concurrency = self.backend.max_concurrency

        def choose(self, state, crit):
            return self.backend.answer(state, INSTRUCTIONS, crit)

    P.__name__ = backend_name.capitalize() + "Player"
    P.label = BACKENDS[backend_name].label
    return P


LayaPlayer = model_player("laya")
JevPlayer = model_player("jev")
DrexPlayer = model_player("drex")
KevPlayer = model_player("kev")
GlinerPlayer = model_player("gliner")
BevPlayer = model_player("bev")
DmPlayer = model_player("dm")


def _target_row(state):
    ups = upcoming(state)
    return ups[0]["gap"] + (GAP - 1) / 2 if ups else (ROWS - 1) / 2


class RandomPlayer(Player):
    name, label, baseline = "random", "Random (baseline)", True

    def decide(self, state):
        pick = random.choice(ACTIONS)
        return pick, {a: 1 / len(ACTIONS) for a in ACTIONS}, "random pick"


class GreedyPlayer(Player):
    """Steers toward the middle of the next gap with a fixed rule. No lookahead, no model."""
    name, label, baseline = "greedy", "Greedy (baseline)", True

    def decide(self, state):
        r, _ = next_motion(state["bird_row"], state["vy"], "none")
        flap_r, _ = next_motion(state["bird_row"], state["vy"], "flap")
        # 1.5 rows of slack: a flap carries the bird ~3 rows up, nearly the whole 4-row gap
        pick = "flap" if r > _target_row(state) + 1.5 and flap_r >= 0 else "none"
        return pick, {pick: 1.0}, "greedy: flap when falling would leave the bird well below the gap's middle"


class OraclePlayer(Player):
    """Exact dynamic programming over every pipe already on the board (each is at most 9 ticks
    away), using the real motion rules. Upper-bound baseline, no model."""
    name, label, baseline = "oracle", "Oracle (baseline)", True

    def decide(self, state):
        pipes = [(p["col"] - BIRD_COL, p["gap"]) for p in state["pipes"] if p["col"] > BIRD_COL]
        gap_at = dict(pipes)
        horizon = (max(n for n, _ in pipes) + 3) if pipes else 3
        end_target = (pipes[-1][1] + (GAP - 1) / 2) if pipes else (ROWS - 1) / 2

        @functools.lru_cache(maxsize=None)
        def best(k, row, vy):
            """(ticks survived from here, -distance from the last gap's middle) — higher is better."""
            if k == horizon:
                return (0, -abs(row - end_target))
            top = None
            for a in ACTIONS:
                r, v = next_motion(row, vy, a)
                g = gap_at.get(k + 1)
                if r < 0 or r > ROWS - 1 or (g is not None and not g <= r < g + GAP):
                    val = (0, -99)
                else:
                    sub = best(k + 1, r, v)
                    val = (1 + sub[0], sub[1])
                if top is None or val > top:
                    top = val
            return top

        scored = []
        for a in ACTIONS:
            r, v = next_motion(state["bird_row"], state["vy"], a)
            g = gap_at.get(1)
            if r < 0 or r > ROWS - 1 or (g is not None and not g <= r < g + GAP):
                scored.append(((-1, -99), a))
            else:
                sub = best(1, r, v)
                scored.append(((1 + sub[0], sub[1]), a))
        pick = max(scored)[1]
        return pick, {pick: 1.0}, "oracle: exact lookahead over the pipes on the board"


# To add a model: subclass Player (or use model_player), implement choose(state, crit), register it here.
PLAYERS = {"laya": LayaPlayer, "jev": JevPlayer, "drex": DrexPlayer, "kev": KevPlayer, "gliner": GlinerPlayer,
           "bev": BevPlayer, "dm": DmPlayer, "random": RandomPlayer, "greedy": GreedyPlayer, "oracle": OraclePlayer}
_cache = {}


def get_player(name):
    if name not in _cache:
        _cache[name] = PLAYERS[name]()
    return _cache[name]


def play(policy, cap=PIPE_CAP, max_ticks=TICK_CAP, rng=random):
    """Headless runner for benchmarking: policy(state) -> action. Returns (score, pipes passed, why)."""
    state = new_game(rng)
    why = None
    while state["passed"] < cap and state["tick"] < max_ticks:
        why = step_tick(state, policy(state), rng)
        if why:
            break
    return state["score"], state["passed"], why or "cap"
