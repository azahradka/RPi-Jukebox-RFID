/**
 * Tests for the top-level ErrorBoundary — Phase 1, fix #7.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';

import ErrorBoundary from './index';

const Bomb = ({ message }) => {
  throw new Error(message);
};

describe('ErrorBoundary', () => {
  beforeEach(() => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    console.error.mockRestore();
  });

  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">ok</div>
      </ErrorBoundary>
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  it('renders the error message when a child throws', () => {
    render(
      <ErrorBoundary>
        <Bomb message="exploded during render" />
      </ErrorBoundary>
    );
    const alert = screen.getByTestId('ui-error-boundary');
    expect(alert).toHaveTextContent('exploded during render');
  });

  it('retry button clears the error and re-renders children', () => {
    let shouldThrow = true;
    const Conditional = () => {
      if (shouldThrow) throw new Error('temporary');
      return <div data-testid="recovered">recovered</div>;
    };

    render(
      <ErrorBoundary>
        <Conditional />
      </ErrorBoundary>
    );
    expect(screen.getByTestId('ui-error-boundary')).toBeInTheDocument();
    shouldThrow = false;
    fireEvent.click(screen.getByTestId('ui-error-boundary-retry'));
    expect(screen.getByTestId('recovered')).toBeInTheDocument();
  });
});
