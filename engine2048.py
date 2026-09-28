"""2048 rules + move decider (models come from models.py, shared across games)."""
import random

from models import BACKENDS, get_backend

MOVES = ["up", "down", "left", "right"]


def _slide_row(row):
    tiles = [v for v in row if v]
    out, gain, i = [], 0, 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            out.append(tiles[i] * 2); gain += tiles[i] * 2; i += 2
        else:
            out.append(tiles[i]); i += 1
    return out + [0] * (4 - len(out)), gain


def move(grid, d):
    """Return (new_grid, gain) — grid unchanged if move is illegal."""
    g = [r[:] for r in grid]
    if d in ("up", "down"):
        g = [list(c) for c in zip(*g)]
    if d in ("right", "down"):
        g = [r[::-1] for r in g]
    gain = 0
    for i, r in enumerate(g):
        g[i], gg = _slide_row(r); gain += gg
    if d in ("right", "down"):
        g = [r[::-1] for r in g]
    if d in ("up", "down"):
        g = [list(c) for c in zip(*g)]
    return g, gain


def merged_cells(grid, d):
    """Cells of the post-move grid that are products of a merge."""
    g = [r[:] for r in grid]
    tr = d in ("up", "down"); rev = d in ("right", "down")
    if tr: g = [list(c) for c in zip(*g)]
    if rev: g = [r[::-1] for r in g]
    cells = set()
    for i, row in enumerate(g):
        t = [v for v in row if v]; k = j = 0
        while j < len(t):
            if j + 1 < len(t) and t[j] == t[j + 1]:
                cells.add((i, k)); j += 2
            else:
                j += 1
            k += 1
    def back(i, k):
        if rev: k = 3 - k
        return (k, i) if tr else (i, k)
    return {back(i, k) for i, k in cells}


def legal(grid):
    return [m for m in MOVES if move(grid, m)[0] != grid]


def spawn(grid, rng=random):
    empt = [(r, c) for r in range(4) for c in range(4) if not grid[r][c]]
    if not empt:
        return grid
    r, c = rng.choice(empt)
    g = [x[:] for x in grid]
    g[r][c] = 2 if rng.random() < 0.9 else 4
    return g


def new_game(rng=random):
    return spawn(spawn([[0] * 4 for _ in range(4)], rng), rng)


def render(grid):
    return "\n".join(" ".join(f"{v:5d}" if v else "    ." for v in r) for r in grid)


CORNERS = [(0, 0), (0, 3), (3, 0), (3, 3)]


def anchor(grid):
    """Corner holding the max tile now (None if it isn't in a corner)."""
    mx = max(v for r in grid for v in r)
    return next((c for c in CORNERS if grid[c[0]][c[1]] == mx), None)


def edge_line(grid, corner):
    """Row along the top/bottom edge starting at the anchor corner."""
    r, c = corner
    row = grid[r][:]
    return row if c == 0 else row[::-1]


def sandwiched(grid):
    """Big tiles (>=16) with a smaller tile on both sides in a row/column -> hard to merge later."""
    n = 0
    for line in list(grid) + [list(c) for c in zip(*grid)]:
        for i in range(1, 3):
            v = line[i]
            if v >= 16 and 0 < line[i - 1] < v and 0 < line[i + 1] < v:
                n += 1
    return n


def describe(grid, moves):
    """Text for the model: the board plus one terse line per candidate move (corner/chain strategy)."""
    mx0 = max(v for r in grid for v in r)
    cor = anchor(grid)
    lines = ["2048 board (row 1 = top):", render(grid), "",
             f"Biggest tile {mx0} is " + (f"in corner (row {cor[0]+1}, col {cor[1]+1})." if cor else "NOT in a corner."),
             "", "Moves:"]
    crit = {}
    for m in moves:
        ng, gain = move(grid, m)
        empty = sum(v == 0 for r in ng for v in r)
        mx = max(v for r in ng for v in r)
        keeps = bool(cor and ng[cor[0]][cor[1]] == mx)
        ordered = False
        if cor:
            el = edge_line(ng, cor)
            ordered = all(el[i] >= el[i + 1] for i in range(3))
        sw = sandwiched(ng)
        ch = ""
        if cor and keeps:
            after = edge_line(ng, cor)
            mc = merged_cells(grid, m)
            cm = sum(1 for (r, c) in mc if r == cor[0])   # merges along the anchor edge row
            off = len(mc) - cm
            ch = f" chain {after[0]}|{after[1]}|{after[2]}|{after[3]} chain-merges {cm} scattered-merges {off}"
            if after[1] == after[0]:
                ch += " CORNER-MERGE-READY"
        lines.append(f"- {m}: {'KEEPS' if keeps else 'LOSES'} corner,{' ordered,' if ordered else ''}"
                     f"{' TRAPPED,' if sw else ''} empty {empty}{ch}")
        crit[m] = f"{m}: keeps the biggest tile in its corner and builds the edge chain"
    return "\n".join(lines), crit


INSTRUCTIONS = (
    "2048 corner strategy: keep the biggest tile in its corner, grow the tile next to it to the same "
    "value so they merge, and avoid scattered merges away from the edge chain. Pick the best move in `state`.")


def candidates(grid):
    """Legal moves, minus any that pull the biggest tile out of its corner (if avoidable)."""
    moves = legal(grid)
    cor = anchor(grid)
    if cor:
        mx = grid[cor[0]][cor[1]]
        moves = [m for m in moves if move(grid, m)[0][cor[0]][cor[1]] == mx] or moves
    return moves


class Player:
    """Shared flow: filter moves, describe the board, let the model choose."""
    name = "base"
    max_concurrency = 1  # simultaneous decide() calls the server will allow

    @classmethod
    def availability(cls):
        """(available, reason-if-not). Lets a player opt out, e.g. when a key is missing."""
        return True, ""

    def decide(self, grid):
        moves = candidates(grid)  # guarded: legal moves that keep the biggest tile in its corner
        if not moves:
            return None, {}, "", False
        if len(moves) == 1:
            return moves[0], {moves[0]: 1.0}, "only legal move", False
        state, crit = describe(grid, moves)
        pick, probs = self.choose(state, crit)
        illegal = pick not in moves  # can't happen with well-behaved models; kept as a safety net
        if illegal:
            pick = max(moves, key=lambda k: probs.get(k, 0))
        return pick, probs, state, illegal

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


class RandomPlayer(Player):
    name, label, baseline = "random", "Random (baseline)", True

    def decide(self, grid):
        moves = legal(grid)
        if not moves:
            return None, {}, "", False
        return random.choice(moves), {k: 1 / len(moves) for k in moves}, "random legal move", False


class GreedyPlayer(Player):
    """Best immediate merge score, then most empty cells. No model involved."""
    name, label, baseline = "greedy", "Greedy (baseline)", True

    def decide(self, grid):
        moves = legal(grid)
        if not moves:
            return None, {}, "", False
        best = max(moves, key=lambda m: (move(grid, m)[1], sum(v == 0 for r in move(grid, m)[0] for v in r)))
        return best, {best: 1.0}, "greedy: highest merge score, then most empty cells", False


LayaPlayer.baseline = JevPlayer.baseline = DrexPlayer.baseline = KevPlayer.baseline = GlinerPlayer.baseline = BevPlayer.baseline = False

# To add a model: subclass Player, implement choose(state, crit), register it here.
PLAYERS = {"laya": LayaPlayer, "jev": JevPlayer, "drex": DrexPlayer, "kev": KevPlayer, "gliner": GlinerPlayer, "bev": BevPlayer, "random": RandomPlayer, "greedy": GreedyPlayer}
_cache = {}


def get_player(name):
    if name not in _cache:
        _cache[name] = PLAYERS[name]()
    return _cache[name]
