import React, { useEffect, useMemo, useRef } from 'react';
import { without } from 'ramda';

import PubSubContext from './context';
import createPubSubStore from './store';
import { initSockets } from '../../sockets';
import { SUBSCRIPTIONS } from '../../config';

/**
 * Phase 4 (Web UI quick wins): re-render fix.
 *
 * The previous implementation held all PubSub topics in a single
 * ``useState`` object inside this provider. Any backend push (e.g.
 * ``volume.level`` while dragging the volume slider) forced every
 * ``useContext(PubSubContext)`` consumer — including the entire Cards
 * page — to re-render.
 *
 * The provider now owns a topic-keyed store with per-topic subscribers
 * (see ``store.js``). Consumers read individual topics via
 * ``useSubscription(topic)`` (see ``src/hooks/useSubscription.js``) which
 * uses a manual ``useState`` + ``useEffect`` shim (React 17 does not ship
 * ``useSyncExternalStore``; the shim follows the official
 * ``use-sync-external-store`` polyfill) to re-render only on changes to
 * that topic. Phase 5b FU: docstring corrected to match the actual
 * implementation. A React 18 upgrade would let us drop the shim.
 *
 * The context value (``{ store, setState }``) is stable for the lifetime
 * of the provider, so context consumers no longer re-render at all when
 * topics update; they only re-render through their own
 * ``useSubscription`` calls.
 */
const PubSubProvider = ({ children }) => {
  // ``useRef`` keeps the store stable across renders (vs ``useMemo`` which
  // React is allowed to discard).
  const storeRef = useRef();
  if (!storeRef.current) {
    storeRef.current = createPubSubStore();
  }
  const store = storeRef.current;

  useEffect(() => {
    initSockets({
      events: without(['playerstatus'], SUBSCRIPTIONS),
      setState: store.setState,
    });
  }, [store]);

  const context = useMemo(
    () => ({ store, setState: store.setState }),
    [store],
  );

  return (
    <PubSubContext.Provider value={context}>
      {children}
    </PubSubContext.Provider>
  );
};

export default PubSubProvider;
