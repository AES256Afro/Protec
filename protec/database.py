"""SQLite backup and restore to a new destination; never replace live data."""
import argparse
import os
from pathlib import Path
import sqlite3
import tempfile

REQUIRED = {'devices','enrollments','jobs','audit'}

def validate(connection):
    result = connection.execute('PRAGMA integrity_check').fetchall()
    if result != [('ok',)]:
        raise ValueError('Database integrity check failed')
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not REQUIRED.issubset(tables):
        raise ValueError('Source is not a Protec database')
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version > 1:
        raise ValueError('Database version is newer than this Protec release')

def copy_database(source, destination):
    """Snapshot a live SQLite source, validate it, then atomically create destination."""
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if source == destination.resolve() or destination.exists() or destination.is_symlink():
        raise ValueError('Destination must be a new file; existing files are never replaced')
    if not destination.parent.is_dir():
        raise ValueError('Destination directory must already exist')
    fd, temporary = tempfile.mkstemp(prefix='.protec-backup-',dir=destination.parent)
    os.close(fd)
    try:
        # mode=ro prevents an accidental empty source database from being created.
        origin = sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=10)
        target = sqlite3.connect(temporary)
        try:
            origin.backup(target,pages=256,sleep=0.1)
            validate(target)
        finally:
            target.close()
            origin.close()
        with open(temporary,'rb') as file:
            os.fsync(file.fileno())
        # Hard-link creation is atomic and fails if another process created destination.
        os.link(temporary,destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['backup','restore'])
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args = parser.parse_args()
    try:
        destination = copy_database(args.source,args.destination)
    except (OSError,ValueError,sqlite3.Error) as error:
        raise SystemExit(f'{args.operation.capitalize()} failed: {error}')
    print(f'Validated database written to {destination}')
    if args.operation=='restore':
        print('Restore is staged. Stop the control plane before selecting this database for use.')
    print('Administrator token and agent credential files are separate and are not included.')

if __name__=='__main__':
    main()
