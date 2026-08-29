import re
from pathlib import Path


def _service_block(compose: str, service: str) -> str:
    marker = f"\n  {service}:\n"
    start = compose.index(marker) + len(marker)
    remainder = compose[start:]
    next_service = re.search(r"\n  [a-zA-Z0-9_-]+:\n", remainder)
    return remainder[: next_service.start()] if next_service else remainder


def test_critical_nas_services_restart_after_power_loss():
    compose = (
        Path(__file__).resolve().parents[2] / "deploy" / "nas" / "docker-compose.yml"
    ).read_text(encoding="utf-8")

    for service in ("backend", "db", "backup"):
        assert "restart: always" in _service_block(compose, service)
