"""Project facts and presentation metadata. This site never imports model runtimes."""
GAMES = [
    {"id": "2048", "name": "2048", "number": "01", "mark": "2048", "skill": "Planning & merging", "description": "Four directions, a shrinking board, and a corner worth protecting. Models choose among guarded legal moves.", "metric": "Score / largest tile"},
    {"id": "dino", "name": "Dino Run", "number": "02", "mark": "↗", "skill": "Timing & control", "description": "A runner with jump momentum and real collision bounds. Read the terrain, jump over cacti, and duck under birds.", "metric": "Obstacles cleared"},
    {"id": "chess", "name": "Chess", "number": "03", "mark": "♞", "skill": "Adversarial decisions", "description": "Two players, full chess rules, and a ranked shortlist of about 14 legal moves. Every benchmark pairing plays both colors.", "metric": "Wins / draws / losses"},
    {"id": "flappy", "name": "Flappy Bird", "number": "04", "mark": "⌁", "skill": "Trajectory selection", "description": "Navigate pipe gaps with real flight physics. Assisted models compare short flight plans and replan after each control.", "metric": "Pipes cleared"},
    {"id": "sudoku", "name": "Sudoku", "number": "05", "mark": "123\n456\n789", "skill": "Constraint reasoning", "description": "Forced cells fill automatically. The model handles the next ambiguous digit; three mistakes end the puzzle.", "metric": "Score / solved puzzles"},
]
MODELS = [
    {"id": "laya", "name": "Laya", "size": "~420M", "source": "https://huggingface.co/convaiinnovations/laya", "type": "Local classifier"},
    {"id": "jev", "name": "Jev-BERTa", "size": "~198M", "source": "https://huggingface.co/leobitz/jev-berta-base-zeroshot-classifier", "type": "Local classifier"},
    {"id": "drex", "name": "Drex", "size": "Hosted API", "source": "https://drex.nace.ai/docs", "type": "Remote backend"},
    {"id": "kev", "name": "Kev-0.8B", "size": "~0.8B", "source": "https://github.com/jaredpalmer/kev", "type": "Self-hosted backend"},
    {"id": "gliner", "name": "GLiNER2.5-Decide", "size": "~340M", "source": "https://huggingface.co/fastino/GLiNER2.5-Decide", "type": "Local classifier"},
    {"id": "bev", "name": "Bev-Decider-0.4B", "size": "~0.4B", "source": "https://huggingface.co/avbiswas/bev-decider-0.4B", "type": "Local classifier"},
    {"id": "dm", "name": "DecisionMaster", "size": "Qwen3-based", "source": "https://huggingface.co/leobitz/decision-master-base", "type": "Gated checkpoint"},
]
NAMES = {x['id']: x['name'] for x in MODELS + GAMES}
NAMES.update(random="Random", greedy="Greedy", oracle="Oracle")

GLYPHS = {
    'A':'M9 73V20L20 9H48L59 20V73 M9 43H59', 'B':'M10 9H46L58 21V31L47 41L58 51V61L46 73H10Z M10 41H47',
    'C':'M59 9H22L10 21V61L22 73H59', 'D':'M10 9H44L59 24V58L44 73H10Z', 'E':'M59 9H10V73H59 M10 41H49',
    'F':'M59 9H10V73 M10 41H49', 'G':'M59 9H22L10 21V61L22 73H59V42H37', 'H':'M10 9V73 M59 9V73 M10 41H59',
    'I':'M10 9H59 M34 9V73 M10 73H59', 'J':'M10 9H59V61L47 73H22L10 61', 'K':'M10 9V73 M59 9L25 41L59 73 M10 41H25',
    'L':'M10 9V73H59', 'M':'M10 73V9H18L35 36L52 9H60V73', 'N':'M10 73V9H19L51 73H59V9',
    'O':'M22 9H47L59 21V61L47 73H22L10 61V21Z', 'P':'M10 73V9H47L59 21V34L47 46H10',
    'R':'M10 73V9H47L59 21V34L47 46H10 M36 46L60 73', 'S':'M59 9H22L10 21V30L22 41H47L59 53V61L47 73H10',
    'T':'M5 9H64 M35 9V73', 'U':'M10 9V61L22 73H47L59 61V9', 'V':'M8 9V35L34 73L60 35V9',
    'W':'M7 9V73H16L34 46L52 73H61V9', 'X':'M10 9L59 73 M59 9L10 73', 'Y':'M8 9V23L34 45L60 23V9 M34 45V73', '_':'M8 73H60',
}

def lettering(word):
    # Called only with our own fixed heading strings, never visitor input.
    paths = ''.join(f'<path transform="translate({i*80},0)" d="{GLYPHS[c]}"/>' for i,c in enumerate(word))
    return f'<svg aria-hidden="true" viewBox="0 0 {len(word)*80-10} 84" fill="none" stroke="currentColor" stroke-width="12" stroke-linejoin="bevel" stroke-linecap="square">{paths}</svg>'
