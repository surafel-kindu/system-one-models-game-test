"""Chrome-dino-style runner, simplified to one decision per obstacle: jump, duck, or none.

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
OBSTACLE_CAP = 300  # game ends here even if nothing crashed (matches 2048's MOVE_CAP idea)


def speed_for(cleared):
    return round(min(6 + cleared * 0.15, 18), 1)


def gen_obstacle(cleared, rng=random):
    """Weighted by difficulty: more birds (the trickier obstacle) later in a run."""
    bird_p = min(0.2 + cleared * 0.01, 0.7)
    if rng.random() > bird_p:
        return "cactus"
    return "bird_low" if rng.random() < 0.5 else "bird_high"


def new_game():
    return {"score": 0, "cleared": 0, "speed": speed_for(0)}


def resolve(obstacle, action):
    """True = cleared, False = crash."""
    return CORRECT.get(obstacle) == action


def advance(state, obstacle):
    """Mutates state after a cleared obstacle: score/cleared/speed for the next one."""
    state["cleared"] += 1
    state["score"] += round(10 * state["speed"] / 6)
    state["speed"] = speed_for(state["cleared"])
    return state


INSTRUCTIONS = (
    "You control a dino that must react to the obstacle ahead. Pick exactly one action — jump, "
    "duck, or none — based on what kind of obstacle it is. Only one action clears each kind.")


def describe(state, obstacle, next_obstacle=None):
    state_text = (f"Dino Run. Score {state['score']}, obstacles cleared {state['cleared']}, "
                  f"speed {state['speed']}.\nObstacle ahead: {LABELS[obstacle]}." +
                  (f" After that: {LABELS[next_obstacle]}." if next_obstacle else ""))
    crit = dict(ACTION_DESC)
    return state_text, crit


class Player:
    name = "base"
    max_concurrency = 1
    baseline = False

    @classmethod
    def availability(cls):
        return True, ""

    def decide(self, state, obstacle, next_obstacle=None):
        state_text, crit = describe(state, obstacle, next_obstacle)
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
LayaPlayer.baseline = JevPlayer.baseline = DrexPlayer.baseline = False


class RandomPlayer(Player):
    name, label, baseline = "random", "Random (baseline)", True

    def decide(self, state, obstacle, next_obstacle=None):
        pick = random.choice(ACTIONS)
        return pick, {k: 1 / len(ACTIONS) for k in ACTIONS}, f"random pick vs {obstacle}"


class OraclePlayer(Player):
    """Always plays the correct action for the obstacle. Upper-bound baseline, no model involved."""
    name, label, baseline = "oracle", "Oracle (baseline)", True

    def decide(self, state, obstacle, next_obstacle=None):
        pick = CORRECT[obstacle]
        return pick, {pick: 1.0}, f"oracle: correct action vs {obstacle}"


# To add a model: subclass Player (or use model_player), implement choose(state, crit), register it here.
PLAYERS = {"laya": LayaPlayer, "jev": JevPlayer, "drex": DrexPlayer, "kev": KevPlayer, "gliner": GlinerPlayer, "random": RandomPlayer, "oracle": OraclePlayer}
_cache = {}


def get_player(name):
    if name not in _cache:
        _cache[name] = PLAYERS[name]()
    return _cache[name]


def play(policy, cap=OBSTACLE_CAP, rng=random):
    """Headless runner for benchmarking: policy(state, obstacle) -> action string."""
    state = new_game()
    while state["cleared"] < cap:
        obstacle = gen_obstacle(state["cleared"], rng)
        action = policy(state, obstacle)
        if not resolve(obstacle, action):
            break
        advance(state, obstacle)
    return state["score"], state["cleared"]
