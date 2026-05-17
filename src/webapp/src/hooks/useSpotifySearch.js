import { useCallback, useEffect, useState } from 'react';

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

  const performSearch = useCallback(async (q) => {
    const trimmed = (q || '').trim();
    if (trimmed.length < 2) {
      setResults([]);
      setSearchPerformed(false);
      return;
    }

    setSearching(true);
    setError(null);
    setSearchPerformed(true);

    try {
      const { result } = await request('spotifySearch', {
        query: trimmed,
        content_type: contentType,
        limit,
      });
      if (result && result.items) {
        setResults(result.items);
      } else {
        setResults([]);
      }
    } catch (err) {
      setError((err && err.message) || 'Search failed');
      setResults([]);
    } finally {
      setSearching(false);
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
