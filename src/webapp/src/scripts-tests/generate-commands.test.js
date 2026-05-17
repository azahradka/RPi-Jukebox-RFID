/* eslint-env jest, node */
/**
 * Tests for the Phase 5a command-index generator.
 *
 * Coverage focus:
 *   - Python-literal parser handles the strict subset used by
 *     rpc_command_alias.py (dict / set / frozenset / list / tuple /
 *     str / bool / None / int / comments).
 *   - AST-style scanner discovers @plugs.tag / @plugin.tag methods on
 *     classes registered via plugs.register(obj, name='X', ...).
 *   - validate() rejects unresolved RPC targets with a clear message
 *     (this is the deliberate-mismatch test the meta-plan mandates).
 *   - emitJsCommands produces a deterministic, parseable JS file.
 *
 * The tests run against in-memory fixtures + a tmpdir mirroring the
 * components/ layout so they don't depend on the live tree.
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const {
  PyParser,
  extractTopLevelAssign,
  scanRegistry,
  parseModulesNamed,
  emitJsCommands,
  validate,
} = require('../../scripts/generate-commands.js');

// ---------------------------------------------------------------------------
// PyParser
// ---------------------------------------------------------------------------
describe('PyParser', () => {
  test('parses an empty dict', () => {
    expect(new PyParser('{}').readValue()).toEqual({});
  });

  test('parses a dict of strings', () => {
    const out = new PyParser("{'a': 'hello', 'b': 'world'}").readValue();
    expect(out).toEqual({ a: 'hello', b: 'world' });
  });

  test('parses booleans and None', () => {
    const out = new PyParser("{'k1': True, 'k2': False, 'k3': None}").readValue();
    expect(out).toEqual({ k1: true, k2: false, k3: null });
  });

  test('parses nested dict + list', () => {
    const out = new PyParser(
      "{'cmd': {'package': 'p', 'plugin': 'q', 'argKeys': ['a', 'b']}}"
    ).readValue();
    expect(out).toEqual({
      cmd: { package: 'p', plugin: 'q', argKeys: ['a', 'b'] },
    });
  });

  test('tolerates trailing commas + comments + multi-line', () => {
    const src = `
{
    # leading comment
    'a': 'hi',  # inline comment
    'b': 'bye',
}
`;
    expect(new PyParser(src).readValue()).toEqual({ a: 'hi', b: 'bye' });
  });

  test('parses frozenset of tuples', () => {
    const out = new PyParser(
      "frozenset({('misc', 'foo', None), ('host', 'bar', 'baz')})"
    ).readValue();
    expect(out).toBeInstanceOf(Set);
    const triples = [...out].map(s => JSON.parse(s));
    expect(triples).toContainEqual(['misc', 'foo', null]);
    expect(triples).toContainEqual(['host', 'bar', 'baz']);
  });

  test('parses string escapes', () => {
    const out = new PyParser("'a\\nb\\tc\\\\d'").readValue();
    expect(out).toBe('a\nb\tc\\d');
  });
});

// ---------------------------------------------------------------------------
// extractTopLevelAssign
// ---------------------------------------------------------------------------
describe('extractTopLevelAssign', () => {
  test('finds and parses a multi-line dict assignment', () => {
    const src = `
"""module docstring"""
import foo

cmd_alias_definitions = {
    'play': {'package': 'player', 'plugin': 'ctrl'},
    'pause': {'package': 'player', 'plugin': 'ctrl'},
}

other_var = 'ignored'
`;
    const out = extractTopLevelAssign(src, 'cmd_alias_definitions');
    expect(out).toEqual({
      play: { package: 'player', plugin: 'ctrl' },
      pause: { package: 'player', plugin: 'ctrl' },
    });
  });

  test('returns undefined for missing assignments', () => {
    expect(extractTopLevelAssign('x = 1\n', 'missing')).toBeUndefined();
  });

  test('finds frozenset top-level assignments', () => {
    const src = "KNOWN = frozenset({('a','b',None)})\n";
    const out = extractTopLevelAssign(src, 'KNOWN');
    expect(out).toBeInstanceOf(Set);
    expect([...out].length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// scanRegistry — uses a tmpdir with a fake components tree
// ---------------------------------------------------------------------------
describe('scanRegistry', () => {
  let tmpdir;

  beforeEach(() => {
    tmpdir = fs.mkdtempSync(path.join(os.tmpdir(), 'rpc-gen-'));
  });

  afterEach(() => {
    fs.rmSync(tmpdir, { recursive: true, force: true });
  });

  function writeFile(rel, body) {
    const p = path.join(tmpdir, rel);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, body);
  }

  test('discovers @plugs.tag methods registered via plugs.register(obj, name=...)', () => {
    writeFile('playermpd/__init__.py', `
import jukebox.plugs as plugs


class PlayerMPD:
    @plugs.tag
    def play(self):
        pass

    @plugs.tag
    def pause(self):
        pass

    def _internal(self):
        pass


@plugs.initialize
def initialize():
    global player_ctrl
    player_ctrl = PlayerMPD()
    plugs.register(player_ctrl, name='ctrl')
`);
    const reg = scanRegistry(tmpdir, { player: 'playermpd' });
    expect(reg.has('player::ctrl::play')).toBe(true);
    expect(reg.has('player::ctrl::pause')).toBe(true);
    expect(reg.has('player::ctrl::_internal')).toBe(false);
  });

  test('discovers top-level @plugs.register / @plugin.register functions', () => {
    writeFile('hostif/linux/__init__.py', `
import jukebox.plugs as plugin


@plugin.register
def reboot():
    pass

@plugin.register
def shutdown():
    pass

@plugin.register(name='renamed')
def some_func():
    pass
`);
    const reg = scanRegistry(tmpdir, { host: 'hostif.linux' });
    expect(reg.has('host::reboot::None')).toBe(true);
    expect(reg.has('host::shutdown::None')).toBe(true);
    expect(reg.has('host::renamed::None')).toBe(true);
    expect(reg.has('host::some_func::None')).toBe(false);
  });

  test('handles nested classes (PulseVolumeControl with inner callback handlers)', () => {
    writeFile('volume/__init__.py', `
import jukebox.plugs as plugin


class PulseVolumeControl:
    class InnerCB:
        def register(self, func):
            pass
        def run_callbacks(self, *a):
            pass

    def __init__(self):
        pass

    @plugin.tag
    def set_volume(self, v):
        pass

    @plugin.tag
    def toggle_output(self):
        pass


@plugin.initialize
def initialize():
    pulse_control = PulseVolumeControl()
    plugin.register(pulse_control, package='volume', name='ctrl', replace=True)
`);
    const reg = scanRegistry(tmpdir, { volume: 'volume' });
    expect(reg.has('volume::ctrl::set_volume')).toBe(true);
    expect(reg.has('volume::ctrl::toggle_output')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// parseModulesNamed
// ---------------------------------------------------------------------------
describe('parseModulesNamed', () => {
  test('extracts modules.named mapping from yaml', () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'rpc-yaml-'));
    const yamlPath = path.join(tmp, 'jukebox.yaml');
    fs.writeFileSync(yamlPath, `
system:
  box_name: Jukebox
modules:
  named:
    player: playermpd
    player_spotify: playerspotify
    host: hostif.linux
  others:
  - misc
pulse:
  soft_max_volume: 70
`);
    const out = parseModulesNamed(yamlPath);
    expect(out).toEqual({
      player: 'playermpd',
      player_spotify: 'playerspotify',
      host: 'hostif.linux',
    });
    fs.rmSync(tmp, { recursive: true, force: true });
  });
});

// ---------------------------------------------------------------------------
// validate — the deliberate-mismatch test the meta-plan mandates
// ---------------------------------------------------------------------------
describe('validate', () => {
  const aliasByDir = { player: 'playermpd', volume: 'volume', host: 'hostif.linux' };
  const registry = new Set([
    'player::ctrl::play',
    'player::ctrl::pause',
    'host::reboot::None',
  ]);
  const allowlist = new Set([JSON.stringify(['misc', 'get_app_settings', null])]);
  const internalSet = new Set([JSON.stringify(['player', 'ctrl', 'play_single_passive'])]);

  test('passes when every command resolves', () => {
    const cmds = {
      play: { package: 'player', plugin: 'ctrl', method: 'play' },
      reboot: { package: 'host', plugin: 'reboot' },
      getAppSettings: { package: 'misc', plugin: 'get_app_settings' },
    };
    expect(validate(cmds, registry, allowlist, internalSet, aliasByDir)).toEqual([]);
  });

  test('fails when a command points at a non-existent plugin method', () => {
    const cmds = {
      bogus: { package: 'player', plugin: 'ctrl', method: 'does_not_exist' },
    };
    const errors = validate(cmds, registry, allowlist, internalSet, aliasByDir);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatch(/'bogus'/);
    expect(errors[0]).toMatch(/cannot resolve RPC target player\.ctrl\.does_not_exist/);
  });

  test('fails when a command targets an internal-only RPC', () => {
    const cmds = {
      sneaky: { package: 'player', plugin: 'ctrl', method: 'play_single_passive' },
    };
    const errors = validate(cmds, registry, allowlist, internalSet, aliasByDir);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatch(/internal-only RPC/);
  });

  test('fails when the package alias is unknown', () => {
    const cmds = {
      bad: { package: 'made_up', plugin: 'ctrl', method: 'play' },
    };
    const errors = validate(cmds, registry, allowlist, internalSet, aliasByDir);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatch(/unknown package alias 'made_up'/);
  });

  test('accepts allowlisted triples even when not in registry', () => {
    const cmds = {
      getAppSettings: { package: 'misc', plugin: 'get_app_settings' },
    };
    expect(validate(cmds, registry, allowlist, internalSet, aliasByDir)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// emitJsCommands — deterministic output
// ---------------------------------------------------------------------------
describe('emitJsCommands', () => {
  test('renders package/plugin/method and argKeys', () => {
    const out = emitJsCommands({
      play_single: {
        package: 'player', plugin: 'ctrl', method: 'play_single',
        argKeys: ['song_url'],
      },
      reboot: { package: 'host', plugin: 'reboot' },
    });
    expect(out).toMatch(/AUTO-GENERATED/);
    expect(out).toMatch(/play_single: \{/);
    expect(out).toMatch(/_package: 'player'/);
    expect(out).toMatch(/argKeys: \['song_url'\]/);
    expect(out).toMatch(/reboot: \{[\s\S]*plugin: 'reboot'/);
    expect(out).toMatch(/export default commands;/);
  });

  test('quotes JS keys containing dots', () => {
    const out = emitJsCommands({
      'timer_fade_volume.cancel': {
        package: 'timers', plugin: 'timer_fade_volume', method: 'cancel',
      },
    });
    expect(out).toMatch(/'timer_fade_volume\.cancel': \{/);
  });

  test('omits method when null', () => {
    const out = emitJsCommands({
      cardsList: { package: 'cards', plugin: 'list_cards' },
    });
    expect(out).toMatch(/cardsList: \{\n\s*_package: 'cards',\n\s*plugin: 'list_cards',\n\s*},/);
    expect(out).not.toMatch(/cardsList:[\s\S]*method:/);
  });

  test('output is parseable as a module (smoke)', () => {
    const out = emitJsCommands({
      play: { package: 'player', plugin: 'ctrl', method: 'play' },
    });
    // Strip export to allow eval as plain JS.
    const stripped = out.replace(/export default commands;/, '');
    // eslint-disable-next-line no-new-func
    const mod = new Function(`${stripped}; return commands;`);
    expect(mod()).toEqual({
      play: { _package: 'player', plugin: 'ctrl', method: 'play' },
    });
  });
});
