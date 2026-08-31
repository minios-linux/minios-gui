from pathlib import Path

import pytest


@pytest.fixture
def tmp_path(tmpdir):
    """Provide pathlib temporary paths on Bionic's pytest 3.3."""
    return Path(str(tmpdir))
