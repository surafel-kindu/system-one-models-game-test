"""Chrome-dino-style runner: a grid of cubes that shifts one column every tick (400ms), with a
fresh jump/duck/none decision asked every tick — not just when an obstacle is imminent.

Each obstacle type has exactly one action that clears it — any other action is a crash. This
mirrors 2048's decision loop (describe the situation, ask a typed choice question, apply the
answer) so the same model backends (models.py) can play both games.
"""
import random

from models import BACKENDS, get_backend

ACTIONS = ["jump", "duck", "none"]
OBSTACLES = ["cactus", "bird_low", "bird_high"]
CORRECT = {"cactus": "jump", "bird_low": "duck", "bird_high": "none"}
LABELS = {
    "cactus": "a cactus on the ground",
    "bird_low": "a bird flying low, at head height",
    "bird_high": "a bird flying high overhead",
}
ACTION_DESC = {
    "jump": "leap into the air — clears a ground cactus, but jumping into a low bird still hits it",
    "duck": "crouch down — ducks under a low-flying bird, but does not clear a ground cactus or a high flier",
    "none": "keep running upright — only safe when the obstacle is flying high overhead",
}

TICK_MS = 400          # a tick fires this often; the grid shifts one column and a decision is asked
GRID_LEN = 10           # columns in the grid (column 0 is the dino's own column); 5x10 board
SPAWN_GAP_START = 5      # ticks between spawns early on
SPAWN_GAP_MIN = 2        # ticks between spawns at max difficulty
OBSTACLE_CAP = 300       # game ends here even if nothing crashed (matches 2048's MOVE_CAP idea)
TICK_CAP = 4000          # hard safety cap on ticks for headless/benchmark runs

# Rows for the 5-row visualization only (0 = bottom, 4 = top) — the pass/fail rule is still the
# CORRECT lookup above, not row overlap; see the README for why a literal row-collision system
# can't reproduce "exactly one correct action per obstacle" with only three rows in play.
ROWS = 5
DINO_ROW = {"none": 1, "jump": 4, "duck": 0}    # "2nd from the bottom" at rest; up on jump, down on duck
OBSTACLE_ROW = {"cactus": 0, "bird_low": 2, "bird_high": 4}


def spawn_gap_for(cleared):
    """Ticks between spawns — the only difficulty knob now that the tick rate itself is fixed."""
    return max(SPAWN_GAP_MIN, SPAWN_GAP_START - cleared // 15)


def gen_obstacle(cleared, rng=random):
    """Weighted by difficulty: more birds (the trickier obstacle) later in a run."""
    bird_p = min(0.2 + cleared * 0.01, 0.7)
    if rng.random() > bird_p:
        return "cactus"
    return "bird_low" if rng.random() < 0.5 else "bird_high"


def new_game():
    return {"score": 0, "cleared": 0, "tick": 0, "obstacles": [], "next_spawn_in": SPAWN_GAP_START}


def step_tick(state, action, rng=random):
    """Advance one 400ms tick: resolve anything that just arrived (column 0) against `action`,
    shift everything else one column closer, maybe spawn a new obstacle at the far column.
    Returns the obstacle type that caused a crash, or None if the tick was clean."""
    arrived = [o for o in state["obstacles"] if o["col"] == 0]
    for ob in arrived:
        if CORRECT[ob["type"]] != action:
            return ob["type"]  # crash — state is left as-is, caller stops the game
    state["cleared"] += len(arrived)
    state["score"] += 10 * len(arrived)
    state["obstacles"] = [o for o in state["obstacles"] if o["col"] > 0]
    for ob in state["obstacles"]:
        ob["col"] -= 1
    state["next_spawn_in"] -= 1
    if state["next_spawn_in"] <= 0:
        state["obstacles"].append({"type": gen_obstacle(state["cleared"], rng), "col": GRID_LEN - 1})
        state["next_spawn_in"] = spawn_gap_for(state["cleared"])
    state["tick"] += 1
    return None


INSTRUCTIONS = (
    "You control a dino on a grid that shifts one column toward you every tick. Pick exactly one "
    "action for this tick — jump, duck, or none. Anything sitting at distance 0 arrives this tick: "
    "the wrong action for its kind is a crash. Nothing at distance 0 means this tick is free, but "
    "plan ahead for what is approaching at distance 1 or 2.")


def describe(state):
    if not state["obstacles"]:
        body = "No obstacles on the grid right now."
    else:
        ordered = sorted(state["obstacles"], key=lambda o: o["col"])
        body = "Grid ahead (distance 0 = arrives this tick):\n" + "\n".join(
            f"- distance {o['col']}: {LABELS[o['type']]}" for o in ordered)
    state_text = f"Dino Run. Score {state['score']}, cleared {state['cleared']}.\n{body}"
    return state_text, dict(ACTION_DESC)


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
LayaPlayer.baseline = JevPlayer.baseline = DrexPlayer.baseline = False


class RandomPlayer(Player):
    name, label, baseline = "random", "Random (baseline)", True

    def decide(self, state):
        pick = random.choice(ACTIONS)
        return pick, {k: 1 / len(ACTIONS) for k in ACTIONS}, "random pick"


class OraclePlayer(Player):
    """Always plays correctly for whatever is at distance 0 (none if nothing is). Upper-bound
    baseline, no model involved."""
    name, label, baseline = "oracle", "Oracle (baseline)", True

    def decide(self, state):
        arrived = [o for o in state["obstacles"] if o["col"] == 0]
        pick = CORRECT[arrived[0]["type"]] if arrived else "none"
        return pick, {pick: 1.0}, "oracle: correct action for what's at distance 0"


# To add a model: subclass Player (or use model_player), implement choose(state, crit), register it here.
PLAYERS = {"laya": LayaPlayer, "jev": JevPlayer, "drex": DrexPlayer, "kev": KevPlayer, "gliner": GlinerPlayer, "bev": BevPlayer, "dm": DmPlayer, "random": RandomPlayer, "oracle": OraclePlayer}
_cache = {}


def get_player(name):
    if name not in _cache:
        _cache[name] = PLAYERS[name]()
    return _cache[name]


def play(policy, cap=OBSTACLE_CAP, max_ticks=TICK_CAP, rng=random):
    """Headless runner for benchmarking: policy(state) -> action string."""
    state = new_game()
    while state["cleared"] < cap and state["tick"] < max_ticks:
        action = policy(state)
        if step_tick(state, action, rng) is not None:
            break
    return state["score"], state["cleared"]
