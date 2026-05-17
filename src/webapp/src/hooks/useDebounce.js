import { useEffect, useState } from 'react';

/**
 * Returns ``value`` debounced by ``delayMs``: the returned state only
 * updates after ``value`` has been stable for ``delayMs`` milliseconds.
 *
 * Phase 4 (Web UI quick wins) uses this in the Spotify and Podcast
 * search inputs to coalesce per-keystroke RPC calls into a single
 * trailing request once the user has stopped typing for ~300ms. See
 * meta-plan §"Phase 4".
 *
 *     const debouncedQuery = useDebounce(searchQuery, 300);
 *     useEffect(() => { performSearch(debouncedQuery); }, [debouncedQuery]);
 *
 * If the caller passes ``delayMs <= 0`` the value passes through with
 * no debounce; the effect still runs once per change so test code can
 * exercise the no-debounce path deterministically.
 */
const useDebounce = (value, delayMs = 300) => {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    if (delayMs <= 0) {
      setDebounced(value);
      return undefined;
    }
    const handle = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(handle);
  }, [value, delayMs]);

  return debounced;
};

export default useDebounce;
