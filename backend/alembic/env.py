import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import your models
from app.core.db import Base
# Import models to ensure they are registered
from app.models import settings, treatment, suggestion, user_data, temp_mode, draft_db

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# ----------------ADDED FOR RENDER----------------
# Iterate DB URL from Environment if present
import os
db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Ensure correct driver for asyncpg
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    config.set_main_option("sqlalchemy.url", db_url)
# ------------------------------------------------


# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    
    # Handle sync sqlite URL fallback for autogen
    url = config.get_main_option("sqlalchemy.url")
    if url and url.startswith("sqlite://") and "aiosqlite" not in url:
         from sqlalchemy import engine_from_config
         connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
         with connectable.connect() as connection:
            connection.run_callable(do_run_migrations)
         return

    
    # Clean sslmode from URL for asyncpg and pass as connect_args
    section = config.get_section(config.config_ini_section, {})
    connect_args = {}
    
    # If the URL in the config has sslmode, we need to strip it and move it to connect_args
    # This is because asyncpg via SQLAlchemy doesn't support sslmode in the query string well.
    current_url = section.get("sqlalchemy.url")
    if current_url and "sslmode" in current_url:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        
        # Parse URL
        u = urlparse(current_url)
        q = parse_qs(u.query)
        
        if "sslmode" in q:
            mode = q.pop("sslmode")[0] # parse_qs returns list
            if mode == "require" or mode == "verify-full":
                connect_args["ssl"] = "require"
            elif mode == "disable":
                connect_args["ssl"] = False
            
            # Reconstruct URL without sslmode
            new_query = urlencode(q, doseq=True)
            u = u._replace(query=new_query)
            section["sqlalchemy.url"] = urlunparse(u)

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
