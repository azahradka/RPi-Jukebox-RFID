/**
 * Extract the OAuth authorization code from a callback URL.
 * Accepts either a full URL (http://127.0.0.1:8888/callback?code=xxx)
 * or just the code value itself.
 *
 * Hoisted out of the SettingsSpotify monolith (Phase 5b) so it's
 * trivially unit-testable and reusable by the auth hook + form.
 */
export function extractCode(input) {
  const trimmed = (input || '').trim();
  if (!trimmed) return null;

  // Try parsing as a URL with a ?code= param
  try {
    const url = new URL(trimmed);
    const code = url.searchParams.get('code');
    if (code) return code;
  } catch {
    // Not a valid URL — fall through
  }

  // If it looks like a bare code (no spaces, no '?' at start), accept it
  if (/^[A-Za-z0-9_-]+$/.test(trimmed)) {
    return trimmed;
  }

  return null;
}

export default extractCode;
