"""Physics, model-control, API and benchmark regressions. No weights or hosted calls needed."""
import contextlib
import io
import json
import random
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark
import engineflappy as flappy
import enginedino as dino
import runs
import server
from benchmark_console import Console


class PhysicsTests(unittest.TestCase):
    def test_jump_has_momentum_and_lands(self):
        height = vy = 0
        heights = []
        for action in ['jump'] + ['none'] * 4:
            height, vy = dino.motion(height, vy, action)
            heights.append(height)
        self.assertEqual(heights, [2, 3, 3, 2, 0])
        self.assertEqual(vy, 0)

    def test_real_collision_intervals(self):
        self.assertTrue(dino.collision(0, 'none', 'cactus'))
        self.assertFalse(dino.collision(2, 'jump', 'cactus'))
        self.assertFalse(dino.collision(0, 'duck', 'bird_low'))
        self.assertTrue(dino.collision(0, 'none', 'bird_low'))
        self.assertFalse(dino.collision(0, 'none', 'bird_high'))
        self.assertTrue(dino.collision(3, 'jump', 'bird_high'))

    def test_oracles_complete_seeded_courses(self):
        for mod in (dino, flappy):
            for seed in range(20):
                player = mod.get_player('oracle')
                result = mod.play(lambda s: player.decide(s)[0], rng=random.Random(seed))
                self.assertEqual(result[:2], (1000, 100), (mod.__name__, seed, result))

    def test_dino_assistance_skips_idle_and_guards_collision(self):
        class Probe(dino.Player):
            def choose(self, state, criteria):
                raise AssertionError('must not invoke model for an idle or forced control')
        state = dino.new_game(random.Random(0))
        self.assertFalse(Probe().decide(state)[3]['model_called'])
        state['obstacles'] = [{'type':'cactus', 'col':dino.PLAYER_COL+1}]
        self.assertEqual(Probe().decide(state)[0], 'jump')
        state['control'] = 'raw'
        self.assertEqual(set(dino.describe(state)[1]), set(dino.ACTIONS))

    def test_flappy_plans_follow_the_real_physics(self):
        for row in range(10):
            state = flappy.new_game(); state['bird_row'] = row
            for plan in flappy.flight_plans(state).values():
                clone = json.loads(json.dumps(state)); path = []
                for action in plan['actions']:
                    if flappy.step_tick(clone, action, random.Random(0)):
                        break
                    path.append(clone['bird_row'])
                self.assertEqual(path, plan['path'])
        state = flappy.new_game(control='raw'); state['bird_row'] = 0
        self.assertIn('flap', flappy.describe(state)[1])

    def test_flight_guard_preserves_a_reachable_gap(self):
        state = flappy.new_game()
        state['pipes'] = [{'col':6, 'gap':5}]
        plans = flappy.flight_plans(state)
        self.assertNotIn('flap_flap_coast', plans)  # three safe ticks, but too high to reach this gap
        for plan in plans.values():
            clone = json.loads(json.dumps(state))
            for action in plan['actions']:
                self.assertIsNone(flappy.step_tick(clone, action, random.Random(0)))
            action = flappy.OraclePlayer().decide(clone)[0]
            self.assertIsNone(flappy.step_tick(clone, action, random.Random(0)))
            self.assertEqual(clone['passed'], 1)

    def test_flappy_model_selects_a_plan_then_applies_first_control(self):
        class Probe(flappy.Player):
            def choose(self, state, criteria):
                key = next(iter(criteria))
                return key, {key:1.0}
        state = flappy.new_game()
        action, _, _, meta = Probe().decide(state)
        plan = flappy.flight_plans(state)[meta['choice']]
        self.assertEqual(action, plan['actions'][0])
        self.assertEqual(meta['path'], plan['path'])
        self.assertTrue(meta['model_called'])


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.old_results, cls.old_trace = server.RESULTS, server.TRACES_FILE
        server.RESULTS = {g:str(Path(cls.temp.name)/f'{g}.json') for g in server.GAMES}
        server.TRACES_FILE = str(Path(cls.temp.name)/'traces.jsonl')
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.H)
        cls.url = f'http://127.0.0.1:{cls.http.server_port}'
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join()
        server.RESULTS, server.TRACES_FILE = cls.old_results, cls.old_trace
        server.ARCADE.clear(); cls.temp.cleanup()

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        with urllib.request.urlopen(urllib.request.Request(self.url+path, data=data)) as response:
            return json.load(response)

    def test_server_and_headless_use_identical_courses_and_save_once(self):
        for kind, mod in [('dino', dino), ('flappy', flappy)]:
            game = self.request(f'/api/{kind}/games', {'model':'greedy', 'seed':7})
            prefix = f'/api/{kind}/games/{game["game_id"]}'
            rng = random.Random(7)
            # Match new_game's RNG consumption before advancing the reference course.
            expected = mod.new_game(rng)
            player = mod.get_player('greedy')
            for _ in range(12):
                mod.step_tick(expected, player.decide(expected)[0], rng)
                actual = self.request(prefix+'/step', {})
                self.assertEqual(actual['state'], expected)
            while not actual['over']:
                actual = self.request(prefix+'/step', {})
            count = len(server.load_results(kind))
            again = self.request(prefix+'/step', {})
            self.assertEqual(again, actual)
            self.assertEqual(len(server.load_results(kind)), count)
            self.assertEqual(actual['result']['version'], 'arcade-v2')
            self.request(prefix+'/close', {})

    def test_rejects_invalid_modes_and_cross_game_ids(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/dino/games', {'model':'random', 'control':'magic'})
        self.assertEqual(error.exception.code, 400)
        game = self.request('/api/dino/games', {'model':'random'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(f'/api/flappy/games/{game["game_id"]}/step', {})
        self.assertEqual(error.exception.code, 404)
        self.request(f'/api/dino/games/{game["game_id"]}/close', {})

    def test_pages_and_assets_are_served(self):
        for path in ['/dino', '/dino/play', '/flappy', '/flappy/play', '/arcade.js', '/arcade.css', '/2048', '/benchmarks']:
            with urllib.request.urlopen(self.url+path) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())


class BenchmarkTests(unittest.TestCase):
    def test_random_baseline_is_reproducible(self):
        for game in benchmark.MODS:
            if game == 'chess':
                continue
            first = benchmark.play_single(game, 'random', 8)
            second = benchmark.play_single(game, 'random', 8)
            self.assertEqual(first[0], second[0])
            for key in set(first[1]) - {'ms_per_decision'}:
                self.assertEqual(first[1][key], second[1][key])

    def test_formats_and_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            for fmt in benchmark.FORMATS:
                dest = Path(temp)/f'{fmt}.json'; csv = Path(temp)/f'{fmt}.csv'
                with contextlib.redirect_stdout(io.StringIO()):
                    code = benchmark.main(['--game','dino,flappy','--players','baselines','--games','2','--format',fmt,'--no-save','--plain','--json',str(dest),'--csv',str(csv)])
                self.assertEqual(code, 0)
                records = json.loads(dest.read_text())['records']
                self.assertEqual(records[-1]['status'], 'complete')
                self.assertIn('avg_score', csv.read_text())
                summaries = [r for r in records if r['type']=='result' and r['game']=='overall']
                self.assertEqual(len(summaries), 3)

    def test_failed_player_is_excluded_but_others_continue(self):
        original = benchmark.play_single
        def broken(game, player, *args, **kwargs):
            if player == 'random':
                raise RuntimeError('test failure')
            return original(game, player, *args, **kwargs)
        run = runs.Run('dino', save=False, format='average')
        with patch.object(benchmark, 'play_single', broken), contextlib.redirect_stdout(io.StringIO()):
            with Console(plain=True) as console:
                scores, _, _ = benchmark.collect('dino', ['random','greedy'], 2, 0, console, run=run)
        self.assertEqual(list(scores), ['greedy'])
        self.assertEqual(len(console.errors), 1)
        self.assertEqual(run.records[-1]['type'], 'checkpoint')

    def test_checkpoints_survive_interrupt_and_final_rows_replace_them(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runs, 'FILE', str(Path(temp)/'runs.jsonl')):
            run = runs.Run('dino', format='average')
            run.checkpoint('greedy', avg_score=10)
            run.finish('interrupted')
            loaded = runs.load_runs()[0]
            self.assertEqual(loaded['status'], 'interrupted')
            self.assertEqual(len(loaded['results']), 1)
            run.result('greedy', avg_score=20)
            self.assertEqual(runs.load_runs()[0]['results'][0]['avg_score'], 20)
            self.assertEqual(len(runs.load_runs()[0]['results']), 1)

    def test_interactive_wizard_prints_a_repeatable_command(self):
        with patch('builtins.input', side_effect=['1', '2', 'raw']), contextlib.redirect_stdout(io.StringIO()) as output:
            args = benchmark.wizard()
        self.assertEqual(args, ['--game', 'dino,flappy', '--players', 'random', 'greedy', 'oracle', '--games', '2', '--control', 'raw'])
        self.assertIn('Repeat this run:', output.getvalue())

    def test_invalid_counts_return_cli_error(self):
        proc = subprocess.run([sys.executable, '-B', str(Path(benchmark.__file__)), '--games','0'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('must be at least 1', proc.stderr)


if __name__ == '__main__':
    unittest.main()
