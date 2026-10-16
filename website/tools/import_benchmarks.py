"""Copy existing benchmark exports into the site's mounted data directory."""
import argparse
from pathlib import Path
import shutil
import tempfile
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from benchmarks import MAX_FILE_BYTES, read_records

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+',type=Path,help='JSON/JSONL files or benchmark directories')
    parser.add_argument('--destination',type=Path,default=Path(__file__).resolve().parents[1]/'benchmark-data')
    args = parser.parse_args()
    args.destination.mkdir(parents=True,exist_ok=True)
    count=0
    for source in args.sources:
        if not source.exists():
            parser.error(f'Source not found: {source}')
        files=sorted(source.rglob('*')) if source.is_dir() else [source]
        for path in files:
            if path.is_symlink() or not path.is_file() or path.suffix not in ('.json','.jsonl'):
                continue
            if path.resolve().is_relative_to(args.destination.resolve()):
                continue
            try:
                if path.stat().st_size>MAX_FILE_BYTES or not read_records(path)[0]:
                    print(f'Skipped non-benchmark or oversized file: {path}')
                    continue
            except (OSError,UnicodeError,ValueError,RecursionError):
                print(f'Skipped unreadable benchmark file: {path}')
                continue
            relative=path.relative_to(source) if source.is_dir() else Path('archive.jsonl' if path.name=='bench_runs.jsonl' else path.name)
            target=args.destination/relative
            if path.resolve()==target.resolve():
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as temp:
                temp_path=Path(temp.name)
                with path.open('rb') as original:
                    shutil.copyfileobj(original,temp)
            temp_path.chmod(0o644)
            temp_path.replace(target)
            print(f'Imported {path} -> {target}')
            count+=1
    print(f'{count} file(s) imported. Refresh the benchmark archive; no rebuild is needed.')

if __name__=='__main__':
    main()
