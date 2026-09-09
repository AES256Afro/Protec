"""Transactional, forward-only schema upgrades with explicit compatibility checks."""
SCHEMA_VERSION = 6
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

CREDENTIAL_SCHEMA = 'id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, issued_by TEXT NOT NULL'
CREDENTIAL_COLUMNS = {'id','hash','name','role','created','expires','revoked','issued_by'}

def version(connection):
    value = connection.execute('PRAGMA user_version').fetchone()[0]
    if value < 0 or value > SCHEMA_VERSION:
        raise ValueError('Database version is newer than or incompatible with this Protec release')
    return value

def validate_schema(connection):
    current = version(connection)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required_tables = {**COLUMNS, **({'credentials':CREDENTIAL_COLUMNS | ({'device_ids'} if current>=3 else set()) | ({'replacement_id','rotation_deadline'} if current>=4 else set())} if current>=2 else {})}
    if current>=5:
        required_tables['jobs']=COLUMNS['jobs'] | {'contract_version','attempt','lease_hash','receipt','completed','issued_by'}
    if current>=6:
        required_tables['jobs'] |= {'not_before','not_after'}
    if not required_tables.keys() <= tables:
        raise ValueError('Source is not a complete Protec database')
    for table, required in required_tables.items():
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
    if current<2:
        connection.execute(f'CREATE TABLE credentials ({CREDENTIAL_SCHEMA})')
        connection.execute('PRAGMA user_version=2')
    if current<3:
        connection.execute('ALTER TABLE credentials ADD COLUMN device_ids TEXT')
        connection.execute('PRAGMA user_version=3')
    if current<4:
        connection.execute('ALTER TABLE credentials ADD COLUMN replacement_id TEXT')
        connection.execute('ALTER TABLE credentials ADD COLUMN rotation_deadline REAL')
        connection.execute('PRAGMA user_version=4')
    if current<5:
        for definition in ('contract_version INTEGER NOT NULL DEFAULT 0','attempt INTEGER NOT NULL DEFAULT 0','lease_hash TEXT','receipt TEXT','completed REAL','issued_by TEXT'):
            connection.execute('ALTER TABLE jobs ADD COLUMN '+definition)
        connection.execute('PRAGMA user_version=5')
    if current<6:
        connection.execute('ALTER TABLE jobs ADD COLUMN not_before REAL')
        connection.execute('ALTER TABLE jobs ADD COLUMN not_after REAL')
        connection.execute('PRAGMA user_version=6')
    validate_schema(connection)
