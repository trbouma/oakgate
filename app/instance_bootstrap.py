"""Fresh-instance DB setup, invoked explicitly by init-instance with secrets on stdin.

Never imports app.main, initializes a wallet, migrates existing data or starts workers.
"""
import json
import re
import secrets
import sys
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from sqlalchemy import text

from app.database import postgres_engine
from app.postgres_migrations import initialize, verify
from app.postgres_schema import metadata


def provision(config, *, connect=psycopg.connect, initialize_schema=initialize, engine_factory=postgres_engine):
    admin=config['OAKGATE_POSTGRES_PASSWORD']
    kc=config['KEYCLOAK_POSTGRES_PASSWORD']
    parsed=urlsplit(config['OAKGATE_DATABASE_URL'])
    runtime=parsed.password
    if any(not re.fullmatch('[0-9a-f]{64}',v or '') for v in (admin,kc,runtime)):
        raise ValueError('Invalid generated secret format')
    if (parsed.scheme!='postgresql+psycopg' or parsed.hostname!='postgres' or parsed.port!=5432
            or parsed.username!='oakgate_runtime' or parsed.path!='/oakgate' or parsed.query or parsed.fragment):
        raise ValueError('Unexpected runtime target')
    migration=secrets.token_hex(32)
    with connect(host='postgres',dbname='oakgate',user='oakgate_admin',password=admin,connect_timeout=5,autocommit=True) as db:
        with db.transaction():
            db.execute('SELECT pg_advisory_xact_lock(73020261025)')
            if db.execute("SELECT 1 FROM pg_tables WHERE schemaname='public'").fetchone():
                raise ValueError('Existing schema refused')
            if db.execute("SELECT 1 FROM pg_roles WHERE rolname IN ('oakgate_runtime','oakgate_migrator','keycloak')").fetchone():
                raise ValueError('Existing roles refused')
            if db.execute("SELECT 1 FROM pg_database WHERE datname='keycloak'").fetchone():
                raise ValueError('Existing Keycloak database refused')
            for name,password in (('oakgate_runtime',runtime),('oakgate_migrator',migration),('keycloak',kc)):
                db.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(name),sql.Literal(password)))
            db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
            db.execute('GRANT USAGE, CREATE ON SCHEMA public TO oakgate_migrator')
            db.execute('GRANT USAGE ON SCHEMA public TO oakgate_runtime')
        # CREATE DATABASE cannot run inside a transaction. Partial failure is not retried.
        db.execute("CREATE DATABASE keycloak OWNER keycloak ENCODING 'UTF8' TEMPLATE template0")
        url='postgresql+psycopg://oakgate_migrator:'+migration+'@postgres:5432/oakgate'
        initialize_schema(url)
        for table in metadata.tables:
            db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE public.{} TO oakgate_runtime').format(sql.Identifier(table)))
        db.execute('GRANT SELECT ON public.alembic_version TO oakgate_runtime')
        db.execute('GRANT USAGE ON SEQUENCE public.pos_audit_id_seq TO oakgate_runtime')
        db.execute('ALTER ROLE oakgate_migrator NOLOGIN PASSWORD NULL')
    with connect(host='postgres',dbname='keycloak',user='oakgate_admin',password=admin,connect_timeout=5) as db:
        db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        db.execute('GRANT USAGE,CREATE ON SCHEMA public TO keycloak')
    engine=engine_factory(config['OAKGATE_DATABASE_URL'])
    try:
        with engine.connect() as connection: verify(connection,runtime=True)
    finally: engine.dispose()


def main():
    try: provision(json.load(sys.stdin))
    except Exception:
        print('Fresh database provisioning failed. Keep services/state for inspection; never reset or retry against existing data.',file=sys.stderr)
        raise SystemExit(1)
    print('Fresh schemas and restricted runtime role ready. No wallet operations performed.')


if __name__=='__main__': main()
