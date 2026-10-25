"""Accept only the verified, backed-up maintenance runner's transaction."""
from alembic import context

config = context.config
connection = config.attributes.get('connection')
if (connection is None or not config.attributes.get('oakgate_verified')
        or connection.dialect.name != 'sqlite' or context.is_offline_mode()):
    raise RuntimeError('Use python -m app.db_migrations; direct stamp/offline/other database commands are disabled')
context.configure(connection=connection, transactional_ddl=True, target_metadata=None)
with context.begin_transaction():
    context.run_migrations()
