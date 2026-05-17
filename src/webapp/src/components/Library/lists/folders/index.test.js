/**
 * Phase 4 behavioural tests for the Folders loading + error states.
 *
 * Drives the real ``Folders`` component through ``renderWithProviders`` +
 * mockSocket — no parallel implementation. Reversion check: removing
 * the ``setIsLoading`` toggle around ``request`` fails the loading
 * assertion; removing the ``swallow: true`` opt-in re-routes the error
 * to the top-level boundary and the inline error assertion fails.
 */

import React from 'react';
import { act, screen, waitFor } from '@testing-library/react';

import {
  __resetMockSocket,
  __setMockResponse,
} from '../../../../test-utils/mockSocket';
import { renderWithProviders } from '../../../../test-utils/renderWithProviders';

jest.mock('../../../../sockets', () => require('../../../../test-utils/mockSocket'));

const Folders = require('./index').default;

describe('Folders loading + error', () => {
  beforeEach(() => {
    __resetMockSocket();
  });

  it('renders the labelled loading state while folderList is in flight', async () => {
    // Hold the RPC pending so the loading state is observable.
    let resolveCall;
    __setMockResponse(
      'player.ctrl.get_folder_content',
      new Promise((resolve) => { resolveCall = resolve; })
    );

    renderWithProviders(<Folders musicFilter="" isSelecting={false} registerMusicToCard={() => {}} />);
    expect(screen.getByTestId('folder-list-loading')).toBeInTheDocument();

    await act(async () => {
      resolveCall([]);
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(screen.queryByTestId('folder-list-loading')).not.toBeInTheDocument()
    );
  });

  it('renders an inline error (not the top-level boundary) on RPC failure', async () => {
    __setMockResponse('player.ctrl.get_folder_content', new Error('mpd offline'));

    renderWithProviders(<Folders musicFilter="" isSelecting={false} registerMusicToCard={() => {}} />);

    await waitFor(() =>
      expect(screen.getByTestId('folder-list-error')).toBeInTheDocument()
    );
  });
});
