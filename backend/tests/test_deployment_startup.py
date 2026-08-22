from pathlib import Path


def test_native_render_start_runs_migrations_before_uvicorn():
    script = (Path(__file__).resolve().parents[2] / "render_start.sh").read_text(
        encoding="utf-8"
    )

    migration = "python -m alembic -c alembic.ini upgrade head"
    server = "exec python -m uvicorn app.main:app"
    assert migration in script
    assert server in script
    assert script.index(migration) < script.index(server)
