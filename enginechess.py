"""Chess: full rules via python-chess; models pick a move from a code-ranked shortlist.

Unlike 2048/Dino, this game is adversarial (two models play each other, alternating colors) and
its rules are too intricate to safely mirror in JS (castling, en passant, check, checkmate, draw
conditions), so the authoritative `chess.Board` lives on the server per match — see server.py's
MATCHES. This module only decides one side's move for a given board.
"""
import random

import chess

from models import BACKENDS, get_backend

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
SHORTLIST_CAP = 14  # keeps state+choices text within local models' ~512-token budget


def material(board, color):
    return sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values() if p.color == color)


def _tags(board, move):
    """Short, human-readable tags for one move: capture/check/castle/promotion + direction."""
    tags = []
    mover = board.turn
    if board.is_capture(move):
        victim = board.piece_at(move.to_square)
        if board.is_en_passant(move):
            tags.append("captures pawn en passant")
        elif victim:
            tags.append(f"captures {chess.piece_name(victim.piece_type)} (+{PIECE_VALUE[victim.piece_type]})")
    if board.is_castling(move):
        tags.append("castles " + ("kingside" if chess.square_file(move.to_square) == 6 else "queenside") + ", king safety")
    if move.promotion:
        tags.append(f"promotes to {chess.piece_name(move.promotion)}")
    from_rank, to_rank = chess.square_rank(move.from_square), chess.square_rank(move.to_square)
    forward = (to_rank > from_rank) if mover == chess.WHITE else (to_rank < from_rank)
    if from_rank != to_rank:
        tags.append("advances forward" if forward else "retreats backward")
    else:
        tags.append("moves sideways")
    board.push(move)
    if board.is_checkmate():
        tags.append("CHECKMATE — wins the game")
    elif board.is_check():
        tags.append("gives check")
    elif board.is_repetition(2):
        tags.append("repeats a position — heads toward a draw")
    board.pop()
    return tags


def _score(board, move):
    """Heuristic used only to rank/shortlist candidates in code — the model still picks among them."""
    s = 0.0
    if board.is_capture(move):
        victim = board.piece_at(move.to_square)
        s += 10 + (PIECE_VALUE[victim.piece_type] if victim else 1)
    board.push(move)
    if board.is_checkmate():
        s += 1000
    elif board.is_check():
        s += 6
    elif board.is_repetition(2):  # heading toward a draw; nudge away from it unless nothing better exists
        s -= 4
    board.pop()
    file, rank = chess.square_file(move.to_square), chess.square_rank(move.to_square)
    s += 2 - (abs(file - 3.5) + abs(rank - 3.5)) * 0.25  # mild pull toward the center
    return s


def _candidate_moves(board):
    """All legal moves, except: promoting to anything but a queen is (almost) never right, so don't
    offer that trap alongside the always-legal queen promotion for the same pawn push."""
    moves = list(board.legal_moves)
    kept = [m for m in moves if not (m.promotion and m.promotion != chess.QUEEN)]
    return kept or moves  # keep everything if somehow only underpromotions remain


def shortlist(board, cap=SHORTLIST_CAP):
    """Legal moves ranked by _score and capped, like 2048's guarded candidates: the model chooses
    among code-filtered good options rather than the full, often-40-wide, legal move list."""
    moves = _candidate_moves(board)
    moves.sort(key=lambda m: _score(board, m), reverse=True)
    return moves[:cap]


def render(board):
    rows = str(board).split("\n")  # python-chess: rank 8 first, files a-h, '.' for empty
    return "\n".join(f"{8 - i} {row}" for i, row in enumerate(rows)) + "\n  a b c d e f g h"


INSTRUCTIONS = (
    "Play chess. Pick the best move from the options for the side to move. Favor moves that "
    "capture material, give check or checkmate, improve king safety, or develop toward the center; "
    "avoid moves that hang material for nothing in return.")


def describe(board):
    mover = board.turn
    color_name = "White" if mover == chess.WHITE else "Black"
    toward = "up the board, toward rank 8" if mover == chess.WHITE else "down the board, toward rank 1"
    mine, theirs = material(board, mover), material(board, not mover)
    diff = f"up {mine - theirs}" if mine > theirs else (f"down {theirs - mine}" if theirs > mine else "even")
    state = (f"Chess. You are playing {color_name}; your pieces move {toward}. UPPERCASE = White, "
             f"lowercase = Black, . = empty.\n" + render(board) +
             f"\nMaterial: you {mine}, opponent {theirs} ({diff}). {color_name} to move.")
    cands = shortlist(board)
    crit = {}
    for m in cands:
        san = board.san(m)
        tags = _tags(board, m)
        crit[m.uci()] = f"{san}: " + (", ".join(tags) if tags else "quiet developing move")
    return state, crit, cands


class Player:
    name = "base"
    max_concurrency = 1
    baseline = False

    @classmethod
    def availability(cls):
        return True, ""

    def decide(self, board):
        state, crit, cands = describe(board)
        if len(crit) == 1:  # Jev-BERTa (and any future backend) may require >=2 choices
            only = next(iter(crit))
            return only, {only: 1.0}, state
        pick, probs = self.choose(state, crit)
        if pick not in crit:  # safety net; shouldn't happen with well-behaved backends
            pick = max(crit, key=lambda k: probs.get(k, 0)) if probs else cands[0].uci()
        return pick, probs, state

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

    def decide(self, board):
        moves = list(board.legal_moves)
        m = random.choice(moves)
        return m.uci(), {}, f"random legal move ({board.san(m)})"


class GreedyPlayer(Player):
    """Always the top-ranked shortlisted move (captures, checks, center). No model involved."""
    name, label, baseline = "greedy", "Greedy (baseline)", True

    def decide(self, board):
        cands = shortlist(board, cap=len(list(board.legal_moves)) or 1)
        best = cands[0]
        return best.uci(), {best.uci(): 1.0}, f"greedy: highest-ranked move ({board.san(best)})"


# To add a model: use model_player("name") after registering a Backend in models.py, then add it here.
PLAYERS = {"laya": LayaPlayer, "jev": JevPlayer, "drex": DrexPlayer, "kev": KevPlayer, "gliner": GlinerPlayer, "random": RandomPlayer, "greedy": GreedyPlayer}
_cache = {}


def get_player(name):
    if name not in _cache:
        _cache[name] = PLAYERS[name]()
    return _cache[name]


def new_game():
    return chess.Board()


def outcome_info(board):
    """(result_str, reason) once board.is_game_over(), else (None, None)."""
    o = board.outcome()
    if o is None:
        return None, None
    result = {chess.WHITE: "1-0", chess.BLACK: "0-1", None: "1/2-1/2"}[o.winner]
    return result, o.termination.name.lower()


def play(white_policy, black_policy, max_plies=200):
    """Headless runner for benchmarking: policy(board) -> move_uci."""
    board = new_game()
    while not board.is_game_over() and board.ply() < max_plies:
        policy = white_policy if board.turn == chess.WHITE else black_policy
        board.push(chess.Move.from_uci(policy(board)))
    result, reason = outcome_info(board)
    return result or "1/2-1/2", reason or "ply_limit", board.ply()
