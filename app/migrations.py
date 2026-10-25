from sqlalchemy import text
from .db import engine, Base

VERSION = 1

def migrate():
    with engine.begin() as c:
        c.execute(text('SELECT pg_advisory_xact_lock(78345121)'))
        c.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
        c.execute(text('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())'))
        version = c.scalar(text('SELECT COALESCE(MAX(version),0) FROM schema_version'))
        if version > VERSION:
            raise RuntimeError('Database is newer than this application; upgrade the application.')
        if version < 1:
            Base.metadata.create_all(c)
            c.execute(text('''CREATE FUNCTION deny_audit_mutation() RETURNS trigger AS $$
                BEGIN RAISE EXCEPTION 'Audit entries are append only'; END; $$ LANGUAGE plpgsql'''))
            c.execute(text('CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit FOR EACH ROW EXECUTE FUNCTION deny_audit_mutation()'))
            c.execute(text('INSERT INTO schema_version(version) VALUES(1)'))
