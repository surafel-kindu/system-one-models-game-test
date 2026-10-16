"""Public page copy and asset identities, shared by headers and link previews."""
PAGES = {
    'home': dict(path='/', title='Small models. Real decisions.',
        description='Five familiar games. Seven model backends. Explore how small decision models choose their next move, inspect benchmarks, and build the next experiment.',
        caption='Five games. One decision at a time.', card_lines=['SMALL MODELS.', 'REAL DECISIONS.']),
    'benchmarks': dict(path='/benchmarks', title='Benchmark archive',
        description='Explore recorded game benchmarks with shared seeds, baseline comparisons, raw scores, timing, control modes, and game versions. Read the conditions with the score.',
        caption='Inspect the seeds, the settings, and the recorded results.', card_lines=['BENCHMARK', 'THE CHOICE.']),
    'project': dict(path='/project', title='About the experiment',
        description='Meet Model Arcade Lab: an open playground where small decision models rank candidate actions in 2048, Dino Run, Chess, Flappy Bird, and Sudoku.',
        caption='State → candidate actions → a choice → the next state.', card_lines=['SMALL MODELS.', 'VISIBLE CHOICES.']),
    'contribute': dict(path='/contribute', title='Build the next experiment',
        description='Contribute a model adapter, a console benchmark, or a browser game. Follow the engine, baseline, test, and pull-request guides for Model Arcade Lab.',
        caption='A model, a console game, or a complete browser experiment.', card_lines=['BUILD THE NEXT', 'EXPERIMENT.']),
    'submit-model': dict(path='/submit', title='Suggest a model',
        description='Bring a model to Model Arcade Lab. Share its source, creator, description, and setup instructions for maintainer review.',
        caption='Share the source. Credit the creator. Explain the setup.', card_lines=['BRING A MODEL.', 'ADD A NEW PLAYER.']),
    'submit-game': dict(path='/submit?kind=game', title='Suggest a game',
        description='Suggest a new game for Model Arcade Lab, with its rules, source, creator, and console or browser integration ideas.',
        caption='New rules. New decisions. A different kind of experiment.', card_lines=['BRING A GAME.', 'ASK A NEW QUESTION.']),
}


def page_metadata(endpoint, kind='model'):
    key = {'home':'home', 'benchmarks_page':'benchmarks', 'project':'project',
           'contribute':'contribute', 'submit':'submit-game' if kind=='game' else 'submit-model'}.get(endpoint)
    return dict(PAGES[key or 'home'], key=key or 'home', public=key is not None)
