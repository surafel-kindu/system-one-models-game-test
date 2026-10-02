"""Sudoku: the engine fills in cells that have exactly one legal digit, then asks the model about the
next cell that needs a real decision — "which digit goes here?" — among the digits still legal there.

A wrong digit is a mistake (it is not placed, and is excluded from that cell next time); three
mistakes end the game. Puzzles have a unique solution and are generated from an integer seed, so a
whole Arena run (or a benchmark) can give every player the identical puzzle.

Like Chess this is server-authoritative: the solution lives on the server, never in the browser.
"""
import functools
import random

from models import BACKENDS, get_backend

EMPTIES = 56             # cells removed from a full grid (~25 givens); fewer if uniqueness forbids
MAX_MISTAKES = 3
STEP_CAP = 200           # model decisions; a safety cap, a real game needs far fewer
ROWS = [[(r, c) for c in range(9)] for r in range(9)]
COLS = [[(r, c) for r in range(9)] for c in range(9)]
BOXES = [[(br * 3 + i, bc * 3 + j) for i in range(3) for j in range(3)] for br in range(3) for bc in range(3)]


def units_of(r, c):
    return ROWS[r], COLS[c], BOXES[(r // 3) * 3 + c // 3]


def legal(grid, r, c):
    used = {grid[a][b] for unit in units_of(r, c) for a, b in unit}
    return [d for d in range(1, 10) if d not in used]


# ---- puzzle generation -------------------------------------------------------------------------
def _fill(grid, rng):
    for r in range(9):
        for c in range(9):
            if grid[r][c] == 0:
                options = legal(grid, r, c)
                rng.shuffle(options)
                for d in options:
                    grid[r][c] = d
                    if _fill(grid, rng):
                        return True
                grid[r][c] = 0
                return False
    return True


def _count(grid, limit=2):
    """Number of solutions (stops counting at `limit`)."""
    best = None
    for r in range(9):
        for c in range(9):
            if grid[r][c] == 0:
                opts = legal(grid, r, c)
                if best is None or len(opts) < len(best[2]):
                    best = (r, c, opts)
                    if len(opts) <= 1:
                        break
        if best and len(best[2]) <= 1:
            break
    if best is None:
        return 1
    r, c, opts = best
    total = 0
    for d in opts:
        grid[r][c] = d
        total += _count(grid, limit - total)
        if total >= limit:
            break
    grid[r][c] = 0
    return total


@functools.lru_cache(maxsize=128)
def make_puzzle(seed):
    rng = random.Random(seed)
    solution = [[0] * 9 for _ in range(9)]
    _fill(solution, rng)
    puzzle = [row[:] for row in solution]
    cells = [(r, c) for r in range(9) for c in range(9)]
    rng.shuffle(cells)
    removed = 0
    for r, c in cells:
        if removed >= EMPTIES:
            break
        keep = puzzle[r][c]
        puzzle[r][c] = 0
        if _count([row[:] for row in puzzle]) == 1:
            removed += 1
        else:
            puzzle[r][c] = keep
    return tuple(map(tuple, puzzle)), tuple(map(tuple, solution))


# ---- game state --------------------------------------------------------------------------------
def new_game(seed=None):
    seed = random.randrange(10 ** 9) if seed is None else seed
    puzzle, solution = make_puzzle(seed)
    return {"seed": seed, "grid": [list(r) for r in puzzle], "solution": [list(r) for r in solution],
            "given": [[v != 0 for v in r] for r in puzzle], "banned": {}, "mistakes": 0, "placed": 0,
            "steps": 0, "score": 0, "over": False, "result": None}


def public(game):
    """What the browser may see — never the solution."""
    return {k: game[k] for k in ("seed", "grid", "given", "mistakes", "placed", "steps", "score", "over", "result")
            } | {"max_mistakes": MAX_MISTAKES}


def cands(game, r, c):
    banned = game["banned"].get((r, c), ())
    return [d for d in legal(game["grid"], r, c) if d not in banned]


def empties(game):
    return [(r, c) for r in range(9) for c in range(9) if game["grid"][r][c] == 0]


def _elsewhere(game, r, c, d, unit):
    """How many OTHER empty cells in `unit` could still take digit d."""
    return sum(1 for a, b in unit if (a, b) != (r, c) and game["grid"][a][b] == 0 and d in cands(game, a, b))


def fits(game, r, c, d):
    row, col, box = units_of(r, c)
    return _elsewhere(game, r, c, d, row), _elsewhere(game, r, c, d, col), _elsewhere(game, r, c, d, box)


def _finish(game, result):
    game["over"], game["result"] = True, result
    game["score"] = 10 * game["placed"] + (100 if result == "solved" else 0)


def autofill(game):
    """Place every cell that has exactly one legal digit, repeatedly. Returns [(r, c, d), ...]."""
    done = []
    changed = True
    while changed:
        changed = False
        for r, c in empties(game):
            options = cands(game, r, c)
            if len(options) == 1:
                game["grid"][r][c] = options[0]
                done.append((r, c, options[0]))
                changed = True
    if not empties(game) and not game["over"]:
        _finish(game, "solved")
    return done


def pick_cell(game):
    """The next cell worth asking about: one that has a digit with nowhere else to go (so a pure
    deduction exists), otherwise the cell with the fewest candidates."""
    todo = empties(game)
    forced = [(len(cands(game, r, c)), r, c) for r, c in todo
              if any(0 in fits(game, r, c, d) for d in cands(game, r, c))]
    pool = forced or [(len(cands(game, r, c)), r, c) for r, c in todo]
    _, r, c = min(pool)
    return r, c


INSTRUCTIONS = (
    "Sudoku: choose the digit for the marked cell. Each option lists how many OTHER empty cells in "
    "the same row, column and box could still take that digit. A digit with 0 in any of those three "
    "has nowhere else to go, so it must be the answer.")


def render(game, cell=None):
    lines = []
    for r in range(9):
        parts = ["?" if cell == (r, c) else (str(game["grid"][r][c]) if game["grid"][r][c] else ".") for c in range(9)]
        lines.append(" | ".join(" ".join(parts[i:i + 3]) for i in (0, 3, 6)))
        if r in (2, 5):
            lines.append("------+-------+------")
    return "\n".join(lines)


def describe(game, cell):
    r, c = cell
    text = (f"Sudoku. Mistakes {game['mistakes']} of {MAX_MISTAKES}. Fill the cell marked ? "
            f"(row {r + 1}, column {c + 1}; rows and columns count from 1).\n{render(game, cell)}")
    crit = {}
    for d in cands(game, r, c):
        a, b, x = fits(game, r, c, d)
        crit[str(d)] = f"{d}: other cells that can still take it — row {a}, column {b}, box {x}"
    return text, crit


class Player:
    name = "base"
    max_concurrency = 1
    baseline = False

    @classmethod
    def availability(cls):
        return True, ""

    def decide(self, game):
        """-> (digit, probabilities, state_text, (row, col))"""
        cell = pick_cell(game)
        text, crit = describe(game, cell)
        pick, probs = self.choose(text, crit)
        if pick not in crit:  # safety net; shouldn't happen with well-behaved backends
            pick = max(crit, key=lambda k: probs.get(k, 0)) if probs else next(iter(crit))
        return int(pick), probs, text, cell

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


class RandomPlayer(Player):
    name, label, baseline = "random", "Random (baseline)", True

    def decide(self, game):
        cell = pick_cell(game)
        options = cands(game, *cell)
        return random.choice(options), {str(d): 1 / len(options) for d in options}, "random legal digit", cell


class GreedyPlayer(Player):
    """Applies the rule in the instructions literally: a digit with 0 alternatives in any unit wins,
    otherwise the digit with the fewest alternatives overall. No model."""
    name, label, baseline = "greedy", "Greedy (baseline)", True

    def decide(self, game):
        cell = pick_cell(game)
        options = cands(game, *cell)
        pick = min(options, key=lambda d: (min(fits(game, *cell, d)), sum(fits(game, *cell, d))))
        return pick, {str(pick): 1.0}, "greedy: digit with a unit it has nowhere else to go", cell


class OraclePlayer(Player):
    """Reads the solution. Upper-bound baseline, no model."""
    name, label, baseline = "oracle", "Oracle (baseline)", True

    def decide(self, game):
        cell = pick_cell(game)
        pick = game["solution"][cell[0]][cell[1]]
        return pick, {str(pick): 1.0}, "oracle: reads the solution", cell


# To add a model: subclass Player (or use model_player), implement choose(state, crit), register it here.
PLAYERS = {"laya": LayaPlayer, "jev": JevPlayer, "drex": DrexPlayer, "kev": KevPlayer, "gliner": GlinerPlayer,
           "bev": BevPlayer, "dm": DmPlayer, "random": RandomPlayer, "greedy": GreedyPlayer, "oracle": OraclePlayer}
_cache = {}


def get_player(name):
    if name not in _cache:
        _cache[name] = PLAYERS[name]()
    return _cache[name]


def step(game, player):
    """One turn: auto-fill forced cells, then ask `player` about the next undecided cell.
    Returns what happened (the browser shows it); `game` is updated in place."""
    auto = autofill(game)
    if game["over"]:
        return {"auto": auto, "decision": None}
    digit, probs, text, (r, c) = player.decide(game)
    correct = digit == game["solution"][r][c]
    if correct:
        game["grid"][r][c] = digit
        game["placed"] += 1
    else:
        game["mistakes"] += 1
        game["banned"].setdefault((r, c), set()).add(digit)
        if game["mistakes"] >= MAX_MISTAKES:
            _finish(game, "failed")
    game["steps"] += 1
    auto += autofill(game)
    if not game["over"] and game["steps"] >= STEP_CAP:
        _finish(game, "capped")
    game["score"] = game["score"] if game["over"] else 10 * game["placed"]
    return {"auto": auto, "decision": {"cell": [r, c], "digit": digit, "correct": correct,
                                       "probs": probs, "state": text}}


def play(player, seed):
    """Headless runner for benchmarking. Returns (score, placed, mistakes, result, steps)."""
    game = new_game(seed)
    while not game["over"]:
        step(game, player)
    return game["score"], game["placed"], game["mistakes"], game["result"], game["steps"]
