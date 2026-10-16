"""Read benchmark exports without loading the games or any model dependencies."""
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import threading
from catalog import NAMES

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 500


def number(value, default=0):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else default


def document_records(doc):
    """Accept CLI --json, grouped runs, arrays of records, and JSONL records."""
    if isinstance(doc, list):
        for item in doc:
            yield from document_records(item)
    elif isinstance(doc, dict):
        if isinstance(doc.get('records'), list):
            yield from document_records(doc['records'])
        elif isinstance(doc.get('results'), list) and doc.get('run_id'):
            yield {**doc, 'type': 'run', 'results': None}
            yield from document_records(doc['results'])
            if doc.get('status'):
                yield {'type':'status', 'run_id':doc['run_id'], 'status':doc['status'], 'finished_at':doc.get('finished_at')}
        elif doc.get('type') in ('run', 'result', 'checkpoint', 'status') and isinstance(doc.get('run_id'), str):
            if 'game' in doc and not isinstance(doc['game'],str):
                return
            if doc['type'] in ('result','checkpoint') and not isinstance(doc.get('player'),str):
                return
            if 'vs' in doc and not isinstance(doc['vs'],str):
                return
            yield doc


def read_records(path):
    def reject_constant(value):
        raise ValueError('Non-finite JSON number')
    text = path.read_text(encoding='utf-8')
    if path.suffix == '.json':
        return list(document_records(json.loads(text, parse_constant=reject_constant))), 0
    records, broken = [], 0
    decoder = json.JSONDecoder(parse_constant=reject_constant)
    for line in text.splitlines():
        line, pos = line.strip(), 0
        while pos < len(line):
            try:
                item, pos = decoder.raw_decode(line, pos)
                records.extend(document_records(item))
                while pos < len(line) and line[pos].isspace():
                    pos += 1
            except ValueError:
                broken += 1
                break  # An interrupted trailing write must not hide earlier complete records.
    return records, broken


class BenchmarkIndex:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.lock = threading.Lock()
        self.signature = None
        self.cached = {'runs': [], 'warnings': [], 'files': 0}

    def load(self):
        with self.lock:
            files, warnings = [], []
            if self.directory.is_dir():
                for path in self.directory.rglob('*'):
                    if path.suffix not in ('.json', '.jsonl') or path.is_symlink() or not path.is_file():
                        continue
                    if not path.resolve().is_relative_to(self.directory):
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    files.append((path, stat.st_mtime_ns, stat.st_size))
                    if len(files) > MAX_FILES:
                        warnings.append(f'Only the first {MAX_FILES} benchmark files are indexed.')
                        files = files[:MAX_FILES]
                        break
            signature = tuple(sorted((str(p), m, size) for p,m,size in files))
            if signature == self.signature:
                return self.cached
            runs, seen = {}, defaultdict(Counter)
            for path, _, size in sorted(files, key=lambda x:(x[1], str(x[0]))):
                source = str(path.relative_to(self.directory))
                if size > MAX_FILE_BYTES:
                    warnings.append(f'{source}: larger than the 25 MiB file limit; skipped.')
                    continue
                try:
                    records, broken = read_records(path)
                except (OSError, UnicodeError, ValueError, RecursionError):
                    warnings.append(f'{source}: could not read a benchmark export; skipped.')
                    continue
                if broken:
                    warnings.append(f'{source}: {broken} incomplete or malformed line(s) skipped.')
                counts = Counter()
                for rec in records:
                    rid = rec['run_id']
                    if not rid or len(rid) > 200:
                        continue
                    entry = runs.setdefault(rid, {'run_id':rid, 'game':'unknown', 'params':{}, 'ts':0, 'results':[], 'sources':[]})
                    if source not in entry['sources']:
                        entry['sources'].append(source)
                    signature_rec = json.dumps(rec, sort_keys=True, allow_nan=True)
                    counts[(rid, signature_rec)] += 1
                    # Logs and exports can overlap. Keep repeated chess matches inside a file,
                    # while avoiding doubling them when the same run is exported elsewhere.
                    if counts[(rid, signature_rec)] <= seen[rid][signature_rec]:
                        continue
                    if rec['type'] == 'run':
                        entry.update(game=rec.get('game','unknown'), params=rec.get('params') if isinstance(rec.get('params'),dict) else {}, ts=number(rec.get('ts')))
                    elif rec['type'] == 'status':
                        entry.update(status=rec.get('status','unfinished'), finished_at=number(rec.get('finished_at')))
                    else:
                        entry['results'].append(rec)
                for (rid,key),count in counts.items():
                    seen[rid][key] = max(seen[rid][key], count)
            output = []
            for run in runs.values():
                finals = {(r.get('game',run['game']),r.get('player')) for r in run['results'] if r['type']=='result' and not r.get('vs')}
                rows, positions = [], {}
                for rec in run['results']:
                    key = (rec.get('game',run['game']),rec.get('player'))
                    if rec['type']=='checkpoint' and key in finals:
                        continue
                    # A later final/checkpoint supersedes the earlier per-player row.
                    if not rec.get('vs'):
                        if key in positions:
                            rows[positions[key]] = rec
                        else:
                            positions[key] = len(rows); rows.append(rec)
                    else:
                        rows.append(rec)
                run['results'] = rows
                run['status'] = run.get('status') or ('unfinished' if run['params'].get('versions') else 'legacy')
                run['games'] = sorted({str(r.get('game',run['game'])) for r in rows} - {'overall','multi','unknown'})
                if not run['games'] and run['game'] not in ('multi','unknown'):
                    run['games'] = [run['game']]
                run['players'] = sorted({str(r['player']) for r in rows if r.get('player')} | {str(r['vs']) for r in rows if r.get('vs')})
                suites = run['params'].get('suites',[])
                run['expected_games'] = sorted(set(run['games']) | {g for g in (suites if isinstance(suites,list) else []) if isinstance(g,str)})
                run['format'] = run['params'].get('format') or 'unspecified'
                run['control'] = run['params'].get('control') or 'unspecified'
                run['versions'] = run['params'].get('versions') if isinstance(run['params'].get('versions'),dict) else {}
                run['legacy'] = not bool(run['versions'])
                output.append(run)
            self.signature = signature
            self.cached = {'runs':sorted(output,key=lambda r:(r['ts'],r['run_id']),reverse=True), 'warnings':warnings, 'files':len(files)}
            return self.cached


def summary(run):
    return {k:v for k,v in run.items() if k != 'results'} | {'result_count':len(run['results'])}


def filtered_runs(runs, query):
    def matches(run):
        for field in ('format','control','status'):
            if query.get(field) and run[field] != query[field]:
                return False
        if query.get('game') and query['game'] not in run['games']:
            return False
        text = ' '.join([run['run_id'], *run['players'], *run['games'], *[NAMES.get(p,p) for p in run['players']+run['games']], *map(str,run['versions'].values())]).lower()
        return query.get('q','').strip().lower() in text
    return [r for r in runs if matches(r)]
