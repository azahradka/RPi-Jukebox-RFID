/**
 * Phase 4 behavioural test for AppSettings refresh-on-save.
 *
 * Drives the real ShowCovers component (no parallel implementation)
 * through ``renderWithProviders`` + the Phase 0b mockSocket. Asserts
 * that toggling the switch fires ``setAppSettings`` AND a subsequent
 * ``getAppSettings`` refresh.
 *
 * Reversion check: remove the ``refresh()`` call from
 * ``updateShowCoversSetting`` (or remove ``refresh`` from the context)
 * and the test fails because no second ``getAppSettings`` is observed
 * after the switch.
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

const ShowCovers = require('./show-covers').default;

describe('ShowCovers refresh-on-save', () => {
  beforeEach(() => {
    __resetMockSocket();
    __setMockResponse('misc.get_app_settings', { show_covers: false });
    __setMockResponse('misc.set_app_settings', { ok: true });
  });

  it('fires setAppSettings AND refreshes after toggling', async () => {
    renderWithProviders(<ShowCovers />);

    // Wait for the initial getAppSettings to land so we have a stable
    // baseline.
    await waitFor(() => {
      const initial = __mockSocketLog.filter((c) => c.key === 'misc.get_app_settings');
      expect(initial.length).toBeGreaterThanOrEqual(1);
    });

    const baselineGets = __mockSocketLog.filter((c) => c.key === 'misc.get_app_settings').length;

    const toggle = screen.getByRole('checkbox');
    await act(async () => {
      fireEvent.click(toggle);
    });

    // setAppSettings was sent.
    const sets = __mockSocketLog.filter((c) => c.key === 'misc.set_app_settings');
    expect(sets.length).toBe(1);

    // And a refresh getAppSettings followed.
    await waitFor(() => {
      const gets = __mockSocketLog.filter((c) => c.key === 'misc.get_app_settings').length;
      expect(gets).toBe(baselineGets + 1);
    });
  });
});
