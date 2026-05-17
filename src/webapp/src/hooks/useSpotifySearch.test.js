/**
 * Behavioural tests for the Spotify-search hook.
 *
 * Phase 5b — drives the real ``useSpotifySearch`` hook from a probe
 * component (no parallel implementation).
 *
 * Reversion checks:
 *   - Remove the debounce: ``coalesces rapid keystrokes`` fails (would
 *     fire once per change instead of once per debounce window).
 *   - Remove the 2-char minimum: ``does not search for sub-2-char queries``
 *     fails.
 *   - Remove the error reset in ``performSearch``: re-search after an
 *     error never clears it.
 */

import React, { useImperativeHandle, forwardRef } from 'react';
import { act, render } from '@testing-library/react';

import {
  __mockSocketLog,
  __resetMockSocket,
  __setMockResponse,
} from '../test-utils/mockSocket';

jest.mock('../sockets', () => require('../test-utils/mockSocket'));

const useSpotifySearch = require('./useSpotifySearch').default;

const Probe = forwardRef((props, ref) => {
  const api = useSpotifySearch(props);
  useImperativeHandle(ref, () => api, [api]);
  return null;
});

const mount = (props = {}) => {
  const ref = React.createRef();
  render(<Probe ref={ref} {...props} />);
  return ref;
};

const countSearchCalls = () =>
  __mockSocketLog.filter((c) => c.key === 'player_spotify.ctrl.search').length;

describe('useSpotifySearch', () => {
  beforeEach(() => {
    __resetMockSocket();
    jest.useFakeTimers();
    __setMockResponse('player_spotify.ctrl.search', { items: [] });
  });
  afterEach(() => jest.useRealTimers());

  it('does not search for sub-2-char queries', async () => {
    const ref = mount();
    act(() => { ref.current.setQuery('a'); });
    await act(async () => { jest.advanceTimersByTime(400); });
    expect(countSearchCalls()).toBe(0);
  });

  it('coalesces rapid keystrokes into a single trailing RPC', async () => {
    const ref = mount();
    act(() => {
      ref.current.setQuery('b');
      ref.current.setQuery('be');
      ref.current.setQuery('bea');
      ref.current.setQuery('beatles');
    });
    expect(countSearchCalls()).toBe(0);
    await act(async () => { jest.advanceTimersByTime(350); });
    expect(countSearchCalls()).toBe(1);
    const call = __mockSocketLog.find((c) => c.key === 'player_spotify.ctrl.search');
    expect(call.kwargs.query).toBe('beatles');
    expect(call.kwargs.content_type).toBe('playlist,album,track,show');
    expect(call.kwargs.limit).toBe(10);
  });

  it('submitNow bypasses the debounce', async () => {
    const ref = mount();
    act(() => { ref.current.setQuery('immediate'); });
    expect(countSearchCalls()).toBe(0);
    await act(async () => { await ref.current.submitNow(); });
    expect(countSearchCalls()).toBe(1);
  });

  it('populates results from the backend response', async () => {
    __setMockResponse('player_spotify.ctrl.search', {
      items: [
        { uri: 'spotify:track:1', type: 'track', name: 'Song' },
        { uri: 'spotify:album:1', type: 'album', name: 'Album' },
      ],
    });
    const ref = mount();
    await act(async () => { await ref.current.submitNow('beatles'); });
    expect(ref.current.results).toHaveLength(2);
    expect(ref.current.searchPerformed).toBe(true);
  });

  it('activeFilter narrows filteredResults by type', async () => {
    __setMockResponse('player_spotify.ctrl.search', {
      items: [
        { uri: 'spotify:track:1', type: 'track', name: 'Song' },
        { uri: 'spotify:album:1', type: 'album', name: 'Album' },
      ],
    });
    const ref = mount();
    await act(async () => { await ref.current.submitNow('beatles'); });
    expect(ref.current.filteredResults).toHaveLength(2);
    act(() => { ref.current.setActiveFilter('track'); });
    expect(ref.current.filteredResults).toHaveLength(1);
    expect(ref.current.filteredResults[0].type).toBe('track');
  });

  it('surfaces a backend error and clears results', async () => {
    __setMockResponse('player_spotify.ctrl.search', new Error('rate limited'));
    const ref = mount();
    await act(async () => { await ref.current.submitNow('beatles'); });
    expect(ref.current.error).toBe('rate limited');
    expect(ref.current.results).toHaveLength(0);
    expect(ref.current.searching).toBe(false);
  });
});
