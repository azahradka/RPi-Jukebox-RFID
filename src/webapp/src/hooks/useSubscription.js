import { useContext, useEffect, useState } from 'react';

import PubSubContext from '../context/pubsub/context';

/**
 * Subscribe to a single PubSub topic without re-rendering on unrelated
 * topic pushes.
 *
 * The legacy ``PubSubProvider`` held every backend push (``volume.level``,
 * ``playerstatus``, ``rfid.card_id``, podcast download events, ...) in
 * one ``useState`` object. Any consumer that did
 * ``const { state } = useContext(PubSubContext)`` therefore re-rendered on
 * every push — a volume slider drag re-rendered the entire Cards list.
 *
 * Phase 4 (Web UI quick wins) replaces the underlying state with a small
 * subscribable store kept on a stable context value (see
 * ``context/pubsub/store.js``). ``useSubscription`` subscribes to a single
 * topic and only re-renders when that topic's value changes by reference.
 *
 * Implementation note: React 17 ships without ``useSyncExternalStore``;
 * the equivalent ``useState`` + ``useEffect`` pattern below is what the
 * official ``use-sync-external-store`` shim does internally. We avoid the
 * extra dependency since the store is single-process and not concurrent.
 *
 * Usage:
 *
 *     const volume = useSubscription('volume.level');
 *
 * Returns the latest data published for ``topic``, or ``undefined`` if the
 * backend has not pushed that topic yet.
 */
const useSubscription = (topic) => {
  const { store } = useContext(PubSubContext);
  const [value, setValue] = useState(() => store.get(topic));

  useEffect(() => {
    // Re-sync on mount in case the topic changed between render and
    // effect, then subscribe for future updates.
    setValue(store.get(topic));
    const unsubscribe = store.subscribe(topic, () => {
      setValue(store.get(topic));
    });
    return unsubscribe;
  }, [store, topic]);

  return value;
};

export default useSubscription;
