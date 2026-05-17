# -*- coding: utf-8 -*-
"""Smoke tests for the top-level ``conftest.py`` fixtures."""

import json


def test_fake_mpd_client_basic_playback(fake_mpd_client):
    client = fake_mpd_client
    client.connect('localhost', 6600)
    assert client.ping() == 'OK'

    client.clear()
    client.add('song1.mp3')
    client.add('song2.mp3')
    client.play()

    status = client.status()
    assert status['state'] == 'play'
    assert status['playlistlength'] == '2'
    assert client.currentsong()['file'] == 'song1.mp3'

    client.next()
    assert client.currentsong()['file'] == 'song2.mp3'

    client.stop()
    assert client.status()['state'] == 'stop'


def test_fake_mpd_client_seekcur(fake_mpd_client):
    fake_mpd_client.add('song.mp3')
    fake_mpd_client.play()
    fake_mpd_client.seekcur(42.5)
    assert float(fake_mpd_client.status()['elapsed']) == 42.5
    assert ('seekcur', (42.5,), {}) in fake_mpd_client.call_log


def test_fake_mpd_client_mpd_version_attribute(fake_mpd_client):
    """mpd_version is a plain string attribute on python-mpd2.

    Phase 1 fix #3 corrected ``playermpd.get_player_type_and_version`` to
    access it without parentheses; the Phase 0b callable-string shim is
    therefore gone.
    """
    assert fake_mpd_client.mpd_version == '0.23.5'
    assert isinstance(fake_mpd_client.mpd_version, str)


def test_fake_mpd_client_consume(fake_mpd_client):
    fake_mpd_client.consume(1)
    assert fake_mpd_client.status()['consume'] == '1'
    fake_mpd_client.consume(0)
    assert fake_mpd_client.status()['consume'] == '0'


def test_fake_mpd_client_delete(fake_mpd_client):
    fake_mpd_client.add('a.mp3')
    fake_mpd_client.add('b.mp3')
    fake_mpd_client.add('c.mp3')
    fake_mpd_client.play()  # _pos = 0

    fake_mpd_client.delete(1)  # remove b.mp3
    files = [e['file'] for e in fake_mpd_client.playlistinfo()]
    assert files == ['a.mp3', 'c.mp3']
    # Position indices are re-numbered.
    assert [e['pos'] for e in fake_mpd_client.playlistinfo()] == ['0', '1']
    # Cursor unchanged (delete was after current).
    assert fake_mpd_client.currentsong()['file'] == 'a.mp3'

    # Delete current song -> cursor advances onto the next entry.
    fake_mpd_client.delete(0)
    assert fake_mpd_client.currentsong()['file'] == 'c.mp3'


def test_fake_mpd_client_shuffle_preserves_membership(fake_mpd_client):
    files = [f'song{i}.mp3' for i in range(6)]
    for f in files:
        fake_mpd_client.add(f)
    fake_mpd_client.shuffle()
    shuffled = [e['file'] for e in fake_mpd_client.playlistinfo()]
    assert sorted(shuffled) == sorted(files)
    # 'pos' is re-indexed after shuffle.
    assert [e['pos'] for e in fake_mpd_client.playlistinfo()] == [str(i) for i in range(6)]


def test_fake_mpd_client_pause_toggle(fake_mpd_client):
    fake_mpd_client.add('a.mp3')
    fake_mpd_client.play()
    fake_mpd_client.pause()
    assert fake_mpd_client.status()['state'] == 'pause'
    fake_mpd_client.pause()
    assert fake_mpd_client.status()['state'] == 'play'
    fake_mpd_client.pause(1)
    assert fake_mpd_client.status()['state'] == 'pause'
    fake_mpd_client.pause(0)
    assert fake_mpd_client.status()['state'] == 'play'


def test_fake_plugs_register_and_call(fake_plugs):
    @fake_plugs.register
    def hello(name):
        return f'hello {name}'

    @fake_plugs.register(name='greeting')
    def _greet():
        return 'hi'

    # registry uses module-name + function-name
    keys = list(fake_plugs.registry.keys())
    assert any(k.endswith('.hello') for k in keys)
    assert any(k.endswith('.greeting') for k in keys)

    # call routes through and logs
    pkg = next(iter(fake_plugs.registry)).rsplit('.', 1)[0]
    result = fake_plugs.call(pkg, method='hello', args=('world',))
    assert result == 'hello world'
    assert fake_plugs.call_log[-1][0].endswith('.hello')


def test_fake_plugs_missing_returns_none_logs_call(fake_plugs):
    result = fake_plugs.call('nonexistent', 'plugin', 'method')
    assert result is None
    assert fake_plugs.call_log[-1][0] == 'nonexistent.plugin.method'


def test_fake_plugs_register_class_auto_tag(fake_plugs):
    """Mirror playermpd's pattern: @plugs.register(auto_tag=True) on a class."""
    @fake_plugs.register(auto_tag=True)
    class Player:
        def __init__(self):
            self.calls = []

        def play(self, uri):
            self.calls.append(('play', uri))
            return f'playing {uri}'

        def stop(self):
            self.calls.append(('stop',))
            return 'stopped'

    # Instantiate with plugin_name so the instance auto-registers.
    pkg = Player.plugs_package
    instance = Player(plugin_name='ctrl')

    # call(package, plugin, method) dispatches to the bound method.
    result = fake_plugs.call(pkg, 'ctrl', 'play', args=('song.mp3',))
    assert result == 'playing song.mp3'
    assert instance.calls == [('play', 'song.mp3')]

    assert fake_plugs.call(pkg, 'ctrl', 'stop') == 'stopped'
    assert fake_plugs.call_log[-1][0].endswith('.ctrl.stop')


def test_fake_plugs_register_class_explicit_tag(fake_plugs):
    """Without auto_tag, only methods tagged with @plugs.tag are callable."""
    @fake_plugs.register
    class Component:
        def __init__(self):
            pass

        @fake_plugs.tag
        def callable_method(self):
            return 'ok'

        def untagged_method(self):
            return 'should-not-dispatch'

    pkg = Component.plugs_package
    Component(plugin_name='comp')

    assert fake_plugs.call(pkg, 'comp', 'callable_method') == 'ok'
    # Untagged methods are not exposed via call().
    assert fake_plugs.call(pkg, 'comp', 'untagged_method') is None


def test_tmp_state_dir_round_trip(tmp_state_dir):
    path = tmp_state_dir / 'player.json'
    with open(path, 'w') as f:
        json.dump({'state': 'play', 'pos': 3}, f)

    data = tmp_state_dir.read_json('player.json')
    assert data == {'state': 'play', 'pos': 3}
