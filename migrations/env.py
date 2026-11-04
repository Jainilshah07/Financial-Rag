from alembic import context
from sqlalchemy import create_engine

from financial_rag.config import settings
from financial_rag.db import Base

target_metadata = Base.metadata

if context.is_offline_mode():
    # `alembic upgrade head --sql` prints the SQL without connecting
    context.configure(url=settings.database_url or "postgresql+psycopg://", target_metadata=target_metadata,
                      literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set in .env")
    with create_engine(settings.database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
