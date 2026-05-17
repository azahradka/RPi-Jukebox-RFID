import React from 'react';
import { render, screen } from '@testing-library/react';

import SpotifyStatusDisplay from './SpotifyStatusDisplay';

describe('SpotifyStatusDisplay', () => {
  it.each([
    ['authenticated', /Connected/i],
    ['unconfigured', /Not Configured/i],
    ['unauthenticated', /Not Connected/i],
  ])('renders the chip for status=%s', (status, matcher) => {
    render(<SpotifyStatusDisplay authStatus={status} />);
    expect(screen.getByText(matcher)).toBeInTheDocument();
  });
});
