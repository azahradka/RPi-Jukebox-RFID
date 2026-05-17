/**
 * Phase 4: page-scoped error boundaries.
 *
 * Verifies that a render-time error in one page (Library) is contained:
 * the scoped fallback renders and the Navigation surface is still
 * present. Reversion check: remove the per-page ``ErrorBoundary`` wrap
 * around the failing route and the test fails because the error
 * propagates to the top-level boundary, which replaces the entire app.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';

// Replace the Library component with a Bomb that always throws.
jest.mock('./components/Library', () => () => {
  throw new Error('library exploded');
});

// Stub other heavy pages so this test stays narrow.
jest.mock('./components/Player', () => () => <div data-testid="player-ok">player</div>);
jest.mock('./components/Cards', () => () => <div data-testid="cards-ok">cards</div>);
jest.mock('./components/Settings', () => () => <div data-testid="settings-ok">settings</div>);
jest.mock('./components/Navigation', () => () => <div data-testid="nav">nav</div>);

// HashRouter doesn't honour initial entries; swap to a MemoryRouter so we
// can route to /#/library deterministically.
jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('react-router-dom');
  return {
    ...actual,
    HashRouter: ({ children }) => (
      <actual.MemoryRouter initialEntries={['/library/foo']}>
        {children}
      </actual.MemoryRouter>
    ),
  };
});

const Router = require('./router').default;

describe('Page-scoped error boundaries', () => {
  beforeEach(() => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    console.error.mockRestore();
  });

  it('contains a Library render error inside the Library boundary', () => {
    render(<Router />);

    // Scoped fallback is shown for the failing page.
    expect(screen.getByTestId('ui-error-boundary-Library')).toBeInTheDocument();
    expect(screen.getByText(/library exploded/i)).toBeInTheDocument();

    // Crucially, Navigation is still rendered — the rest of the app
    // wasn't taken down by the page-local error.
    expect(screen.getByTestId('nav')).toBeInTheDocument();
  });
});
