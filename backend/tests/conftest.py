import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from factories.factory import create_app
from fakes import build_test_services, write_test_data_root

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


@pytest.fixture
def test_data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    write_test_data_root(root)
    return root


@pytest.fixture
def app_settings(test_data_root: Path) -> Settings:
    # _env_file=None: a developer's .env must not change test behaviour.
    # TestClient reports the client host "testclient", which is not a loopback address; the
    # local-only guard has its own tests.
    return Settings(
        _env_file=None, data_root=test_data_root, log_dir=None, allow_remote_clients=True
    )


@pytest.fixture
def client(app_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(create_app(app_settings, build_test_services)) as test_client:
        yield test_client
