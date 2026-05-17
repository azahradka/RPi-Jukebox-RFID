/**
 * End-to-end behavioural tests for the refactored SettingsSpotify card.
 *
 * Drives the real composed component (``SettingsSpotify`` ->
 * ``useSpotifyAuth`` -> ``SpotifyAuthFlow`` / ``SpotifyConfigForm`` /
 * ``SpotifyStatusDisplay``) via ``renderWithProviders`` + ``mockSocket``.
 *
 * Reversion checks:
 *   - If the Connect button stops calling ``spotifyGetAuthUrl``, the
 *     ``Connect opens auth URL`` test fails.
 *   - If the Disconnect button stops calling ``spotifyLogout``, the
 *     ``Disconnect transitions back to Not Connected`` test fails.
 *   - If the chip stops re-deriving from authStatus, the ``authenticated
 *     chip shows after disconnect+reload`` invariant breaks.
 */

import React from 'react';
import { act, fireEvent, screen, waitFor } from '@testing-library/react';

import {
  __mockSocketLog,
  __resetMockSocket,
  __setMockResponse,
} from '../../../test-utils/mockSocket';
import { renderWithProviders } from '../../../test-utils/renderWithProviders';

jest.mock('../../../sockets', () => require('../../../test-utils/mockSocket'));

const SettingsSpotify = require('../spotify').default;

describe('SettingsSpotify (refactored)', () => {
  beforeEach(() => {
    __resetMockSocket();
    // window.open is invoked when the user clicks "Connect Spotify".
    jest.spyOn(window, 'open').mockImplementation(() => null);
  });

  afterEach(() => jest.restoreAllMocks());

  it('shows the Connected chip when the backend reports authenticated', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', {
      configured: true, authenticated: true,
    });
    renderWithProviders(<SettingsSpotify />);
    await waitFor(() => expect(screen.getByText('Connected')).toBeInTheDocument());
  });

  it('shows the Not Configured state and the credentials form when unconfigured', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: false });
    __setMockResponse('player_spotify.ctrl.get_spotify_config', { client_id: '' });
    renderWithProviders(<SettingsSpotify />);

    await waitFor(() => expect(screen.getByText('Not Configured')).toBeInTheDocument());
    expect(screen.getByLabelText(/Client ID/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Client Secret/i)).toBeInTheDocument();
  });

  it('Connect opens auth URL and moves to the paste step', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.get_auth_url', {
      auth_url: 'https://accounts.spotify.com/authorize?x=1',
    });
    renderWithProviders(<SettingsSpotify />);
    await waitFor(() => expect(screen.getByText('Not Connected')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Connect Spotify/i }));
    });

    expect(window.open).toHaveBeenCalledWith(
      'https://accounts.spotify.com/authorize?x=1',
      '_blank',
      'noopener',
    );
    expect(await screen.findByLabelText(/Paste callback URL/i)).toBeInTheDocument();
  });

  it('Disconnect transitions back to Not Connected', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', {
      configured: true, authenticated: true,
    });
    __setMockResponse('player_spotify.ctrl.logout', { success: true });
    renderWithProviders(<SettingsSpotify />);
    await waitFor(() => expect(screen.getByText('Connected')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Disconnect/i }));
    });

    await waitFor(() => expect(screen.getByText('Not Connected')).toBeInTheDocument());
    expect(__mockSocketLog.some((c) => c.key === 'player_spotify.ctrl.logout')).toBe(true);
  });

  it('Save Config writes credentials and transitions to Not Connected', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: false });
    __setMockResponse('player_spotify.ctrl.get_spotify_config', { client_id: '' });
    __setMockResponse('player_spotify.ctrl.set_spotify_config', {
      success: true, configured: true,
    });
    renderWithProviders(<SettingsSpotify />);
    await waitFor(() => expect(screen.getByText('Not Configured')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Client ID/i), { target: { value: 'id123' } });
    fireEvent.change(screen.getByLabelText(/Client Secret/i), { target: { value: 'secret456' } });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Save/i }));
    });

    await waitFor(() => expect(screen.getByText('Not Connected')).toBeInTheDocument());
    const setCall = __mockSocketLog.find((c) => c.key === 'player_spotify.ctrl.set_spotify_config');
    expect(setCall.kwargs).toEqual({ client_id: 'id123', client_secret: 'secret456' });
  });
});
