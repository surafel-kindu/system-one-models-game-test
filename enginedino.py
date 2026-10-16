"""Desert runner with jump momentum and actual vertical collision bounds.

Assisted control skips empty track and filters immediately fatal actions. Raw control asks the
model every tick. The same seeded physics is used by the browser server and benchmarks.
"""
import functools
import random
from models import BACKENDS, get_backend

VERSION = "arcade-v2"
ACTIONS = ["jump", "duck", "none"]
OBSTACLES = ["cactus", "bird_low", "bird_high"]
LABELS = {"cactus": "ground cactus", "bird_low": "low bird", "bird_high": "high bird"}
# Vertical intervals in world units, above the ground.
BOUNDS = {"cactus": (0, 1.2), "bird_low": (1.1, 2.0), "bird_high": (3.7, 4.8)}
CORRECT = {"cactus": "jump", "bird_low": "duck", "bird_high": "none"}  # legacy imports
TICK_MS, GRID_LEN, PLAYER_COL, ROWS = 180, 24, 3, 8
SPAWN_GAP_START, SPAWN_GAP_MIN = 12, 8
OBSTACLE_CAP, TICK_CAP = 100, 2400
INSTRUCTIONS = (
    "Choose the runner's next action. Jump over ground cacti, duck under low birds, and stay "
    "on the ground under high birds. Jump has momentum and lasts five ticks; it cannot be "
    "cancelled. Prefer the option that safely clears the nearest obstacle. none means run.")


def spawn_gap_for(cleared):
    return max(SPAWN_GAP_MIN, SPAWN_GAP_START - cleared // 12)


def gen_obstacle(cleared, rng=random):
    return rng.choices(OBSTACLES, weights=[5, 3, 2])[0]


def new_game(rng=random, control="assisted"):
    return {"score": 0, "cleared": 0, "tick": 0, "height": 0, "vy": 0,
            "posture": "run", "obstacles": [{"type": gen_obstacle(0, rng), "col": 15}],
            "next_spawn_in": 5, "control": control, "version": VERSION}


def motion(height, vy, action):
    if height == 0 and action == "jump":
        vy = 2
    height = max(0, height + vy)
    return height, vy - 1 if height else 0


def collision(height, action, kind):
    bottom, top = BOUNDS[kind]
    body = 0.8 if height == 0 and action == "duck" else 1.8
    return height < top and height + body > bottom


def step_tick(state, action, rng=random):
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action}")
    state["height"], state["vy"] = motion(state["height"], state["vy"], action)
    state["posture"] = "duck" if action == "duck" and state["height"] == 0 else "run"
    state["tick"] += 1
    for ob in state["obstacles"]:
        ob["col"] -= 1
        if ob["col"] == PLAYER_COL and collision(state["height"], action, ob["type"]):
            return ob["type"]
        if ob["col"] == PLAYER_COL - 1:
            state["cleared"] += 1
            state["score"] += 10
    state["obstacles"] = [o for o in state["obstacles"] if o["col"] >= -1]
    state["next_spawn_in"] -= 1
    if state["next_spawn_in"] <= 0:
        state["obstacles"].append({"type": gen_obstacle(state["cleared"], rng), "col": GRID_LEN - 1})
        state["next_spawn_in"] = spawn_gap_for(state["cleared"])
    return None


def describe(state):
    nearest = sorted((o for o in state["obstacles"] if o["col"] > PLAYER_COL), key=lambda o: o["col"])
    text = (f"Desert runner. Height {state['height']}, vertical speed {state['vy']}. "
            "Ground = 0. Standing height 1.8; ducking height 0.8.\n")
    text += "\n".join(f"{LABELS[o['type']]} arrives in {o['col'] - PLAYER_COL} ticks "
                      f"(height {BOUNDS[o['type']][0]} to {BOUNDS[o['type']][1]})." for o in nearest[:2])
    options = {}
    for action in ACTIONS:
        if state.get("control", "assisted") == "assisted" and state["height"] and action == "jump":
            continue
        height, _ = motion(state["height"], state["vy"], action)
        fatal = any(o["col"] == PLAYER_COL + 1 and collision(height, action, o["type"]) for o in nearest)
        options[action] = f"{action}: next height {height}; " + ("COLLISION this tick" if fatal else "clear this tick")
    if state.get("control", "assisted") == "assisted":
        safe = {a: d for a, d in options.items() if "COLLISION" not in d}
        options = safe or options
    return text, options


class Player:
    name, baseline, max_concurrency = "base", False, 1

    @classmethod
    def availability(cls):
        return True, ""

    def decide(self, state):
        text, options = describe(state)
        nearest = min((o["col"] - PLAYER_COL for o in state["obstacles"] if o["col"] > PLAYER_COL), default=99)
        idle = state.get("control", "assisted") == "assisted" and nearest > 3 and not state["height"]
        called = not idle and len(options) > 1
        if idle:
            action, probs = "none", {"none": 1.0}
        elif len(options) == 1:
            action = next(iter(options)); probs = {action: 1.0}
        else:
            action, probs = self.choose(text, options)
            if action not in options:
                action = max(options, key=lambda a: probs.get(a, 0))
        return action, probs, text, {"choice": action, "options": options, "model_called": called,
                                    "note": "Coasting on open track" if idle else "Immediate collision guard" if len(options) == 1 else "Model decision"}

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
LayaPlayer.baseline = JevPlayer.baseline = DrexPlayer.baseline = False


class RandomPlayer(Player):
    name, label, baseline = "random", "Random (baseline)", True

    def decide(self, state):
        action = random.choice(ACTIONS)
        return action, {a: 1 / len(ACTIONS) for a in ACTIONS}, "random controls", {"model_called": False, "choice": action}


class GreedyPlayer(Player):
    name, label, baseline = "greedy", "Greedy (baseline)", True

    def decide(self, state):
        obs = sorted((o for o in state["obstacles"] if o["col"] > PLAYER_COL), key=lambda o: o["col"])
        action = "none"
        if obs and obs[0]["col"] - PLAYER_COL <= 2:
            if obs[0]["type"] == "cactus" and state["height"] == 0:
                action = "jump"
            elif obs[0]["type"] == "bird_low":
                action = "duck"
        return action, {action: 1.0}, "greedy: react to the nearest obstacle", {"model_called": False, "choice": action}


class OraclePlayer(Player):
    name, label, baseline = "oracle", "Oracle (baseline)", True

    def decide(self, state):
        obstacles = {o["col"] - PLAYER_COL: o["type"] for o in state["obstacles"] if o["col"] > PLAYER_COL}
        horizon = max(obstacles, default=0) + 5

        @functools.lru_cache(None)
        def best(tick, height, vy):
            if tick >= horizon:
                return (0, -height)
            scored = []
            for action in ACTIONS:
                h, v = motion(height, vy, action)
                if tick + 1 in obstacles and collision(h, action, obstacles[tick + 1]):
                    score = (-1, -99)
                else:
                    n, end = best(tick + 1, h, v)
                    score = (1 + n, end)
                scored.append((score, action))
            return max(scored)[0]

        ranked = []
        for action in ACTIONS:
            h, v = motion(state["height"], state["vy"], action)
            score = (-1, -99) if 1 in obstacles and collision(h, action, obstacles[1]) else best(1, h, v)
            ranked.append((score, action == "none", action))
        action = max(ranked)[2]
        return action, {action: 1.0}, "oracle: physics lookahead", {"model_called": False, "choice": action}


PLAYERS = {name: model_player(name) for name in BACKENDS}
PLAYERS.update(random=RandomPlayer, greedy=GreedyPlayer, oracle=OraclePlayer)
_cache = {}


def get_player(name):
    if name not in _cache:
        _cache[name] = PLAYERS[name]()
    return _cache[name]


def play(policy, cap=OBSTACLE_CAP, max_ticks=TICK_CAP, rng=random, control="assisted"):
    state = new_game(rng, control)
    while state["cleared"] < cap and state["tick"] < max_ticks:
        if step_tick(state, policy(state), rng):
            break
    return state["score"], state["cleared"]
