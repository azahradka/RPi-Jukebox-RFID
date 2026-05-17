# -*- coding: utf-8 -*-
"""Per-plugin configuration schema validation.

Phase 6: surfaces plugin misconfiguration as a structured
:class:`PluginSchemaError` before the plugin's ``__init__`` runs and
crashes with an opaque ``KeyError`` deep inside resolver code. Plugins
that opt in declare a schema (a dict) on their module via:

* ``plugs_config_schema`` — a dict mapping config keys to type/spec
  descriptors. See :func:`validate_plugin_config` for the schema
  language.
* ``plugs_config_section`` — the key path into ``cfg`` where this
  plugin's configuration lives. Defaults to the plugin's ``loaded_as``
  alias when not provided.

Schema language (minimal, intentional):

The schema is a ``dict`` keyed by config-field name. Each value is one
of:

* a builtin type: ``str``, ``int``, ``float``, ``bool``, ``list``, ``dict``
* a dict ``{'type': T, 'required': bool, 'default': X, 'choices': [...]}``
* a nested schema dict for sub-sections (``'type': dict, 'schema': {...}}``)

The validator only enforces three things:

1. Required keys are present.
2. Present keys have a value of the declared type (or one of the
   declared ``choices``).
3. Sub-section schemas are recursively validated.

It deliberately does NOT validate keys we don't know about, so plugin
authors can adopt incrementally without listing every legacy option.
This is JSON-Schema-lite — full JSON Schema is overkill for the
handful of declared fields we have today, and ``jsonschema`` is an
extra dependency we don't need yet.

If a plugin wants richer validation it can declare ``plugs_validate``
as a callable ``(cfg_section) -> None`` that raises
:class:`PluginSchemaError` itself.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger('jb.plugin.schema')


class PluginSchemaError(Exception):
    """Raised when a plugin's configuration fails schema validation.

    Carries the plugin name and the dotted path to the offending field
    so the daemon can log a structured error rather than the opaque
    ``KeyError`` the plugin would otherwise raise deep in its init.
    """

    def __init__(self, plugin: str, path: str, msg: str):
        self.plugin = plugin
        self.path = path
        self.msg = msg
        super().__init__(f"[{plugin}] config error at '{path}': {msg}")


_BUILTIN_TYPES = (str, int, float, bool, list, dict)


def _normalise_field_spec(spec: Any) -> Dict[str, Any]:
    """Turn shorthand schema entries into the canonical dict form.

    ``str`` -> ``{'type': str, 'required': False}``
    ``{'type': str, ...}`` -> as-is, with defaults filled in
    """
    if spec in _BUILTIN_TYPES:
        return {'type': spec, 'required': False}
    if isinstance(spec, dict) and 'type' in spec:
        out = dict(spec)
        out.setdefault('required', False)
        return out
    raise ValueError(
        f"Invalid schema field spec: {spec!r}. "
        f"Must be a builtin type or a dict with 'type' key."
    )


def _check_type(value: Any, expected: type) -> bool:
    """Type check that treats bool as distinct from int.

    Python's ``isinstance(True, int)`` is True, but a config field
    declared as ``int`` shouldn't silently accept ``yes`` (bool True
    from YAML). We special-case bool.
    """
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is float:
        # Accept int as float-compatible; reject bool.
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, expected)


def validate_plugin_config(plugin: str,
                           schema: Dict[str, Any],
                           cfg_section: Any,
                           path_prefix: str = '') -> None:
    """Validate a config section against ``schema``.

    Raises :class:`PluginSchemaError` on the first failure with the
    full dotted path to the offending field.

    :param plugin: Plugin name (for error messages)
    :param schema: Schema dict, see module docstring
    :param cfg_section: The config section to validate (a mapping)
    :param path_prefix: Internal — used for recursive calls into
        nested sub-schemas.
    """
    if cfg_section is None:
        cfg_section = {}
    if not isinstance(cfg_section, dict):
        raise PluginSchemaError(
            plugin, path_prefix or '<root>',
            f"expected a mapping, got {type(cfg_section).__name__}",
        )

    for field, raw_spec in schema.items():
        spec = _normalise_field_spec(raw_spec)
        field_path = f"{path_prefix}.{field}" if path_prefix else field
        present = field in cfg_section
        value = cfg_section.get(field)

        if not present:
            if spec.get('required'):
                raise PluginSchemaError(
                    plugin, field_path, "missing required field",
                )
            continue

        expected_type = spec['type']
        if not _check_type(value, expected_type):
            raise PluginSchemaError(
                plugin, field_path,
                f"expected {expected_type.__name__}, "
                f"got {type(value).__name__}: {value!r}",
            )

        choices: Optional[Iterable] = spec.get('choices')
        if choices is not None and value not in choices:
            raise PluginSchemaError(
                plugin, field_path,
                f"value {value!r} not in allowed choices {list(choices)}",
            )

        # Recursive validation for nested dicts
        if expected_type is dict and 'schema' in spec:
            validate_plugin_config(plugin, spec['schema'], value, field_path)


def _walk_to_section(cfg, section_path: List[str]) -> Any:
    """Resolve a dotted section path through a ConfigHandler-or-dict.

    Returns None when any intermediate key is missing.
    """
    cur = cfg
    for key in section_path:
        if cur is None:
            return None
        if hasattr(cur, 'getn'):
            cur = cur.getn(key, default=None)
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def validate_loaded_plugin_module(plugin_name: str,
                                  module: Any,
                                  cfg) -> None:
    """If ``module`` declares a schema, validate ``cfg`` against it.

    Resolution rules:

    * ``module.plugs_config_schema`` — schema dict. If absent, this is
      a no-op (the plugin opted out, which is fine for legacy plugins).
    * ``module.plugs_config_section`` — list of strings, the path into
      ``cfg``. If absent, defaults to ``[plugin_name]``.
    * ``module.plugs_validate`` — optional callable taking the section
      value; called after the schema check. Plugins can use this for
      cross-field invariants schemas don't express well.

    Raises :class:`PluginSchemaError` on the first failure.
    """
    schema = getattr(module, 'plugs_config_schema', None)
    extra_validator = getattr(module, 'plugs_validate', None)
    if schema is None and extra_validator is None:
        return

    section_path = getattr(module, 'plugs_config_section', [plugin_name])
    if isinstance(section_path, str):
        section_path = [section_path]
    section = _walk_to_section(cfg, list(section_path))

    if schema is not None:
        validate_plugin_config(plugin_name, schema, section,
                               path_prefix='.'.join(section_path))

    if callable(extra_validator):
        try:
            extra_validator(section)
        except PluginSchemaError:
            raise
        except Exception as exc:
            raise PluginSchemaError(
                plugin_name, '.'.join(section_path),
                f"custom validator raised: {exc}",
            )
