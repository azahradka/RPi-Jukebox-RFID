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


def test_tmp_state_dir_round_trip(tmp_state_dir):
    path = tmp_state_dir / 'player.json'
    with open(path, 'w') as f:
        json.dump({'state': 'play', 'pos': 3}, f)

    data = tmp_state_dir.read_json('player.json')
    assert data == {'state': 'play', 'pos': 3}
