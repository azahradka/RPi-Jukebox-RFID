# -*- coding: utf-8 -*-
"""Shared test configuration for playermpd tests (Phase 3a).

Loads the extracted ``state_store`` and ``mpd_client`` modules without
executing ``components.playermpd/__init__.py`` (which wires plugs and
demands MPD at import time). The top-level ``test/conftest.py`` already
provides ``FakeMPDClient``, ``FakePlugs``, and ``tmp_state_dir`` fixtures
which we reuse here.

The trick: register a do-nothing parent package
``components.playermpd`` in ``sys.modules`` *before* importing the
sub-modules so Python's relative-import machinery is satisfied without
running the real ``__init__.py``. Tests of the full plugin (which only
exist as source-grep checks in ``test_state_lock.py``) still work because
they do not import the package.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_JUKEBOX_SRC = Path(__file__).resolve().parents[2].parent / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


# ---------------------------------------------------------------------------
# Real ``jukebox.utils.atomic_io`` — without booting ``jukebox.utils``
# ---------------------------------------------------------------------------
# ``jukebox/utils/__init__.py`` pulls ``components.rpc_command_alias`` and
# subprocess helpers at import time (used by the CLI / RPC tool). For unit
# tests of ``state_store`` we only need ``atomic_write_json_safe``. Install
# the atomic_io module under its canonical name *before* anything else
# triggers ``import jukebox.utils``.
def _install_atomic_io_module():
    qual = 'jukebox.utils.atomic_io'
    if qual in sys.modules:
        return
    # Set up stub parents so ``import jukebox.utils.atomic_io`` resolves
    # without executing the real ``jukebox.utils.__init__``.
    if 'jukebox' not in sys.modules:
        jb = types.ModuleType('jukebox')
        jb.__path__ = [str(_JUKEBOX_SRC / 'jukebox')]
        sys.modules['jukebox'] = jb
    if 'jukebox.utils' not in sys.modules:
        ju = types.ModuleType('jukebox.utils')
        ju.__path__ = [str(_JUKEBOX_SRC / 'jukebox' / 'utils')]
        sys.modules['jukebox.utils'] = ju

    spec = importlib.util.spec_from_file_location(
        qual,
        _JUKEBOX_SRC / 'jukebox' / 'utils' / 'atomic_io.py',
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qual] = mod
    spec.loader.exec_module(mod)


_install_atomic_io_module()


def _load_submodule(qualname: str, file_path: Path):
    """Load a submodule file as ``qualname`` without executing the parent
    package's ``__init__.py``.

    The first call also installs a minimal stub ``components.playermpd``
    parent in ``sys.modules`` so relative imports from the submodule
    (if any) resolve, and so re-imports under the canonical dotted name
    return our loaded module.
    """
    pkg_name = qualname.rsplit('.', 1)[0]
    if pkg_name not in sys.modules:
        parent_qual = pkg_name.rsplit('.', 1)[0]
        if parent_qual and parent_qual not in sys.modules:
            sys.modules[parent_qual] = types.ModuleType(parent_qual)
        stub = types.ModuleType(pkg_name)
        stub.__path__ = [str(file_path.parent)]
        sys.modules[pkg_name] = stub

    if qualname in sys.modules:
        return sys.modules[qualname]

    spec = importlib.util.spec_from_file_location(qualname, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod
    spec.loader.exec_module(mod)
    return mod


_PLAYERMPD_DIR = _JUKEBOX_SRC / 'components' / 'playermpd'


@pytest.fixture
def state_store_module():
    """Provide the ``components.playermpd.state_store`` module."""
    return _load_submodule(
        'components.playermpd.state_store',
        _PLAYERMPD_DIR / 'state_store.py',
    )


@pytest.fixture
def mpd_client_module():
    """Provide the ``components.playermpd.mpd_client`` module."""
    return _load_submodule(
        'components.playermpd.mpd_client',
        _PLAYERMPD_DIR / 'mpd_client.py',
    )
