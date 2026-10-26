"""Shared test fixtures. The repo root is on sys.path via pytest.ini (pythonpath = .)."""
import os

# Tests must never touch AWS: disable S3 persistence and the EC2 metadata lookup.
os.environ.pop("TABCOUNT_S3_BUCKET", None)
os.environ["TABCOUNT_DISABLE_IMDS"] = "1"

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from tools.synthetic import encode, grid_scene, render_scene  # noqa: E402


@pytest.fixture
def rng():
    return np.random.default_rng(1234)


@pytest.fixture
def grid12_png():
    return encode(render_scene(grid_scene(12, "dark"), np.random.default_rng(1), degrade=True))
