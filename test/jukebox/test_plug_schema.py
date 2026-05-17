# -*- coding: utf-8 -*-
"""Tests for :mod:`jukebox.plug_schema`.

Phase 6: per-plugin config schema validation. These tests exercise the
real schema language (no parallel implementation) — a plugin module
declares ``plugs_config_schema``, the loader walks the config section,
and a :class:`PluginSchemaError` is raised with the dotted path on
the first violation.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# Add jukebox source to path
_JUKEBOX_SRC = Path(__file__).resolve().parents[2] / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))

from jukebox.plug_schema import (  # noqa: E402
    PluginSchemaError,
    validate_loaded_plugin_module,
    validate_plugin_config,
)


# ---------------------------------------------------------------------------
# Direct schema validation
# ---------------------------------------------------------------------------
def test_validate_accepts_correct_types():
    """A correctly-typed config passes silently."""
    schema = {
        'host': {'type': str, 'required': True},
        'port': int,
        'tls': bool,
    }
    validate_plugin_config('myplugin', schema,
                           {'host': 'localhost', 'port': 6600, 'tls': False})


def test_validate_missing_required_raises_with_path():
    schema = {'host': {'type': str, 'required': True}}
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_plugin_config('myplugin', schema, {})
    assert exc_info.value.plugin == 'myplugin'
    assert exc_info.value.path == 'host'
    assert 'missing required field' in exc_info.value.msg


def test_validate_wrong_type_raises_with_actual_type():
    schema = {'port': int}
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_plugin_config('myplugin', schema, {'port': '6600'})
    assert exc_info.value.path == 'port'
    assert 'expected int' in exc_info.value.msg
    assert 'str' in exc_info.value.msg


def test_validate_bool_not_accepted_as_int():
    """A YAML ``true`` for an int field is wrong, not coerced.

    Reversion check: remove the bool-special-case in ``_check_type``
    and this test fails.
    """
    schema = {'port': int}
    with pytest.raises(PluginSchemaError):
        validate_plugin_config('myplugin', schema, {'port': True})


def test_validate_optional_field_can_be_absent():
    schema = {'port': int}
    validate_plugin_config('myplugin', schema, {})  # no port → fine


def test_validate_choices_enforced():
    schema = {'mode': {'type': str, 'choices': ['fast', 'slow']}}
    validate_plugin_config('myplugin', schema, {'mode': 'fast'})
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_plugin_config('myplugin', schema, {'mode': 'bogus'})
    assert 'not in allowed choices' in exc_info.value.msg


def test_validate_nested_dict_schema():
    schema = {
        'auth': {
            'type': dict,
            'schema': {
                'token': {'type': str, 'required': True},
                'expiry': int,
            },
        },
    }
    validate_plugin_config('myplugin', schema,
                           {'auth': {'token': 'abc', 'expiry': 3600}})

    # Nested missing required → path is dotted
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_plugin_config('myplugin', schema, {'auth': {}})
    assert exc_info.value.path == 'auth.token'


def test_validate_unknown_fields_ignored():
    """Plugins can adopt schemas incrementally — extra keys are fine."""
    schema = {'port': int}
    validate_plugin_config('myplugin', schema,
                           {'port': 6600, 'undocumented_extra': 'x'})


def test_validate_section_must_be_mapping():
    schema = {'port': int}
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_plugin_config('myplugin', schema, ['not', 'a', 'dict'])
    assert 'expected a mapping' in exc_info.value.msg


def test_validate_none_section_treated_as_empty():
    """If the section isn't in cfg at all, treat as empty dict — only
    ``required`` keys fail."""
    schema = {'port': int, 'host': {'type': str, 'required': True}}
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_plugin_config('myplugin', schema, None)
    assert exc_info.value.path == 'host'


# ---------------------------------------------------------------------------
# Module-level entry point: validate_loaded_plugin_module
# ---------------------------------------------------------------------------
def _make_fake_module(schema=None, section=None, validate=None):
    mod = types.ModuleType('fake_plugin')
    if schema is not None:
        mod.plugs_config_schema = schema
    if section is not None:
        mod.plugs_config_section = section
    if validate is not None:
        mod.plugs_validate = validate
    return mod


class _FakeCfg:
    """Tiny stand-in for ConfigHandler.getn."""
    def __init__(self, data):
        self._data = data

    def getn(self, *keys, default=None):
        cur = self._data
        for k in keys:
            if isinstance(cur, dict):
                cur = cur.get(k, default)
            else:
                return default
        return cur


def test_validate_loaded_plugin_no_schema_is_noop():
    """Plugins without a schema are skipped — adoption is incremental."""
    mod = _make_fake_module()
    cfg = _FakeCfg({})
    validate_loaded_plugin_module('legacy_plugin', mod, cfg)  # no raise


def test_validate_loaded_plugin_uses_default_section_name():
    """Default section is the plugin name (load_as alias)."""
    schema = {'host': {'type': str, 'required': True}}
    mod = _make_fake_module(schema=schema)
    cfg = _FakeCfg({'myplug': {'host': 'localhost'}})
    validate_loaded_plugin_module('myplug', mod, cfg)


def test_validate_loaded_plugin_honours_section_override():
    """A plugin can name its section explicitly (e.g. rfid's section
    is 'rfid', not its load_as alias)."""
    schema = {'reader_config': {'type': str, 'required': True}}
    mod = _make_fake_module(
        schema=schema, section=['rfid'],
    )
    cfg = _FakeCfg({'rfid': {'reader_config': '/path/to/rfid.yaml'}})
    validate_loaded_plugin_module('rfid_alias', mod, cfg)


def test_validate_loaded_plugin_raises_with_full_path():
    schema = {'port': int}
    mod = _make_fake_module(schema=schema, section=['myplug'])
    cfg = _FakeCfg({'myplug': {'port': 'not-an-int'}})
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_loaded_plugin_module('myplug', mod, cfg)
    # The error path includes the section prefix.
    assert exc_info.value.path == 'myplug.port'


def test_validate_loaded_plugin_calls_extra_validator():
    """``plugs_validate`` callable is invoked after schema check."""
    calls = []

    def custom(section):
        calls.append(section)
        if section and section.get('mode') == 'bad':
            raise PluginSchemaError('p', 'mode', 'custom rejected')

    schema = {'mode': str}
    mod = _make_fake_module(schema=schema, validate=custom)
    cfg = _FakeCfg({'p': {'mode': 'good'}})
    validate_loaded_plugin_module('p', mod, cfg)
    assert calls == [{'mode': 'good'}]

    cfg = _FakeCfg({'p': {'mode': 'bad'}})
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_loaded_plugin_module('p', mod, cfg)
    assert exc_info.value.msg == 'custom rejected'


def test_validate_loaded_plugin_wraps_unexpected_validator_exception():
    """A custom validator that raises non-PluginSchemaError is wrapped."""
    def custom(section):
        raise ValueError('something else')

    mod = _make_fake_module(validate=custom)
    cfg = _FakeCfg({'p': {}})
    with pytest.raises(PluginSchemaError) as exc_info:
        validate_loaded_plugin_module('p', mod, cfg)
    assert 'custom validator raised' in exc_info.value.msg
    assert 'something else' in exc_info.value.msg
