/**
 * Tests for ``useSubscription`` — Phase 4, Web UI quick wins.
 *
 * These tests exercise the real ``PubSubProvider`` (with its store) and the
 * real ``useSubscription`` hook. We use the Phase 0b ``mockSocket`` harness
 * to simulate backend pushes via ``__publishMockMessage``, then assert on
 * rendered output AND on per-component render counts.
 *
 * Reversion check: if ``PubSubProvider`` is reverted to a single
 * ``useState`` object, the "unrelated topic does not re-render"
 * assertions fail because every context consumer re-renders on any
 * change.
 */

import React, { useRef } from 'react';
import { render, screen, act } from '@testing-library/react';

import {
  __publishMockMessage,
  __resetMockSocket,
} from '../test-utils/mockSocket';
import PubSubProvider from '../context/pubsub';
import useSubscription from './useSubscription';

jest.mock('../sockets', () => require('../test-utils/mockSocket'));

const Probe = ({ topic, onRender }) => {
  const renderCount = useRef(0);
  renderCount.current += 1;
  if (onRender) onRender(renderCount.current);
  const value = useSubscription(topic);
  return <div data-testid={`probe-${topic}`}>{JSON.stringify(value)}</div>;
};

describe('useSubscription', () => {
  beforeEach(() => {
    __resetMockSocket();
  });

  it('returns undefined before any push', () => {
    render(
      <PubSubProvider>
        <Probe topic="volume.level" />
      </PubSubProvider>
    );
    expect(screen.getByTestId('probe-volume.level').textContent).toBe('');
  });

  it('renders the latest pushed value for its topic', () => {
    render(
      <PubSubProvider>
        <Probe topic="volume.level" />
      </PubSubProvider>
    );
    act(() => {
      __publishMockMessage('volume.level', { volume: 42, mute: false });
    });
    expect(screen.getByTestId('probe-volume.level').textContent)
      .toBe(JSON.stringify({ volume: 42, mute: false }));
  });

  it('does NOT re-render when an unrelated topic is published', () => {
    let cardsRenders = 0;
    let volumeRenders = 0;
    render(
      <PubSubProvider>
        <Probe topic="rfid.card_id" onRender={(n) => { cardsRenders = n; }} />
        <Probe topic="volume.level" onRender={(n) => { volumeRenders = n; }} />
      </PubSubProvider>
    );
    const cardsAtMount = cardsRenders;
    const volumeAtMount = volumeRenders;

    act(() => {
      __publishMockMessage('volume.level', { volume: 50, mute: false });
    });

    // The volume probe re-rendered, the cards probe did NOT.
    expect(volumeRenders).toBeGreaterThan(volumeAtMount);
    expect(cardsRenders).toBe(cardsAtMount);
  });

  it('re-renders when its own topic changes after another topic was published', () => {
    let cardsRenders = 0;
    render(
      <PubSubProvider>
        <Probe topic="rfid.card_id" onRender={(n) => { cardsRenders = n; }} />
      </PubSubProvider>
    );
    const baseline = cardsRenders;

    act(() => {
      __publishMockMessage('volume.level', { volume: 10, mute: false });
    });
    expect(cardsRenders).toBe(baseline);

    act(() => {
      __publishMockMessage('rfid.card_id', '0123456789');
    });
    expect(cardsRenders).toBeGreaterThan(baseline);
    expect(screen.getByTestId('probe-rfid.card_id').textContent)
      .toBe(JSON.stringify('0123456789'));
  });

  it('notifies subscribers when a topic is removed via functional update', () => {
    // CardsRegister deletes ``rfid.card_id`` after consuming it via
    // ``setState(state => omit(['rfid.card_id'], state))``. Subscribers
    // must observe the value going back to ``undefined``.
    const Consumer = () => {
      const ctx = React.useContext(require('../context/pubsub/context').default);
      return (
        <button data-testid="clear" onClick={() => ctx.setState((s) => {
          const copy = { ...s };
          delete copy['rfid.card_id'];
          return copy;
        })}>clear</button>
      );
    };
    render(
      <PubSubProvider>
        <Probe topic="rfid.card_id" />
        <Consumer />
      </PubSubProvider>
    );
    act(() => {
      __publishMockMessage('rfid.card_id', 'abc');
    });
    expect(screen.getByTestId('probe-rfid.card_id').textContent)
      .toBe(JSON.stringify('abc'));

    act(() => {
      screen.getByTestId('clear').click();
    });
    expect(screen.getByTestId('probe-rfid.card_id').textContent).toBe('');
  });
});
