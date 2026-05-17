/**
 * Tests for ``useDebounce`` — Phase 4, Web UI quick wins.
 *
 * Reversion check: if the ``setTimeout`` is removed (i.e. the hook just
 * returns ``value`` directly), "debounces rapid changes" fails because the
 * test asserts the intermediate value is NOT reflected until the timer
 * elapses.
 */

import React from 'react';
import { act, render } from '@testing-library/react';

import useDebounce from './useDebounce';

const Probe = ({ value, delayMs }) => {
  const debounced = useDebounce(value, delayMs);
  return <div data-testid="probe">{String(debounced)}</div>;
};

describe('useDebounce', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  it('initial render returns the initial value', () => {
    const { getByTestId } = render(<Probe value="hi" delayMs={300} />);
    expect(getByTestId('probe').textContent).toBe('hi');
  });

  it('debounces rapid changes (only the final value lands)', () => {
    const { getByTestId, rerender } = render(<Probe value="a" delayMs={300} />);
    rerender(<Probe value="ab" delayMs={300} />);
    rerender(<Probe value="abc" delayMs={300} />);

    // Before the timer elapses, the debounced value still reflects the
    // initial 'a'.
    expect(getByTestId('probe').textContent).toBe('a');

    act(() => {
      jest.advanceTimersByTime(150);
    });
    expect(getByTestId('probe').textContent).toBe('a');

    act(() => {
      jest.advanceTimersByTime(200); // total 350ms past last change
    });
    expect(getByTestId('probe').textContent).toBe('abc');
  });

  it('resets the timer on each change', () => {
    const { getByTestId, rerender } = render(<Probe value="x" delayMs={300} />);
    rerender(<Probe value="xy" delayMs={300} />);

    act(() => {
      jest.advanceTimersByTime(200);
    });
    // Another change before the 300ms elapses should reset.
    rerender(<Probe value="xyz" delayMs={300} />);

    act(() => {
      jest.advanceTimersByTime(200); // still <300 after last change
    });
    expect(getByTestId('probe').textContent).toBe('x');

    act(() => {
      jest.advanceTimersByTime(150); // now > 300 since last change
    });
    expect(getByTestId('probe').textContent).toBe('xyz');
  });

  it('passes through immediately when delayMs <= 0', () => {
    const { getByTestId, rerender } = render(<Probe value="a" delayMs={0} />);
    rerender(<Probe value="b" delayMs={0} />);
    // ``useEffect`` still fires synchronously enough that
    // ``advanceTimersByTime(0)`` is sufficient.
    act(() => {
      jest.advanceTimersByTime(0);
    });
    expect(getByTestId('probe').textContent).toBe('b');
  });
});
