import React, { useCallback, useEffect, useMemo, useState } from 'react';

import AppSettingsContext from './context';
import request from '../../utils/request';

/**
 * Phase 4: AppSettings context now exposes a ``refresh()`` callback that
 * re-fetches the server-side settings. Settings save paths (e.g. the
 * show-covers toggle) call ``refresh()`` after a successful mutation so
 * the UI reflects the persisted state rather than a locally-optimistic
 * copy.
 *
 * ``setSettings`` is preserved for backwards compatibility (callers that
 * shallow-merged in optimistic state). New code should prefer ``refresh``.
 */
const AppSettingsProvider = ({ children }) => {
  const [settings, setSettings] = useState({});

  const refresh = useCallback(async () => {
    try {
      const { result } = await request('getAppSettings');
      if (result) setSettings(result);
    } catch (err) {
      // The top-level ErrorBoundary will surface uncaught errors. We
      // also keep the legacy console.error so the failure is visible in
      // dev logs when the boundary isn't active (e.g. tests).
      // eslint-disable-next-line no-console
      console.error('Error loading AppSettings', err);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const context = useMemo(
    () => ({ setSettings, settings, refresh }),
    [settings, refresh],
  );

  return (
    <AppSettingsContext.Provider value={context}>
      {children}
    </AppSettingsContext.Provider>
  );
};

export default AppSettingsProvider;
