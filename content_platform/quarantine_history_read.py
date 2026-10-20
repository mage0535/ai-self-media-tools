"""Bounded query-only access to retained historical records, never a replay entry."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3


def read(database, table=None, limit=100):
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('bounded_history_query_required')
    path=Path(database)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():raise ValueError('existing_history_database_required')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as c:
        c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
        where=' WHERE source_table=?' if table else ''
        params=(table,limit) if table else (limit,)
        return [dict(r) for r in c.execute('SELECT orphan_record_id,source_table,source_rowid,reason_code,parent_table,record_sha256,replay_allowed FROM media_migration_orphan_records'+where+' ORDER BY orphan_record_id LIMIT ?',params)]


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database',required=True);p.add_argument('--table');p.add_argument('--limit',type=int,default=100)
    a=p.parse_args();print(json.dumps(read(a.database,a.table,a.limit),ensure_ascii=False))
