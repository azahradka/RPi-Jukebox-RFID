import { useCallback, useEffect, useRef, useState } from 'react';

import request from '../utils/request';
import useDebounce from './useDebounce';

/**
 * Encapsulates the Spotify-search RPC + debounce + filter state.
 *
 * Phase 5b extracts the previously inline state machine from
 * ``SpotifySearch`` (~267 LOC presentational + logic) so it can be tested
 * directly against the mockSocket harness.
 *
 * Behaviour:
 *   - Calls ``spotifySearch`` only when the typed query is >= 2 chars.
 *   - Debounces typed input by ``debounceMs`` (default 300ms) using Phase
 *     4's ``useDebounce``.
 *   - ``submitNow(query)`` bypasses the debounce — wire this to a form
 *     submit / Enter key.
 *   - On error: ``error`` is set, ``results`` is cleared, ``searching``
 *     is false.
 *
 * @param {object} [opts]
 * @param {number} [opts.debounceMs=300]  Debounce window for typed input.
 * @param {string} [opts.contentType]     ``content_type`` passed to the
 *     backend search call.
 * @param {number} [opts.limit=10]        Items per result page.
 *
 * @returns {{
 *   query: string,
 *   setQuery: (q: string) => void,
 *   results: Array,
 *   searching: boolean,
 *   error: string|null,
 *   searchPerformed: boolean,
 *   activeFilter: string|null,
 *   setActiveFilter: (f: string|null) => void,
 *   filteredResults: Array,
 *   submitNow: (q?: string) => Promise<void>,
 * }}
 */
const useSpotifySearch = ({
  debounceMs = 300,
  contentType = 'playlist,album,track,show',
  limit = 10,
} = {}) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState(null);
  const [searchPerformed, setSearchPerformed] = useState(false);
  const [activeFilter, setActiveFilter] = useState(null);

  // Phase 5b race-condition guard. Without this, an in-flight request
  // for an older query (e.g. "ab") can land *after* a newer request
  // (e.g. "abc") and overwrite the newer results. The ref tracks the
  // most recently dispatched query; responses for stale queries are
  // discarded.
  const latestQueryRef = useRef(null);

  const performSearch = useCallback(async (q) => {
    const trimmed = (q || '').trim();
    if (trimmed.length < 2) {
      latestQueryRef.current = trimmed;
      setResults([]);
      setSearchPerformed(false);
      return;
    }

    // Mark this query as the latest dispatched. Responses are only
    // applied if this ref still matches when the reply arrives.
    latestQueryRef.current = trimmed;
    setSearching(true);
    setError(null);
    setSearchPerformed(true);

    try {
      const { result } = await request('spotifySearch', {
        query: trimmed,
        content_type: contentType,
        limit,
      });
      // Stale-response guard: a newer query has been dispatched since
      // we issued this request. Drop the result.
      if (latestQueryRef.current !== trimmed) {
        return;
      }
      if (result && result.items) {
        setResults(result.items);
      } else {
        setResults([]);
      }
    } catch (err) {
      // Same stale-response guard applies to errors so an old failure
      // does not clobber a newer in-flight search's UI state.
      if (latestQueryRef.current !== trimmed) {
        return;
      }
      setError((err && err.message) || 'Search failed');
      setResults([]);
    } finally {
      // Only flip ``searching`` off if this is still the latest query.
      // A stale completion must not unset the spinner for the live one.
      if (latestQueryRef.current === trimmed) {
        setSearching(false);
      }
    }
  }, [contentType, limit]);

  // Phase 4 debounce: rapid keystrokes coalesce into a single trailing
  // RPC. The submit handler / Enter key bypass via ``submitNow``.
  const debouncedQuery = useDebounce(query, debounceMs);
  useEffect(() => {
    if (debouncedQuery && debouncedQuery.trim().length >= 2) {
      performSearch(debouncedQuery);
    }
  }, [debouncedQuery, performSearch]);

  const submitNow = useCallback(async (q) => {
    await performSearch(q !== undefined ? q : query);
  }, [performSearch, query]);

  const filteredResults = activeFilter
    ? results.filter((item) => item.type === activeFilter)
    : results;

  return {
    query,
    setQuery,
    results,
    searching,
    error,
    searchPerformed,
    activeFilter,
    setActiveFilter,
    filteredResults,
    submitNow,
  };
};

export default useSpotifySearch;
