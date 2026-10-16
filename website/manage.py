"""Host-only submission review. No public admin endpoint or admin password required."""
import argparse
import json
import os
from pathlib import Path
from submissions import STATUSES, SubmissionStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    listing = commands.add_parser('list'); listing.add_argument('--status',choices=STATUSES)
    show = commands.add_parser('show'); show.add_argument('reference')
    update = commands.add_parser('status'); update.add_argument('reference'); update.add_argument('status',choices=STATUSES); update.add_argument('--note',default='')
    export = commands.add_parser('export'); export.add_argument('--output',required=True)
    backup = commands.add_parser('backup'); backup.add_argument('--output',required=True)
    args = parser.parse_args()
    store = SubmissionStore(os.environ.get('DATA_DIR',str(Path(__file__).resolve().parent/'data')))
    if args.command=='status':
        if not store.update(args.reference,args.status,args.note):
            parser.error('Reference not found')
        print(f'{args.reference}: {args.status}')
    elif args.command=='list':
        rows = store.all(args.status)
        for row in rows:
            print(json.dumps({k:row[k] for k in ('id','created_at','status','kind','name')},ensure_ascii=False))
        print(f'{len(rows)} suggestion(s)')
    elif args.command=='show':
        row = next((r for r in store.all() if r['id']==args.reference),None)
        if row is None:
            parser.error('Reference not found')
        print(json.dumps(row,indent=2,ensure_ascii=False))
    elif args.command=='backup':
        import sqlite3
        target=Path(args.output)
        if target.resolve()==store.path.resolve() or target.exists():
            parser.error('Choose a new backup filename outside the live database files')
        target.parent.mkdir(parents=True,exist_ok=True)
        with store.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        print(f'Consistent database backup saved to {target}')
    else:
        Path(args.output).write_text(json.dumps(store.all(),indent=2,ensure_ascii=False)+'\n')
        print(f'Exported to {args.output}')


if __name__=='__main__':
    main()
