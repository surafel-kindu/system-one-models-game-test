"""Flappy physics with optional three-tick flight-plan choices and a transparent safety filter."""
import functools
import itertools
import random

from models import BACKENDS, get_backend

VERSION = "arcade-v2"
ACTIONS = ["flap", "none"]
ROWS = 10               # row 0 is the top, row 9 the bottom
COLS = 12               # columns on the board; pipes spawn at the right edge and move left
BIRD_COL = 2            # the bird never moves horizontally
GAP = 4                 # rows in each pipe's gap
FLAP_VY = -2            # a flap sets the vertical speed to this (rows per tick, negative = up)
MAX_FALL = 2            # gravity adds 1 per tick up to this
SPAWN_EVERY = 6         # ticks between pipes
MAX_GAP_SHIFT = 2       # a pipe's gap moves at most this many rows from the previous one
TICK_MS = 180
PIPE_CAP = 100          # run ends here even if nothing crashed
TICK_CAP = 2400         # hard safety cap for headless runs

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


def new_game(rng=random, control="assisted"):
    return {"score": 0, "tick": 0, "passed": 0, "bird_row": ROWS // 2, "vy": 0, "pipes": [{"col": 10, "gap": 3}],
            "next_spawn_in": SPAWN_EVERY + 1, "last_gap": (ROWS - GAP) // 2, "control": control, "version": VERSION}


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


def flight_plans(state):
    """Simulate 3 controls against visible pipes only; never invent unseen future pipes."""
    plans = {}
    for sequence in itertools.product(ACTIONS, repeat=3):
        row, vy, path, reason = state["bird_row"], state["vy"], [], None
        for tick, action in enumerate(sequence, 1):
            row, vy = next_motion(row, vy, action)
            if not 0 <= row < ROWS:
                reason = "ceiling" if row < 0 else "floor"
            for pipe in state["pipes"]:
                if pipe["col"] - tick == BIRD_COL and not pipe["gap"] <= row < pipe["gap"] + GAP:
                    reason = "pipe"
            if reason:
                break
            path.append(row)
        key = "_".join("flap" if a == "flap" else "coast" for a in sequence)
        plans[key] = {"actions": list(sequence), "path": path, "survived": len(path), "crash": reason}
    safe = {k: p for k, p in plans.items() if p["crash"] is None}
    # A locally safe path can still strand the bird outside an approaching gap. Keep plans
    # whose final state has at least one physically possible continuation through visible pipes.
    # This guard is explicit assistance, not model reasoning or knowledge of unseen pipes.
    gaps = {p["col"] - BIRD_COL: p["gap"] for p in state["pipes"] if p["col"] > BIRD_COL}
    horizon = max(3, max(gaps, default=0) + 2)

    @functools.lru_cache(None)
    def reachable(tick, row, vy):
        if tick >= horizon:
            return True
        for action in ACTIONS:
            r, v = next_motion(row, vy, action)
            gap = gaps.get(tick + 1)
            if 0 <= r < ROWS and (gap is None or gap <= r < gap + GAP) and reachable(tick + 1, r, v):
                return True
        return False

    viable = {}
    for key, plan in safe.items():
        row, vy = state["bird_row"], state["vy"]
        for action in plan["actions"]:
            row, vy = next_motion(row, vy, action)
        if reachable(3, row, vy):
            viable[key] = plan
    if viable or safe:
        return viable or safe
    longest = max(p["survived"] for p in plans.values())
    return {k: p for k, p in plans.items() if p["survived"] == longest}


def describe(state):
    row, vy = state["bird_row"], state["vy"]
    text = f"Bird row {row}, speed {vy}. Row 0 = ceiling, row 9 = floor. "
    text += "Flap rises 2 rows; coasting accelerates down.\n"
    ups = upcoming(state)
    for pipe in ups[:2]:
        text += f"Pipe in {pipe['col'] - BIRD_COL} ticks, safe rows {pipe['gap']}-{pipe['gap'] + GAP - 1}.\n"
    if not ups:
        text += "No pipe ahead. Stay near the middle rows.\n"
    if state.get("control", "assisted") == "raw":
        crit = {}
        for action in ACTIONS:
            r, _ = next_motion(row, vy, action)
            crit[action] = f"{action}: next row {r}" + (" COLLISION" if not 0 <= r < ROWS else "")
        return text, crit
    target = _target_row(state)
    options = {}
    for key, plan in flight_plans(state).items():
        path = " → ".join(str(r) for r in plan["path"])
        end = plan["path"][-1] if plan["path"] else row
        options[key] = (f"{key.replace('_', ' / ')}: rows {path}; "
                        f"ends {abs(end - target):.1f} rows from gap center" +
                        (f"; hits {plan['crash']}" if plan["crash"] else "; clear for 3 ticks"))
    return text, options


class Player:
    name, baseline, max_concurrency = "base", False, 1

    @classmethod
    def availability(cls):
        return True, ""

    def decide(self, state):
        text, options = describe(state)
        called = len(options) > 1
        if called:
            pick, probs = self.choose(text, options)
            if pick not in options:
                pick = max(options, key=lambda k: probs.get(k, 0))
        else:
            pick = next(iter(options)); probs = {pick: 1.0}
        raw = state.get("control", "assisted") == "raw"
        plan = None if raw else flight_plans(state)[pick]
        action = pick if raw else plan["actions"][0]
        return action, probs, text, {"choice": pick, "options": options, "model_called": called,
                                    "path": plan["path"] if plan else [],
                                    "note": "Raw controls" if raw else "Flight plans + gap reachability guard · replan each tick"}

    def choose(self, state, criteria):
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


def play(policy, cap=PIPE_CAP, max_ticks=TICK_CAP, rng=random, control="assisted"):
    """Headless runner for benchmarking: policy(state) -> action. Returns (score, pipes passed, why)."""
    state = new_game(rng, control)
    why = None
    while state["passed"] < cap and state["tick"] < max_ticks:
        why = step_tick(state, policy(state), rng)
        if why:
            break
    return state["score"], state["passed"], why or "cap"
