# -*- coding: utf-8 -*-
"""Tests for ``tools/check_schema_coverage.py`` (Phase 6 FU#1).

The check itself is straightforward AST scanning. These tests prove:

1. A clean fixture plugin (every cfg.getn key in the schema) yields
   zero drift.
2. A drifted fixture plugin (cfg.getn for a key NOT in the schema)
   surfaces the missing key with a clear message.
3. The receiver-name guard filters out alt-handler calls (``cfg_rfid.getn``)
   so they don't masquerade as drift on the main schema.
4. The check exits non-zero with a non-baseline missing key.
5. ``main()`` returns 0 when the baseline matches exactly.

The CI step calls ``main()`` with the real repo layout; if a future
plugin __init__.py adds a new ``cfg.getn(...)`` without updating the
schema, CI fails with a unicast diff.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _REPO_ROOT / 'tools'
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import check_schema_coverage as csc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_plugin(plugin_root: Path, init_body: str, extra_files: dict | None = None) -> None:
    """Materialise a plugin directory with the given __init__.py body."""
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / '__init__.py').write_text(textwrap.dedent(init_body))
    for rel, body in (extra_files or {}).items():
        target = plugin_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_clean_plugin_has_no_drift(tmp_path):
    """Schema covers every key the plugin reads → no drift."""
    components = tmp_path / 'components'
    _write_plugin(
        components / 'clean_plugin',
        """
        plugs_config_section = ['clean_plugin']
        plugs_config_schema = {
            'foo': str,
            'bar': dict,
        }

        cfg = None  # placeholder; the scanner only reads literals
        def _doit():
            cfg.getn('clean_plugin', 'foo')
            cfg.setndefault('clean_plugin', 'bar', value={})
        """,
    )
    checks = csc.scan(components)
    assert len(checks) == 1
    assert checks[0].missing_keys == set(), (
        f"unexpected drift: {checks[0].missing_keys}"
    )


def test_drifted_plugin_surfaces_missing_key(tmp_path):
    """A cfg.getn key not in the schema must appear in missing_keys."""
    components = tmp_path / 'components'
    _write_plugin(
        components / 'drifted_plugin',
        """
        plugs_config_section = ['drifted_plugin']
        plugs_config_schema = {
            'declared': str,
        }

        cfg = None
        def _doit():
            cfg.getn('drifted_plugin', 'declared')
            cfg.getn('drifted_plugin', 'undeclared')
        """,
    )
    checks = csc.scan(components)
    assert len(checks) == 1
    assert checks[0].missing_keys == {'undeclared'}


def test_alt_handler_calls_are_ignored(tmp_path):
    """``cfg_rfid.getn(...)`` reads a different YAML file and must
    NOT be flagged against ``plugs_config_schema`` (which describes
    only the jukebox.yaml section).

    Reversion check: drop the receiver-name guard in
    ``_extract_cfg_keys`` and this test fails because the
    ``cfg_other`` call would be counted.
    """
    components = tmp_path / 'components'
    _write_plugin(
        components / 'alt_handler_plugin',
        """
        plugs_config_section = ['alt_handler_plugin']
        plugs_config_schema = {
            'declared': str,
        }

        cfg = None
        cfg_other = None
        def _doit():
            cfg.getn('alt_handler_plugin', 'declared')
            # This call reads a different YAML file; it must be ignored.
            cfg_other.getn('alt_handler_plugin', 'undeclared_in_other_yaml')
        """,
    )
    checks = csc.scan(components)
    assert len(checks) == 1
    assert checks[0].missing_keys == set(), (
        f"alt handler call leaked into drift report: {checks[0].missing_keys}"
    )


def test_multi_file_plugin_aggregates_keys(tmp_path):
    """cfg.getn calls in sibling .py files inside the plugin dir count."""
    components = tmp_path / 'components'
    _write_plugin(
        components / 'multi_plugin',
        """
        plugs_config_section = ['multi_plugin']
        plugs_config_schema = {
            'declared': str,
        }
        """,
        extra_files={
            'helper.py': """
                cfg = None
                def _doit():
                    cfg.getn('multi_plugin', 'undeclared_helper_key')
            """,
        },
    )
    checks = csc.scan(components)
    assert len(checks) == 1
    assert checks[0].missing_keys == {'undeclared_helper_key'}


def test_format_drift_human_readable(tmp_path):
    """The diff message must name the plugin and the missing key."""
    components = tmp_path / 'components'
    _write_plugin(
        components / 'drift_plugin',
        """
        plugs_config_section = ['drift_plugin']
        plugs_config_schema = {'declared': str}
        cfg = None
        def _doit():
            cfg.getn('drift_plugin', 'missing_one')
        """,
    )
    checks = csc.scan(components)
    msg = csc.format_drift(checks)
    assert 'drift_plugin' in msg
    assert "schema missing 'missing_one'" in msg


def test_main_exits_zero_on_real_repo():
    """Against the real repo layout, ``main()`` must succeed (the
    pre-existing drift is in the baseline)."""
    assert csc.main([]) == 0


def test_main_exits_nonzero_on_new_drift(tmp_path, capsys):
    """A fixture tree with new drift must exit non-zero."""
    components = tmp_path / 'components'
    _write_plugin(
        components / 'rotten',
        """
        plugs_config_section = ['rotten']
        plugs_config_schema = {'declared': str}
        cfg = None
        def _doit():
            cfg.getn('rotten', 'declared')
            cfg.getn('rotten', 'this_is_new_drift')
        """,
    )
    rc = csc.main(['--components-root', str(components)])
    captured = capsys.readouterr()
    assert rc == 1
    assert 'this_is_new_drift' in captured.err


def test_baseline_drift_is_suppressed_to_info(tmp_path, capsys, monkeypatch):
    """A baseline-listed entry must not fail CI but must be reported."""
    # Reproduce a baseline-style structure.
    components = tmp_path / 'components'
    _write_plugin(
        components / 'playermpd',
        """
        plugs_config_section = ['playermpd']
        plugs_config_schema = {'host': str}
        cfg = None
        def _doit():
            cfg.getn('playermpd', 'host')
            cfg.getn('playermpd', 'library', 'update_on_startup')
        """,
    )
    # The baseline references the real-repo path; rather than mutate
    # the production set, we add the fixture-relative path temporarily.
    fake_baseline = csc._BASELINE_DRIFT | {('components/playermpd/__init__.py', 'library')}
    monkeypatch.setattr(csc, '_BASELINE_DRIFT', fake_baseline)

    rc = csc.main(['--components-root', str(components)])
    captured = capsys.readouterr()
    assert rc == 0, (
        f"expected exit 0 because the only drift is baseline; got {rc}.\n"
        f"stderr: {captured.err}\nstdout: {captured.out}"
    )
    assert 'pre-existing baseline drift' in captured.err
    assert "'library'" in captured.err
