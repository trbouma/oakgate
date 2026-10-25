"""Adopt the existing SQLite schema without rewriting application data."""
from alembic import op
from app.migrations.baseline import validate

revision = '0001_sqlite_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    db = connection.connection.driver_connection
    for item in validate(db, require_wallets=False):
        connection.exec_driver_sql(item['sql'])
    if validate(db, require_wallets=False):
        raise RuntimeError('Baseline incomplete')


def downgrade():
    raise RuntimeError('Baseline downgrade is deliberately disabled; do not drop custody or payment data')
