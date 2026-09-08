"""Transactional, forward-only schema upgrades with explicit compatibility checks."""
SCHEMA_VERSION = 1
TABLES = {
    'enrollments': 'hash TEXT PRIMARY KEY, expires REAL, used INTEGER DEFAULT 0',
    'devices': 'id TEXT PRIMARY KEY, hash TEXT UNIQUE, inventory TEXT, seen REAL, revoked INTEGER DEFAULT 0',
    'jobs': 'id TEXT PRIMARY KEY, device TEXT, kind TEXT, status TEXT, created REAL, lease REAL, result TEXT',
    'audit': 'id INTEGER PRIMARY KEY, time REAL, actor TEXT, action TEXT, target TEXT',
}
COLUMNS = {
    'enrollments': {'hash','expires','used'},
    'devices': {'id','hash','inventory','seen','revoked'},
    'jobs': {'id','device','kind','status','created','lease','result'},
    'audit': {'id','time','actor','action','target'},
}

def version(connection):
    value = connection.execute('PRAGMA user_version').fetchone()[0]
    if value < 0 or value > SCHEMA_VERSION:
        raise ValueError('Database version is newer than or incompatible with this Protec release')
    return value

def validate_schema(connection):
    current = version(connection)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not COLUMNS.keys() <= tables:
        raise ValueError('Source is not a complete Protec database')
    for table, required in COLUMNS.items():
        # Names come exclusively from the constant schema, never user input.
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
        if not required <= columns:
            raise ValueError('Incompatible Protec table: '+table)
    return current

def migrate(connection):
    """Caller owns the transaction context and commits or rolls back this upgrade."""
    connection.execute('BEGIN IMMEDIATE')
    current = version(connection)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if not tables:
        if current != 0:
            raise ValueError('Versioned database has no Protec tables')
        for name, definition in TABLES.items():
            connection.execute(f'CREATE TABLE {name} ({definition})')
    else:
        validate_schema(connection)
    if current == 0:
        connection.execute('CREATE INDEX IF NOT EXISTS jobs_device_status ON jobs(device,status,lease)')
        connection.execute('CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created DESC)')
        connection.execute('CREATE INDEX IF NOT EXISTS devices_seen ON devices(seen DESC)')
        connection.execute('PRAGMA user_version=1')
    validate_schema(connection)
