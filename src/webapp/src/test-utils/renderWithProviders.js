import React from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import AppSettingsProvider from '../context/appsettings';
import PubSubProvider from '../context/pubsub';
import PlayerProvider from '../context/player';

/**
 * Wraps `ui` in the full provider stack used by the Phoniebox Web UI
 * (AppSettings, PubSub, Player) plus a `MemoryRouter` for route-driven
 * components.
 *
 * The provider effects internally call into `../sockets`, which tests
 * should mock via:
 *
 *     jest.mock('../../sockets', () => require('../../test-utils/mockSocket'));
 *
 * Options:
 *   - `route`: initial route for `MemoryRouter` (default '/').
 *
 * Returns the standard React Testing Library render result.
 */
export const renderWithProviders = (ui, { route = '/', ...renderOptions } = {}) => {
  const Wrapper = ({ children }) => (
    <MemoryRouter initialEntries={[route]}>
      <AppSettingsProvider>
        <PubSubProvider>
          <PlayerProvider>
            {children}
          </PlayerProvider>
        </PubSubProvider>
      </AppSettingsProvider>
    </MemoryRouter>
  );
  return render(ui, { wrapper: Wrapper, ...renderOptions });
};

export default renderWithProviders;
