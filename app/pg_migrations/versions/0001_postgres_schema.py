"""Initial PostgreSQL schema; no import or payment operations."""
from alembic import op
from app.postgres_schema import metadata
revision = '0001_postgres_schema'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=False)

def downgrade():
    raise RuntimeError('Dropping custodial data requires an explicit recovery plan')
