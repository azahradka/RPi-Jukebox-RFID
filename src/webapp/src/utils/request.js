import { socketRequest } from "../sockets";
import commands from "../commands";

/**
 * Issue an RPC request to the jukebox backend.
 *
 * Phase 1, fix #7: the legacy ``catch`` branch returned ``{ error }``
 * which let every call-site silently ignore RPC failures (most do).
 * The new behaviour:
 *
 *   1. Errors now *throw*. A top-level error boundary in
 *      ``App.js`` catches unhandled errors and presents a retry to
 *      the user. Components that handle errors locally can still wrap
 *      with ``try/catch`` or ``.catch``.
 *   2. The return shape is still ``{ result }`` on success — every
 *      existing destructure (``const { result } = await request(...)``)
 *      continues to work.
 *   3. The previous backwards-compat shape ``{ result, error }`` is
 *      preserved when callers opt-in with ``{ swallow: true }`` as the
 *      third argument. New code should not use this.
 *
 * An in-band ``{ error: ... }`` payload from the backend is promoted
 * to a thrown ``Error`` so it cannot be silently consumed either.
 */
const request = async (command, kwargs = {}, options = {}) => {
  const { swallow = false } = options;
  try {
    if (!(command in commands)) {
      throw new Error(`'${command}' does not exist in command object`);
    }

    const { _package, plugin, method = null } = commands[command];
    const result = await socketRequest(_package, plugin, method, kwargs);

    if (result && typeof result === 'object' && result.error) {
      const err = new Error(
        typeof result.error === 'string'
          ? result.error
          : JSON.stringify(result.error)
      );
      err.command = command;
      err.rpcError = result.error;
      throw err;
    }
    return { result };
  }
  catch (error) {
    console.error(`${command}: `, error);
    if (swallow) {
      return { error };
    }
    throw error;
  }
};

export default request;
