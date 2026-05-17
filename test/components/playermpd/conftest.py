# -*- coding: utf-8 -*-
"""Shared test configuration for playermpd tests.

After Item 3 (plug-time-coupling refactor) the parent package
``components.playermpd`` is import-safe — its ``__init__.py`` is
purely declarative. Tests can therefore ``import
components.playermpd.state_store`` / ``mpd_client`` directly, and the
previous ``_load_submodule`` importlib-stub indirection (Phase 3a
era) is gone.

The top-level ``test/conftest.py`` still provides the
``FakeMPDClient``, ``FakePlugs`` and ``tmp_state_dir`` fixtures that
these tests use.
"""

import sys
from pathlib import Path

import pytest

_JUKEBOX_SRC = Path(__file__).resolve().parents[2].parent / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


@pytest.fixture
def state_store_module():
    """Provide the ``components.playermpd.state_store`` module."""
    import components.playermpd.state_store as ss
    return ss


@pytest.fixture
def mpd_client_module():
    """Provide the ``components.playermpd.mpd_client`` module."""
    import components.playermpd.mpd_client as mc
    return mc
