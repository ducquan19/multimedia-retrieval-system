import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from main import create_app

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SESSION_TEMP_ROOT: Path | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Use an isolated writable temp directory for each pytest process."""

    global _SESSION_TEMP_ROOT
    if config.getoption("basetemp") is None:
        _SESSION_TEMP_ROOT = Path(tempfile.mkdtemp(prefix=".pytest-tmp-", dir=_REPOSITORY_ROOT))
        config.option.basetemp = str(_SESSION_TEMP_ROOT / "run")


def pytest_unconfigure(config: pytest.Config) -> None:
    """Best-effort cleanup of this process's isolated temp directory."""

    del config
    if _SESSION_TEMP_ROOT is not None:
        shutil.rmtree(_SESSION_TEMP_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return _REPOSITORY_ROOT


@pytest.fixture
def app_settings(repository_root: Path) -> Settings:
    return Settings(data_root=repository_root / "data")


@pytest.fixture
def client(app_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(create_app(app_settings)) as test_client:
        yield test_client
