import { extractCode } from './extractCode';

describe('extractCode', () => {
  it('returns null for empty or whitespace input', () => {
    expect(extractCode('')).toBeNull();
    expect(extractCode(null)).toBeNull();
    expect(extractCode(undefined)).toBeNull();
    expect(extractCode('   ')).toBeNull();
  });

  it('extracts ?code= from a full callback URL', () => {
    expect(extractCode('http://127.0.0.1:8888/callback?code=ABC123')).toBe('ABC123');
    expect(extractCode('https://example.test/path?code=XYZ&state=foo')).toBe('XYZ');
  });

  it('accepts a bare auth code', () => {
    expect(extractCode('AQ_token-with_underscore-and-dash')).toBe('AQ_token-with_underscore-and-dash');
  });

  it('rejects garbage with spaces', () => {
    expect(extractCode('not a real code')).toBeNull();
  });

  it('rejects a URL without a code= param', () => {
    expect(extractCode('http://example.test/callback')).toBeNull();
  });
});
