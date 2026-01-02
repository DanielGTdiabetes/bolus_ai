import pytest
from datetime import datetime, timedelta
from types import SimpleNamespace

import app.bot.user_settings_resolver as user_settings_resolver
from app.bot.user_settings_resolver import resolve_bot_user_settings
from app.core import config
from app.core import db as core_db
from app.models.settings import UserSettings, UserSettingsDB
from app.services.store import DataStore


@pytest.mark.asyncio
async def test_resolver_prefers_non_default_settings_over_admin(monkeypatch):
    pytest.importorskip("aiosqlite")

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: WPS433
    from sqlalchemy.pool import StaticPool  # noqa: WPS433

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(core_db.Base.metadata.create_all)

    now = datetime.utcnow()
    try:
        async with Session() as session:
            admin_defaults = UserSettings.default().model_dump()
            session.add(
                UserSettingsDB(
                    user_id="admin",
                    settings=admin_defaults,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )

            custom_settings = UserSettings.default()
            custom_settings.targets.mid = 110
            session.add(
                UserSettingsDB(
                    user_id="primary",
                    settings=custom_settings.model_dump(),
                    version=2,
                    created_at=now + timedelta(minutes=1),
                    updated_at=now + timedelta(minutes=5),
                )
            )
            await session.commit()

        monkeypatch.setattr(user_settings_resolver, "get_engine", lambda: engine)
        monkeypatch.setattr(config, "get_bot_default_username", lambda: "admin")

        resolved_settings, resolved_user = await resolve_bot_user_settings()

        assert resolved_user == "primary"
        assert resolved_settings.targets.mid == 110
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resolver_reads_file_store_when_no_db(monkeypatch, tmp_path):
    file_settings = UserSettings.default()
    file_settings.targets.mid = 115

    store = DataStore(tmp_path)
    store.save_settings(file_settings, username="file_user")

    fake_settings = SimpleNamespace(data=SimpleNamespace(data_dir=str(tmp_path)))
    monkeypatch.setattr(user_settings_resolver, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(user_settings_resolver, "get_engine", lambda: None)
    monkeypatch.setattr(config, "get_bot_default_username", lambda: "file_user")

    resolved_settings, resolved_user = await resolve_bot_user_settings()

    assert resolved_user == "file_user"
    assert resolved_settings.targets.mid == 115
