/**
 * Per-topic subscribable store backing ``PubSubProvider``.
 *
 * Why this exists: the previous implementation kept all PubSub topics in
 * a single ``useState`` object, so every backend push (e.g. ``volume.level``
 * during a slider drag) re-rendered every component that read context —
 * including the Cards page. ``createPubSubStore`` exposes a topic-level
 * subscription model that ``useSubscription`` (in ``src/hooks``) drives
 * via ``useSyncExternalStore``. Only consumers of the topic that changed
 * are notified.
 *
 * The store deliberately mirrors the legacy ``state`` shape (a
 * ``{ [topic]: data }`` map) and accepts the same ``setState(updater)``
 * functional-update form used by callers like ``CardsRegister`` that
 * delete a topic after consuming it. Backward-compat shim only — new code
 * should prefer ``useSubscription``.
 */

const createPubSubStore = () => {
  let state = {};
  const listeners = new Map(); // topic -> Set<callback>

  const get = (topic) => state[topic];

  const subscribe = (topic, cb) => {
    let set = listeners.get(topic);
    if (!set) {
      set = new Set();
      listeners.set(topic, set);
    }
    set.add(cb);
    return () => {
      set.delete(cb);
    };
  };

  const notify = (topic) => {
    const set = listeners.get(topic);
    if (set) {
      // Copy to a list so callbacks that unsubscribe during iteration
      // don't mutate the set we're iterating over.
      Array.from(set).forEach((cb) => cb());
    }
  };

  /**
   * Apply ``next`` to the current state map. ``next`` may be either an
   * object to shallow-merge (legacy ``setState({ [topic]: data })`` form)
   * or a function ``(prev) => nextState`` returning the new map.
   *
   * Notifies only the topics whose value changed by reference, plus any
   * topics that were removed from the map (used by ``CardsRegister`` via
   * ``ramda.omit`` to clear a one-shot card swipe).
   */
  const setState = (next) => {
    const prev = state;
    const merged = typeof next === 'function' ? next(prev) : { ...prev, ...next };
    if (merged === prev) return;
    state = merged;

    const changed = new Set();
    Object.keys(merged).forEach((k) => {
      if (prev[k] !== merged[k]) changed.add(k);
    });
    Object.keys(prev).forEach((k) => {
      if (!(k in merged)) changed.add(k);
    });
    changed.forEach(notify);
  };

  /**
   * Snapshot of the full topic map. Used by the legacy
   * ``state``-reading callsites surfaced through context until Phase 4
   * migrates them all to ``useSubscription``. Returns a fresh object so
   * callers cannot mutate the live store.
   */
  const getAll = () => ({ ...state });

  return { get, getAll, subscribe, setState };
};

export default createPubSubStore;
