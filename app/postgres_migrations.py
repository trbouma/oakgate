"""Initialize/check an empty PostgreSQL target, without importing live data."""
import argparse
import os
from pathlib import Path
import re

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import postgres_engine, WRITE_LOCK
from app.db_diagnostics import SchemaValidationError, diagnostic
from app.postgres_schema import metadata

REVISION = '0001_postgres_schema'


def normalized(value):
    value = re.sub(r'::[a-z ]+|[()\s]', '', '' if value is None else str(value)).lower()
    return re.sub(r'(\w+)in([0-9,]+)', r'\1=anyarray[\2]', value)


def verify(connection, *, runtime=False):
    inspector = inspect(connection)
    if connection.execute(text('SHOW server_encoding')).scalar_one() != 'UTF8':
        raise SchemaValidationError('PostgreSQL must use UTF8 encoding')
    if inspector.get_view_names(schema='public') or connection.execute(text("SELECT EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal)")).scalar_one():
        raise SchemaValidationError('Unexpected PostgreSQL views or triggers')
    if set(inspector.get_table_names(schema='public')) != set(metadata.tables) | {'alembic_version'}:
        raise SchemaValidationError('Missing or unexpected PostgreSQL tables')
    if connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all() != [REVISION]:
        raise SchemaValidationError('PostgreSQL revision mismatch')
    for table in metadata.tables.values():
        columns = inspector.get_columns(table.name, schema='public')
        if [c['name'] for c in columns] != list(table.columns.keys()):
            raise SchemaValidationError('PostgreSQL column mismatch: ' + table.name)
        for actual, expected in zip(columns, table.columns):
            if (str(actual['type'].compile(dialect=connection.dialect)) != str(expected.type.compile(dialect=connection.dialect))
                    or actual['nullable'] != expected.nullable):
                raise SchemaValidationError('PostgreSQL type/nullability mismatch: ' + table.name)
            if expected.identity is not None:
                if actual.get('identity') is None:
                    raise SchemaValidationError('Missing audit identity sequence')
            elif normalized(actual.get('default')) != normalized(expected.server_default.arg if expected.server_default else None):
                raise SchemaValidationError('PostgreSQL default mismatch: ' + table.name)
        if inspector.get_pk_constraint(table.name, schema='public')['constrained_columns'] != [c.name for c in table.primary_key]:
            raise SchemaValidationError('PostgreSQL primary key mismatch')
        from sqlalchemy import UniqueConstraint, CheckConstraint
        expected_unique = sorted(tuple(c.name for c in x.columns) for x in table.constraints if isinstance(x, UniqueConstraint))
        actual_unique = sorted(tuple(x['column_names']) for x in inspector.get_unique_constraints(table.name, schema='public'))
        if actual_unique != expected_unique:
            raise SchemaValidationError('PostgreSQL uniqueness mismatch: ' + table.name)
        checks = sorted(normalized(x.sqltext) for x in table.constraints if isinstance(x, CheckConstraint))
        if sorted(normalized(x['sqltext']) for x in inspector.get_check_constraints(table.name, schema='public')) != checks:
            raise SchemaValidationError('PostgreSQL check constraint mismatch: ' + table.name)
        indexes = {x['name']: x for x in inspector.get_indexes(table.name, schema='public') if not x.get('duplicates_constraint')}
        if set(indexes) != {x.name for x in table.indexes}:
            raise SchemaValidationError('PostgreSQL index mismatch: ' + table.name)
        for index in table.indexes:
            actual = indexes[index.name]
            if (actual['column_names'] != [c.name for c in index.columns] or actual['unique'] != index.unique
                    or normalized(actual.get('dialect_options', {}).get('postgresql_where')) != normalized(index.dialect_options['postgresql']['where'])):
                raise SchemaValidationError('PostgreSQL index definition mismatch: ' + index.name)
    if runtime:
        unsafe = connection.execute(text("SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls OR has_schema_privilege(current_user,'public','CREATE') FROM pg_roles WHERE rolname=current_user")).scalar_one()
        unsafe = unsafe or connection.execute(text("SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','S') AND pg_has_role(current_user,c.relowner,'USAGE'))")).scalar_one()
        if unsafe:
            raise SchemaValidationError('Use a restricted PostgreSQL runtime role, not the migration administrator')
        if not connection.execute(text("SELECT has_table_privilege(current_user,'public.alembic_version','SELECT')")).scalar_one():
            raise SchemaValidationError('Runtime revision read grant missing')
        for table in metadata.tables:
            if not connection.execute(text("SELECT has_table_privilege(current_user,:name,'SELECT') AND has_table_privilege(current_user,:name,'INSERT') AND has_table_privilege(current_user,:name,'UPDATE') AND has_table_privilege(current_user,:name,'DELETE')"), {'name': 'public.'+table}).scalar_one():
                raise SchemaValidationError('Runtime table grants missing')
        if not connection.execute(text("SELECT has_sequence_privilege(current_user,'public.pos_audit_id_seq','USAGE')")).scalar_one():
            raise SchemaValidationError('Runtime sequence grant missing')


def initialize(url):
    engine = postgres_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': WRITE_LOCK})
            if inspect(connection).get_table_names(schema='public') or inspect(connection).get_view_names(schema='public'):
                raise SchemaValidationError('PostgreSQL target must be empty; no existing tables will be replaced')
            cfg = Config()
            cfg.set_main_option('script_location', str(Path(__file__).parent / 'pg_migrations'))
            cfg.attributes.update(connection=connection, oakgate_empty_database=True)
            command.upgrade(cfg, REVISION)
            verify(connection)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'check', 'check-runtime'])
    args = parser.parse_args()
    # No URL command argument, so credentials aren't placed in shell history/process args.
    url = os.getenv('OAKGATE_DATABASE_URL' if args.action == 'check-runtime' else 'OAKGATE_MIGRATION_DATABASE_URL', '')
    phase = 'configuration'
    try:
        if args.action == 'init':
            phase = 'initialization'
            initialize(url)
        else:
            engine = postgres_engine(url)
            try:
                phase = 'connection'
                with engine.connect() as connection:
                    phase = 'schema_and_permissions'
                    verify(connection, runtime=args.action == 'check-runtime')
            finally:
                engine.dispose()
    except Exception as error:
        parser.exit(1, 'PostgreSQL schema operation refused: ' + diagnostic(error, phase) + '\nNo automatic retry.\n')
    print('PostgreSQL schema verified: ' + REVISION + '. No application rows changed.')

if __name__ == '__main__':
    main()
