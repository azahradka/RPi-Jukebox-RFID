#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Schema-vs-config drift check (Phase 6 follow-up #1).

For each plugin that declares ``plugs_config_section`` +
``plugs_config_schema`` at module top level under
``src/jukebox/components/``, grep the plugin's source tree for
``cfg.getn(SECTION, KEY, ...)`` (and ``cfg.setndefault(SECTION, KEY,
...)``) calls and assert every TOP-LEVEL ``KEY`` has a corresponding
entry in that plugin's ``plugs_config_schema``.

Why
---
The schema is the documented contract for what the plugin reads from
``jukebox.yaml``. When a developer adds a new ``cfg.getn(...)`` call
without updating the schema, three things break silently:

1. ``jukebox.plug_schema`` validation doesn't know about the new key
   and can't warn on a missing/typo'd YAML entry.
2. Operators reading the schema have a stale picture of what each
   plugin needs.
3. The drift compounds — by the time someone notices, multiple
   keys have rotted and reconstructing intent is hard.

What this script does NOT check
-------------------------------
* Nested keys beyond the second positional argument
  (``cfg.getn(SECTION, 'library', 'update_on_startup')`` is reported
  under the top-level key ``library``; the script does not require
  the schema to describe sub-keys).
* Calls that read SECTION via a dynamic key name
  (``cfg.getn(SECTION, key_var)``).
* Sections that don't declare a schema at all — that's a separate
  documentation concern.

Pre-existing drift baseline
---------------------------
At the time this check was introduced (2026-05-17), three plugins
already had pre-existing drift that lives in ``__init__.py`` files
this PR was scoped out of (post-refactor polish runs file-disjoint
from the plug-time-coupling refactor). Those (plugin, key) pairs are
listed in :data:`_BASELINE_DRIFT` — the script still REPORTS them
but does NOT exit non-zero on the baseline alone. New drift fails
CI. The baseline shrinks to empty once Phase Item 3 lands and the
listed plugins can be touched cleanly.

Usage
-----
``python tools/check_schema_coverage.py`` — exit 0 if clean, exit 1
on drift with a diff to stderr.

``python tools/check_schema_coverage.py --components-root PATH`` —
override the components tree (used by the unit test).

The check is wired into CI as a separate step in
``.github/workflows/pythonpackage_future3.yml``.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Set, Tuple


# ---------------------------------------------------------------------------
# AST scanners
# ---------------------------------------------------------------------------


def _extract_schemas(tree: ast.AST) -> Tuple[List[str], Set[str]]:
    """Return (sections, top_level_schema_keys) from a parsed plugin module.

    Looks for module-level ``plugs_config_section = [...]`` and
    ``plugs_config_schema = {...}`` assignments. Returns empty
    containers if the module declares neither.
    """
    sections: List[str] = []
    schema_keys: Set[str] = set()

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id

        if name == 'plugs_config_section' and isinstance(node.value, ast.List):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    sections.append(elt.value)

        elif name == 'plugs_config_schema' and isinstance(node.value, ast.Dict):
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    schema_keys.add(k.value)

    return sections, schema_keys


#: Names of variables that refer to the canonical ``jukebox.yaml``
#: config handler. Other handlers (``cfg_rfid`` for ``rfid.yaml``,
#: ``cfg_cards`` for ``cards.yaml``, etc.) describe their own files
#: and are NOT covered by the plugin's ``plugs_config_schema``, so
#: we skip those calls.
_JUKEBOX_CFG_VAR_NAMES = ('cfg', 'cfg_main')


#: Item 3 resolved every entry in this allowlist:
#: ``playermpd.library`` and ``playerpodcast.{episode_cache,
#: second_swipe_action}`` are now declared in their respective
#: ``plugs_config_schema``. The set is intentionally kept (rather
#: than dropping the constant) so a future regression that needs a
#: temporary baseline can be re-added with minimal churn, and so
#: ``test/tools/test_check_schema_coverage.py`` continues to
#: exercise the baseline-vs-new split path.
_BASELINE_DRIFT: frozenset = frozenset()


def _extract_cfg_keys(tree: ast.AST, sections: Iterable[str]) -> Set[str]:
    """Return the top-level KEYs read by ``cfg.getn(SECTION, KEY, ...)``.

    Also catches:
      * ``cfg.setndefault(SECTION, KEY, ...)``
      * ``cfg.setn(SECTION, KEY, ...)``

    Restrictions:
      * Receiver variable must be one of :data:`_JUKEBOX_CFG_VAR_NAMES`
        so we only count reads from the jukebox.yaml handler. Calls
        like ``cfg_rfid.getn('rfid', 'readers')`` read from rfid.yaml
        (which is not described by ``plugs_config_schema``) and would
        be a false positive.
      * SECTION must be a string literal in the plugin's declared
        sections.
      * KEY must be a string literal.
    """
    sections_set = set(sections)
    keys: Set[str] = set()

    def visit_call(node: ast.Call) -> None:
        # Match cfg.<method>(SECTION_str, KEY_str, ...)
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr not in ('getn', 'setn', 'setndefault'):
            return
        # Receiver must be a Name (skip ``self.cfg.getn`` etc.).
        receiver = node.func.value
        if not isinstance(receiver, ast.Name):
            return
        if receiver.id not in _JUKEBOX_CFG_VAR_NAMES:
            return
        args = node.args
        if len(args) < 2:
            return
        first = args[0]
        second = args[1]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            return
        if first.value not in sections_set:
            return
        if not (isinstance(second, ast.Constant) and isinstance(second.value, str)):
            return
        keys.add(second.value)

    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            visit_call(n)

    return keys


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------


@dataclass
class PluginCheck:
    """A single plugin's schema-vs-source picture."""
    plugin_dir: Path
    plugin_init: Path
    sections: List[str]
    schema_keys: Set[str]
    cfg_keys: Set[str] = field(default_factory=set)

    @property
    def missing_keys(self) -> Set[str]:
        return self.cfg_keys - self.schema_keys


def _find_plugin_inits(components_root: Path) -> List[Path]:
    """Return every ``__init__.py`` under ``components_root`` that
    contains a ``plugs_config_schema`` at the top level.

    Also includes flat module files (e.g. ``misc.py``) which can
    declare a schema. The presence of ``plugs_config_schema`` is the
    discriminator — files without it are skipped.
    """
    candidates: List[Path] = []
    for path in components_root.rglob('*.py'):
        if '__pycache__' in path.parts:
            continue
        # Cheap text grep first to avoid parsing every file.
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        if 'plugs_config_schema' in text:
            candidates.append(path)
    return candidates


def scan(components_root: Path) -> List[PluginCheck]:
    """Top-level entry point — scan the tree and return one
    ``PluginCheck`` per schema-declaring plugin."""
    results: List[PluginCheck] = []
    for init_path in _find_plugin_inits(components_root):
        src = init_path.read_text(encoding='utf-8')
        try:
            tree = ast.parse(src, filename=str(init_path))
        except SyntaxError:
            # Skip files that don't parse; the regular test suite
            # will surface those.
            continue
        sections, schema_keys = _extract_schemas(tree)
        if not sections or not schema_keys:
            continue

        check = PluginCheck(
            plugin_dir=init_path.parent,
            plugin_init=init_path,
            sections=sections,
            schema_keys=schema_keys,
        )

        # Scan every .py in the plugin's directory tree for cfg.<method>
        # calls against the plugin's declared sections.
        for src_file in check.plugin_dir.rglob('*.py'):
            if '__pycache__' in src_file.parts:
                continue
            try:
                file_src = src_file.read_text(encoding='utf-8')
                file_tree = ast.parse(file_src, filename=str(src_file))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            check.cfg_keys |= _extract_cfg_keys(file_tree, check.sections)

        results.append(check)
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_drift(checks: List[PluginCheck]) -> str:
    """Render a human-readable diff for any checks with missing keys."""
    lines: List[str] = []
    for ch in checks:
        if not ch.missing_keys:
            continue
        rel = ch.plugin_init
        lines.append(f"\n[{rel}]")
        lines.append(f"  sections: {ch.sections}")
        lines.append(f"  schema keys: {sorted(ch.schema_keys) or '(none)'}")
        for key in sorted(ch.missing_keys):
            lines.append(
                f"  schema missing {key!r} (read via "
                f"cfg.getn/setn/setndefault but not declared in plugs_config_schema)"
            )
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--components-root',
        type=Path,
        default=None,
        help='Override the components directory (defaults to repo layout).',
    )
    args = parser.parse_args(argv)

    if args.components_root is None:
        repo_root = Path(__file__).resolve().parents[1]
        components_root = repo_root / 'src' / 'jukebox' / 'components'
    else:
        components_root = args.components_root

    if not components_root.is_dir():
        print(f"components root not found: {components_root}", file=sys.stderr)
        return 2

    checks = scan(components_root)

    # Split drift into "new" (fails CI) vs "baseline" (reported only).
    new_drift: List[PluginCheck] = []
    baseline_only: List[PluginCheck] = []
    repo_jukebox = components_root.parent  # ``src/jukebox``
    for ch in checks:
        if not ch.missing_keys:
            continue
        rel = ch.plugin_init.relative_to(repo_jukebox).as_posix()
        unknown_keys = {
            key for key in ch.missing_keys
            if (rel, key) not in _BASELINE_DRIFT
        }
        if unknown_keys:
            # Build a filtered PluginCheck for clearer reporting.
            filtered = PluginCheck(
                plugin_dir=ch.plugin_dir,
                plugin_init=ch.plugin_init,
                sections=ch.sections,
                schema_keys=ch.schema_keys,
                cfg_keys=unknown_keys | ch.schema_keys,  # makes missing = unknown_keys
            )
            new_drift.append(filtered)
        else:
            baseline_only.append(ch)

    if baseline_only:
        print(
            f"INFO: {len(baseline_only)} plugin(s) have pre-existing baseline "
            f"drift (will fail CI once Phase Item 3 lands):",
            file=sys.stderr,
        )
        print(format_drift(baseline_only), file=sys.stderr)

    if new_drift:
        print("FAIL: new schema-vs-config drift detected:", file=sys.stderr)
        print(format_drift(new_drift), file=sys.stderr)
        return 1

    print(f"OK: {len(checks)} plugin schema(s) scanned; no new drift.")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
