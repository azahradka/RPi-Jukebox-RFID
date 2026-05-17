/**
 * Phase 4 behavioural test for SpotifySearch debounced search.
 *
 * Drives the real SpotifySearch component (no parallel implementation)
 * through ``renderWithProviders`` + the Phase 0b mockSocket. Asserts
 * that rapid keystrokes coalesce into a single trailing RPC after the
 * 300ms debounce window.
 *
 * Reversion check: if useDebounce is bypassed, each keystroke fires
 * its own RPC and the "single RPC sent" assertion fails.
 */

import React from 'react';
import { act, fireEvent, screen } from '@testing-library/react';

import {
  __mockSocketLog,
  __resetMockSocket,
  __setMockResponse,
} from '../../../../test-utils/mockSocket';
import { renderWithProviders } from '../../../../test-utils/renderWithProviders';

jest.mock('../../../../sockets', () => require('../../../../test-utils/mockSocket'));

// Import after the mock so the real component picks up the mocked socket
// module transitively via utils/request.
const SpotifySearch = require('./spotify-search').default;

describe('SpotifySearch debounce', () => {
  beforeEach(() => {
    __resetMockSocket();
    jest.useFakeTimers();
    __setMockResponse('player_spotify.ctrl.search', { items: [] });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  const countSearchCalls = () =>
    __mockSocketLog.filter((c) => c.key === 'player_spotify.ctrl.search').length;

  it('coalesces rapid keystrokes into a single trailing RPC', async () => {
    renderWithProviders(<SpotifySearch isSelecting={false} onPlay={() => {}} onSelectContent={() => {}} />);
    const input = screen.getByLabelText(/Search Spotify/i);

    act(() => {
      fireEvent.change(input, { target: { value: 'b' } });
      fireEvent.change(input, { target: { value: 'be' } });
      fireEvent.change(input, { target: { value: 'bea' } });
      fireEvent.change(input, { target: { value: 'beat' } });
      fireEvent.change(input, { target: { value: 'beatl' } });
      fireEvent.change(input, { target: { value: 'beatle' } });
      fireEvent.change(input, { target: { value: 'beatles' } });
    });

    // Before the debounce window elapses no RPC should have fired.
    expect(countSearchCalls()).toBe(0);

    // Advance past the 300ms window.
    await act(async () => {
      jest.advanceTimersByTime(350);
    });

    // Exactly one RPC, with the final value.
    const calls = __mockSocketLog.filter((c) => c.key === 'player_spotify.ctrl.search');
    expect(calls.length).toBe(1);
    expect(calls[0].kwargs.query).toBe('beatles');
  });

  it('does not fire while query is below the 2-character minimum', async () => {
    renderWithProviders(<SpotifySearch isSelecting={false} onPlay={() => {}} onSelectContent={() => {}} />);
    const input = screen.getByLabelText(/Search Spotify/i);
    act(() => {
      fireEvent.change(input, { target: { value: 'a' } });
    });
    await act(async () => {
      jest.advanceTimersByTime(500);
    });
    expect(countSearchCalls()).toBe(0);
  });
});
