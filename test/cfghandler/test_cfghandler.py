import sys
import os
# In case this is run locally from
sys.path.append(os.path.abspath('../../src/jukebox'))

import jukebox.cfghandler as cfghandler # noqa
from ruamel.yaml import YAML # noqa

ref_dict = {'l1': {'key1': 'value1'}, 'tl': 'number2'}

ref_yaml = """\
l1:
    key1: value1
tl: number2
"""


def test_ordereddict_getn():
    yaml = YAML(typ='rt')
    cfg = cfghandler.ConfigHandler('test_ordereddict_getn')
    cfg.config_dict(yaml.load(ref_yaml))

    assert 'value1' == cfg.getn('l1', 'key1', default='other')
    assert 'kk4' == cfg.getn('l1', 'key4', default='kk4')
    assert 'kk5' == cfg.getn('l1', 'key7', 'extra5', 'sub7', default='kk5')
    assert yaml.load(ref_yaml)['l1'] == cfg.getn('l1', default='other')


def test_ordereddict_setndefault():
    yaml = YAML(typ='rt')
    cfg = cfghandler.ConfigHandler('test_ordereddict_setndefault')
    cfg.config_dict(yaml.load(ref_yaml))

    assert 'newly' == cfg.setndefault('l1', 'n2', 'n3', 'n4', value='newly')
    ref1 = cfg.getn('l1', 'n2', 'n3')
    assert ref1 == cfg.setndefault('l1', 'n2', 'n3', value='should_not_be_new')
    assert 'newly' == cfg.getn('l1', 'n2', 'n3', 'n4')


def test_modified():
    cfg = cfghandler.get_handler('test_modified')
    assert False is cfg.is_modified()
    cfg.config_dict(ref_dict)
    assert False is cfg.is_modified()
    cfg.setndefault('l2', value='a_new_value')
    assert True is cfg.is_modified()
    cfg.clear_modified()
    assert False is cfg.is_modified()


def test_contains():
    cfg = cfghandler.get_handler('test_contains')
    cfg.config_dict(ref_dict)
    assert True == ('l1' in cfg)
    assert False == ('nonono' in cfg)
    assert False == ('key1' in cfg)


def test_lock():
    # Not a real lock test, but simply checking if functions come back ok
    cfg = cfghandler.get_handler('test_lock')
    cfg.config_dict(ref_dict)
    cfg.acquire()
    cfg['l1']['nested1'] = 'lkdr'
    cfg.release()


def test_context():
    # Not a real lock test, but simply checking if functions come back ok
    cfg = cfghandler.get_handler('test_context')
    cfg.config_dict(ref_dict)
    with cfg:
        cfg['l1']['nested1'] = 'lkdr1'
        cfg['l1']['nested2'] = 'lkdr2'
        cfg['l1']['nested3'] = 'lkdr3'


def test_mutable():
    cfg = cfghandler.get_handler('test_mutable')
    cfg.config_dict(ref_dict)
    v = cfg.get('l1')
    v.setdefault('key2', 'anew2')
    assert 'anew2' == cfg.getn('l1', 'key2')


def test_ordereddict_mutable():
    yaml = YAML(typ='rt')
    cfg = cfghandler.ConfigHandler('test_ordereddict_mutable')
    cfg.config_dict(yaml.load(ref_yaml))
    v = cfg.get('l1')
    v.setdefault('key2', 'anew2')
    assert 'anew2' == cfg.getn('l1', 'key2')


def test_getn_logs_warning_on_intermediate_type_mismatch(caplog):
    """Phase 6: when getn descends into a non-mapping intermediate
    value (e.g. an int where a dict is expected), log a WARN with the
    consumed/remaining dotted path so config-schema typos are
    debuggable.

    Reversion check: remove the WARN log in getn's AttributeError
    branch and this test fails.
    """
    import logging as _logging
    cfg = cfghandler.ConfigHandler('test_getn_warn')
    cfg.config_dict({'rfid': 1})

    caplog.set_level(_logging.WARNING, logger='jb.cfghandler')
    result = cfg.getn('rfid', 'readers', default='X')

    # Phase 6: returns default (was returning the leaf int before)
    assert result == 'X'

    # And we logged a structured warning identifying the path
    matched = [r for r in caplog.records
               if 'getn type mismatch' in r.getMessage()
               and "'rfid'" in r.getMessage()
               and "'readers'" in r.getMessage()]
    assert matched, (
        f"Expected getn type-mismatch warning. Got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


def test_getn_no_warning_for_missing_keys():
    """A simple missing key is not a mismatch — just return default,
    no warning."""
    import logging as _logging
    cfg = cfghandler.ConfigHandler('test_getn_no_warn')
    cfg.config_dict({'rfid': {'readers': {}}})

    # Use Python's logging system directly to capture only this case
    logger = _logging.getLogger('jb.cfghandler')
    msgs = []
    handler = _logging.Handler()
    handler.handle = lambda r: msgs.append(r.getMessage())
    logger.addHandler(handler)
    try:
        result = cfg.getn('rfid', 'readers', 'rdr1', default='Y')
    finally:
        logger.removeHandler(handler)
    assert result == 'Y'
    assert not any('type mismatch' in m for m in msgs)


def test_load_yaml_resolves_relative_paths_under_home(tmp_path, monkeypatch):
    """Phase 6: load_yaml anchors relative filenames under PHONIEBOX_HOME.

    Reversion check: remove ``resolve_under_home`` from
    ``cfghandler.load_yaml`` and this test fails — the relative path
    is resolved against cwd, not tmp_path.
    """
    from jukebox.utils import paths as paths_mod
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, str(tmp_path))
    paths_mod.reset_phoniebox_home_cache()

    # Create the YAML file at the anchored relative path
    rel = 'subdir/cfg.yaml'
    full = tmp_path / rel
    full.parent.mkdir(parents=True)
    full.write_text("a: 1\nb: two\n")

    cfg = cfghandler.ConfigHandler('test_load_yaml_relative')
    cfghandler.load_yaml(cfg, rel)
    assert cfg.getn('a') == 1
    assert cfg.getn('b') == 'two'
    # loaded_from records the resolved absolute path
    assert os.path.isabs(cfg.loaded_from)
    paths_mod.reset_phoniebox_home_cache()


def test_load_yaml_absolute_path_unchanged(tmp_path, monkeypatch):
    """Absolute filenames bypass PHONIEBOX_HOME resolution."""
    from jukebox.utils import paths as paths_mod
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, '/some/other/home')
    paths_mod.reset_phoniebox_home_cache()

    full = tmp_path / 'cfg.yaml'
    full.write_text("a: 42\n")
    cfg = cfghandler.ConfigHandler('test_load_yaml_absolute')
    cfghandler.load_yaml(cfg, str(full))
    assert cfg.getn('a') == 42
    paths_mod.reset_phoniebox_home_cache()


if __name__ == '__main__':
    test_ordereddict_getn()
    test_ordereddict_setndefault()
    test_modified()
    test_contains()
    test_lock()
    test_context()
