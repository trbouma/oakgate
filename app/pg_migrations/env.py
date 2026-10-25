from alembic import context
config = context.config
connection = config.attributes.get('connection')
if (connection is None or connection.dialect.name != 'postgresql'
        or not config.attributes.get('oakgate_empty_database') or context.is_offline_mode()):
    raise RuntimeError('Use python -m app.postgres_migrations init for a new empty database')
context.configure(connection=connection, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
