#!/usr/bin/env node
/* eslint-disable no-console */
/**
 * Phase 5a: regenerate ``src/webapp/src/commands/index.js`` from the
 * canonical Python source of truth.
 *
 * Inputs
 * ------
 * * ``src/jukebox/components/rpc_command_alias.py``
 *     - ``web_command_definitions`` — Web UI RPC catalog (REQUIRED).
 *     - ``KNOWN_PLUGIN_METHOD_ALLOWLIST`` — validator escape hatch for
 *       (package, plugin, method) triples that cannot be discovered by
 *       AST scanning (flat modules, dynamic subclass registrations).
 *     - ``KNOWN_INTERNAL_PLUGIN_METHODS`` — triples the generator MUST
 *       NOT emit to the JS file even if web_command_definitions
 *       accidentally lists them.
 * * ``src/jukebox/components/...py`` — AST-scanned for
 *   ``@plugs.tag`` and ``@plugs.register`` decorators to build the
 *   registry of valid plugin methods.
 * * ``resources/default-settings/jukebox.default.yaml`` — read for the
 *   ``modules.named`` alias-to-directory mapping (so we know
 *   ``player`` => ``playermpd`` etc.).
 *
 * Output
 * ------
 * * ``src/webapp/src/commands/index.js`` — overwritten with a
 *   generated header + deterministic command map.
 *
 * Validation (build-fail on mismatch)
 * -----------------------------------
 * For every entry in ``web_command_definitions``:
 *   1. The resolved ``(package, plugin, method)`` triple must exist in
 *      either the AST-discovered registry OR the explicit allowlist.
 *   2. The triple must NOT be in the internal-only set.
 *
 * Generator failures exit with a non-zero status and print a clear
 * error message naming the offending entry.
 *
 * Usage
 * -----
 *   node scripts/generate-commands.js              # regenerate
 *   node scripts/generate-commands.js --check      # exit 1 if file
 *                                                  # would change
 *   node scripts/generate-commands.js --src=PATH   # alternate Python
 *                                                  # source-of-truth
 */

'use strict';

const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const DEFAULT_PY_SOURCE = path.join(
  REPO_ROOT, 'src', 'jukebox', 'components', 'rpc_command_alias.py'
);
const DEFAULT_COMPONENTS_ROOT = path.join(
  REPO_ROOT, 'src', 'jukebox', 'components'
);
const DEFAULT_YAML_PATH = path.join(
  REPO_ROOT, 'resources', 'default-settings', 'jukebox.default.yaml'
);
const DEFAULT_JS_TARGET = path.join(
  REPO_ROOT, 'src', 'webapp', 'src', 'commands', 'index.js'
);

// ---------------------------------------------------------------------------
// CLI args
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const opts = {
    pySource: DEFAULT_PY_SOURCE,
    componentsRoot: DEFAULT_COMPONENTS_ROOT,
    yamlPath: DEFAULT_YAML_PATH,
    jsTarget: DEFAULT_JS_TARGET,
    check: false,
    quiet: false,
  };
  for (const arg of argv.slice(2)) {
    if (arg === '--check') opts.check = true;
    else if (arg === '--quiet') opts.quiet = true;
    else if (arg.startsWith('--src=')) opts.pySource = path.resolve(arg.slice(6));
    else if (arg.startsWith('--components=')) opts.componentsRoot = path.resolve(arg.slice(13));
    else if (arg.startsWith('--yaml=')) opts.yamlPath = path.resolve(arg.slice(7));
    else if (arg.startsWith('--target=')) opts.jsTarget = path.resolve(arg.slice(9));
    else if (arg === '--help' || arg === '-h') {
      printUsage();
      process.exit(0);
    } else {
      console.error(`Unknown argument: ${arg}`);
      printUsage();
      process.exit(2);
    }
  }
  return opts;
}

function printUsage() {
  console.error(`Usage: node generate-commands.js [--check] [--quiet]
                                     [--src=PATH] [--target=PATH]
                                     [--components=PATH] [--yaml=PATH]`);
}

// ---------------------------------------------------------------------------
// Python dict parser
// ---------------------------------------------------------------------------
// Limited Python literal parser sufficient for the strict subset used by
// rpc_command_alias.py: dict / set / frozenset / list / tuple / str /
// bool / None / int literals. Strings can be single- or double-quoted
// (no escapes beyond \n \t \\ \' \"). Trailing commas allowed. No
// expressions, no comprehensions.

class PyParser {
  constructor(src) {
    this.src = src;
    this.i = 0;
  }
  eof() { return this.i >= this.src.length; }
  peek() { return this.src[this.i]; }
  skip() {
    while (!this.eof()) {
      const c = this.peek();
      if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { this.i++; }
      else if (c === '#') {
        while (!this.eof() && this.peek() !== '\n') this.i++;
      } else break;
    }
  }
  expect(ch) {
    this.skip();
    if (this.peek() !== ch) {
      throw new Error(`Parse error at offset ${this.i}: expected '${ch}', got '${this.peek()}'`);
    }
    this.i++;
  }
  readString() {
    this.skip();
    const quote = this.peek();
    if (quote !== '"' && quote !== "'") {
      throw new Error(`Parse error at offset ${this.i}: expected string, got '${this.peek()}'`);
    }
    this.i++;
    let out = '';
    while (!this.eof() && this.peek() !== quote) {
      if (this.peek() === '\\') {
        this.i++;
        const esc = this.peek();
        if (esc === 'n') out += '\n';
        else if (esc === 't') out += '\t';
        else if (esc === '\\') out += '\\';
        else if (esc === "'") out += "'";
        else if (esc === '"') out += '"';
        else out += esc;
        this.i++;
      } else {
        out += this.peek();
        this.i++;
      }
    }
    if (this.eof()) throw new Error('Parse error: unterminated string');
    this.i++; // closing quote
    return out;
  }
  readIdent() {
    this.skip();
    let out = '';
    while (!this.eof() && /[A-Za-z0-9_]/.test(this.peek())) {
      out += this.peek();
      this.i++;
    }
    return out;
  }
  readValue() {
    this.skip();
    const c = this.peek();
    if (c === '"' || c === "'") return this.readString();
    if (c === '{') return this.readDictOrSet();
    if (c === '[') return this.readList();
    if (c === '(') return this.readTuple();
    // bool / None / int / frozenset(...) / etc.
    const ident = this.readIdent();
    if (ident === 'True') return true;
    if (ident === 'False') return false;
    if (ident === 'None') return null;
    if (ident === 'frozenset' || ident === 'set' || ident === 'tuple' || ident === 'list') {
      this.skip();
      this.expect('(');
      this.skip();
      // accept empty () or a single iterable arg
      if (this.peek() === ')') { this.i++; return ident === 'tuple' || ident === 'list' ? [] : new Set(); }
      const inner = this.readValue();
      this.skip();
      this.expect(')');
      if (ident === 'frozenset' || ident === 'set') {
        // ``inner`` may be either a Set (returned by readDictOrSet for
        // a ``{...}`` literal — already JSON-stringified members) or
        // an array (from ``frozenset([...])``). Normalise so the
        // returned Set's members are JSON-stringified once and only
        // once.
        if (inner instanceof Set) return inner;
        const arr = Array.isArray(inner) ? inner : Array.from(inner);
        return new Set(arr.map(v => JSON.stringify(v)));
      }
      return inner;
    }
    if (/^-?\d+$/.test(ident)) return parseInt(ident, 10);
    throw new Error(`Parse error at offset ${this.i}: unexpected identifier '${ident}'`);
  }
  readList() {
    this.expect('[');
    const out = [];
    this.skip();
    if (this.peek() === ']') { this.i++; return out; }
    while (true) {
      out.push(this.readValue());
      this.skip();
      if (this.peek() === ',') { this.i++; this.skip(); }
      if (this.peek() === ']') { this.i++; return out; }
    }
  }
  readTuple() {
    this.expect('(');
    const out = [];
    this.skip();
    if (this.peek() === ')') { this.i++; return out; }
    while (true) {
      out.push(this.readValue());
      this.skip();
      if (this.peek() === ',') { this.i++; this.skip(); }
      if (this.peek() === ')') { this.i++; return out; }
    }
  }
  readDictOrSet() {
    this.expect('{');
    this.skip();
    if (this.peek() === '}') { this.i++; return {}; }
    // Sniff: is it a dict (key: value) or a set?
    const start = this.i;
    const firstKey = this.readValue();
    this.skip();
    if (this.peek() === ':') {
      this.i++;
      const firstVal = this.readValue();
      const out = {};
      out[String(firstKey)] = firstVal;
      this.skip();
      if (this.peek() === ',') { this.i++; }
      this.skip();
      while (this.peek() !== '}') {
        const k = this.readValue();
        this.skip();
        this.expect(':');
        const v = this.readValue();
        out[String(k)] = v;
        this.skip();
        if (this.peek() === ',') { this.i++; }
        this.skip();
      }
      this.i++; // }
      return out;
    } else {
      // Set literal
      const out = new Set();
      out.add(JSON.stringify(firstKey));
      this.skip();
      if (this.peek() === ',') { this.i++; }
      this.skip();
      while (this.peek() !== '}') {
        const v = this.readValue();
        out.add(JSON.stringify(v));
        this.skip();
        if (this.peek() === ',') { this.i++; }
        this.skip();
      }
      this.i++; // }
      return out;
    }
  }
}

/**
 * Extract a single top-level assignment ``NAME = <value>`` from a Python
 * source file. Returns the parsed JS-side value, or undefined.
 *
 * Naïve but sufficient: we anchor on a line that starts with
 * ``NAME = `` at column 0, then hand the remainder of the file to
 * PyParser which stops as soon as the top-level expression closes.
 */
function extractTopLevelAssign(pySrc, name) {
  const lines = pySrc.split('\n');
  let startIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].match(new RegExp(`^${name}\\s*=`))) {
      startIdx = i;
      break;
    }
  }
  if (startIdx === -1) return undefined;
  const headerLine = lines[startIdx];
  const eq = headerLine.indexOf('=');
  const tail = headerLine.slice(eq + 1);
  const rest = [tail, ...lines.slice(startIdx + 1)].join('\n');
  const parser = new PyParser(rest);
  parser.skip();
  return parser.readValue();
}

// ---------------------------------------------------------------------------
// AST-style scanning of plugin decorators
// ---------------------------------------------------------------------------
/**
 * Walk a Python source tree and extract a set of (package, plugin,
 * method) triples that have been registered via the plugs framework.
 *
 * Heuristics (regex-based — Python isn't shellable from JS without a
 * dependency):
 *
 * 1. Module-level ``plugs.register(obj, name='X')`` registers a class
 *    instance under plugin name X. The package alias defaults to the
 *    component's directory but can be overridden by jukebox.yaml.
 *    Every method on that class decorated with ``@plugs.tag`` becomes
 *    callable as ``(package, X, method_name)``. We capture the class
 *    name + method names by parsing the file's ``class Foo:`` /
 *    ``@plugs.tag`` blocks.
 * 2. Top-level ``@plugs.register`` (or ``@plugin.register``) decorates
 *    a function — produces ``(package, function_name, None)``.
 * 3. ``@plugs.register(name='timer_X')`` and friends use the named
 *    plugin slot directly. Methods inside are looked up via
 *    KNOWN_PLUGIN_METHOD_ALLOWLIST since their parent classes can be
 *    dynamic (Timer subclasses).
 *
 * Returns: Set of "alias::plugin::method" strings (method may be 'None').
 */
function scanRegistry(componentsRoot, aliasByDir) {
  const registry = new Set();
  const dirToAlias = invertMap(aliasByDir);

  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name.startsWith('.') || entry.name === '__pycache__') continue;
        walk(p);
      } else if (entry.isFile() && entry.name.endsWith('.py')) {
        scanFile(p);
      }
    }
  }

  function packageAliasFor(filePath) {
    // From filePath, compute the package alias by walking up to find
    // the registered component-directory.
    const rel = path.relative(componentsRoot, filePath).split(path.sep);
    // Try progressively shorter prefixes.
    for (let n = rel.length; n > 0; n--) {
      const key = rel.slice(0, n).join('.').replace(/\.__init__\.py$/, '').replace(/\.py$/, '');
      // Strip __init__ from package key.
      const keyNoInit = key.replace(/\.__init__$/, '');
      if (dirToAlias.has(keyNoInit)) return dirToAlias.get(keyNoInit);
    }
    // Fallback: single-segment directory name (e.g. misc.py top-level).
    const top = rel[0].replace(/\.py$/, '');
    if (dirToAlias.has(top)) return dirToAlias.get(top);
    return null;
  }

  function scanFile(filePath) {
    const src = fs.readFileSync(filePath, 'utf-8');
    const alias = packageAliasFor(filePath);
    if (!alias) return;  // Not a registered component.

    // 1. Find every ``plugs.register(obj, name='X')`` / ``plugs.register(obj, name="X")``
    //    AND ``@plugs.register`` on a class definition.
    // 2. Collect class definitions with their bodies so we know which
    //    @plugs.tag methods belong to which class.

    // Map class name -> {pluginName, methods: [methodName, ...]}.
    const classes = new Map();

    // Pass A: scan for "class Foo" and collect method definitions
    // decorated with @plugs.tag or @plugin.tag. Use a class-stack so
    // an inner-class block doesn't permanently consume the outer class
    // context (volume/__init__.py has nested callback-handler classes
    // inside PulseVolumeControl).
    const lines = src.split('\n');
    /** @type {Array<{name: string, indent: number}>} */
    const classStack = [];
    let pendingDecoratorIsTag = false;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lineTrimmed = line.trimStart();
      const indent = line.length - lineTrimmed.length;
      // Pop class-stack entries whose body has ended (dedent to <=
      // their declared indent on a non-blank, non-decorator line).
      if (lineTrimmed.length > 0) {
        while (classStack.length > 0
               && indent <= classStack[classStack.length - 1].indent) {
          classStack.pop();
        }
      }
      const classMatch = lineTrimmed.match(/^class\s+([A-Za-z_]\w*)\s*(?:\([^)]*\))?:/);
      if (classMatch) {
        const cls = classMatch[1];
        classStack.push({ name: cls, indent });
        if (!classes.has(cls)) {
          classes.set(cls, { methods: [] });
        }
        pendingDecoratorIsTag = false;
        continue;
      }
      // Decorator detection
      if (/^@(plugs|plugin)\.tag\b/.test(lineTrimmed)) {
        pendingDecoratorIsTag = true;
        continue;
      }
      if (/^@/.test(lineTrimmed)) {
        // Other decorators before the def don't reset the tag flag.
        continue;
      }
      const defMatch = lineTrimmed.match(/^def\s+([A-Za-z_]\w*)\s*\(/);
      if (defMatch && pendingDecoratorIsTag) {
        // Attribute to the *innermost* class on the stack. (Nested
        // classes can also expose @plugs.tag methods, but in practice
        // this codebase only tags methods at the outer-class level.)
        if (classStack.length > 0) {
          const cls = classStack[classStack.length - 1].name;
          classes.get(cls).methods.push(defMatch[1]);
        }
        pendingDecoratorIsTag = false;
        continue;
      }
      if (defMatch) {
        pendingDecoratorIsTag = false;
      }
    }

    // Pass B: find ``plugs.register(<expr>, ..., name='X', ...)`` calls
    // to map a class instance to a plugin name. The kwargs may appear
    // in any order (e.g. ``register(obj, package='X', name='Y',
    // replace=True)``); we scan for both the leading positional arg
    // and a name= kwarg within the same parenthesised call.
    const registerCalls = [...src.matchAll(
      /(?:plugs|plugin)\.register\(\s*([A-Za-z_]\w*)\s*,([^)]*)\)/g
    )];
    for (const m of registerCalls) {
      // The first arg is a variable name (e.g. ``player_ctrl``).
      // Find its class via the most recent ``X = ClassName(...)`` or
      // ``global X; X = ClassName()`` pattern. Conservative match:
      const varName = m[1];
      const kwargBlob = m[2];
      const nameMatch = kwargBlob.match(/\bname\s*=\s*['"]([^'"]+)['"]/);
      if (!nameMatch) continue;
      const pluginName = nameMatch[1];
      const ctorRegex = new RegExp(
        `${escapeRegex(varName)}\\s*=\\s*([A-Za-z_]\\w*)\\s*\\(`,
        'g'
      );
      const ctorMatches = [...src.matchAll(ctorRegex)];
      for (const cm of ctorMatches) {
        const cls = cm[1];
        if (classes.has(cls)) {
          for (const method of classes.get(cls).methods) {
            registry.add(`${alias}::${pluginName}::${method}`);
          }
        }
      }
    }

    // Pass B2 (Item 3 init_plugin convention): find
    // ``plugs.register(funcname)`` / ``plugin.register(funcname)``
    // calls where the first argument is a bare identifier. This
    // happens inside ``init_plugin()`` bodies for plugins that
    // migrated to the new convention — module-level decorators
    // would be the only other indicator that ``funcname`` is RPC-
    // callable, and migrating to init_plugin() removes them. So we
    // also accept the function-call style as a registration signal.
    //
    // Heuristic: the identifier must be a module-level ``def``
    // somewhere in the same file. We don't distinguish init_plugin()
    // body from any other call site (out-of-band registrations are
    // not idiomatic anyway).
    const moduleLevelDefs = new Set();
    for (const line of lines) {
      const m = line.match(/^def\s+([A-Za-z_]\w*)\s*\(/);
      if (m) moduleLevelDefs.add(m[1]);
    }
    const bareRegisterCalls = [...src.matchAll(
      /(?:plugs|plugin)\.register\(\s*([A-Za-z_]\w*)\s*\)/g
    )];
    for (const m of bareRegisterCalls) {
      const ident = m[1];
      if (moduleLevelDefs.has(ident)) {
        registry.add(`${alias}::${ident}::None`);
      }
    }

    // Pass C: top-level @plugs.register / @plugin.register
    // (function-style or class-style with auto_tag) — produces
    // (alias, function_name, None).
    pendingDecoratorIsTag = false;
    let pendingRegisterDecorator = false;
    let pendingRegisterAutoTag = false;
    let pendingRegisterName = null;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const lt = line.trimStart();
      const indent = line.length - lt.length;
      // Only top-level (indent 0) matters for function/class @register.
      if (indent !== 0) continue;
      const regMatch = lt.match(/^@(plugs|plugin)\.register(?:\s*\((.*)\))?\s*$/);
      if (regMatch) {
        pendingRegisterDecorator = true;
        const argText = regMatch[2] || '';
        pendingRegisterAutoTag = /auto_tag\s*=\s*True/.test(argText);
        const nameMatch = argText.match(/name=['"]([^'"]+)['"]/);
        pendingRegisterName = nameMatch ? nameMatch[1] : null;
        continue;
      }
      const defMatch = lt.match(/^def\s+([A-Za-z_]\w*)\s*\(/);
      if (defMatch && pendingRegisterDecorator) {
        const name = pendingRegisterName || defMatch[1];
        registry.add(`${alias}::${name}::None`);
        pendingRegisterDecorator = false;
        pendingRegisterName = null;
        pendingRegisterAutoTag = false;
        continue;
      }
      const clsMatch = lt.match(/^class\s+([A-Za-z_]\w*)/);
      if (clsMatch && pendingRegisterDecorator) {
        // @plugs.register on a class — methods accessible via class name
        // (rare in this codebase). Skipped: this codebase only uses the
        // function form at top level. Reset.
        pendingRegisterDecorator = false;
        pendingRegisterName = null;
        pendingRegisterAutoTag = false;
        continue;
      }
      if (/^@/.test(lt)) continue;  // chained decorator
      if (lt.length === 0) continue;  // blank line
      // Anything else at column 0 (assignment, etc) clears state.
      pendingRegisterDecorator = false;
      pendingRegisterName = null;
      pendingRegisterAutoTag = false;
    }
  }

  walk(componentsRoot);
  return registry;
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function invertMap(aliasByDir) {
  const out = new Map();
  for (const [alias, dir] of Object.entries(aliasByDir)) {
    out.set(dir, alias);
  }
  return out;
}

// ---------------------------------------------------------------------------
// jukebox.default.yaml — modules.named parser (minimal)
// ---------------------------------------------------------------------------
function parseModulesNamed(yamlPath) {
  const src = fs.readFileSync(yamlPath, 'utf-8');
  const lines = src.split('\n');
  const out = {};
  let inModulesNamed = false;
  let baseIndent = -1;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*named:\s*$/.test(line) && i > 0 && /^modules:\s*$/.test(lines[i - 1])) {
      inModulesNamed = true;
      baseIndent = -1;
      continue;
    }
    if (!inModulesNamed) continue;
    // End of block: when we hit a top-level (or modules-level) sibling key.
    if (/^[A-Za-z]/.test(line)) { inModulesNamed = false; continue; }
    const m = line.match(/^(\s+)([A-Za-z_][\w.]*)\s*:\s*([A-Za-z_][\w.]*)\s*$/);
    if (m) {
      const indent = m[1].length;
      if (baseIndent === -1) baseIndent = indent;
      if (indent !== baseIndent) {
        // Possibly a sibling (e.g. 'others:'); exit.
        inModulesNamed = false;
        continue;
      }
      out[m[2]] = m[3];
    } else if (/^\s+\w+:\s*$/.test(line) && !/named:/.test(line)) {
      // sibling key like ``others:`` ends the block
      inModulesNamed = false;
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Emit JS
// ---------------------------------------------------------------------------
function quoteJsKey(key) {
  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) return key;
  return `'${key.replace(/'/g, "\\'")}'`;
}

function emitJsCommands(commands) {
  const header = [
    '// THIS FILE IS AUTO-GENERATED — DO NOT EDIT BY HAND.',
    '// Source of truth: src/jukebox/components/rpc_command_alias.py',
    '//                  (web_command_definitions dictionary).',
    '// Regenerate with: npm run generate-commands',
    '// See Phase 5a, src/webapp/scripts/generate-commands.js for details.',
    '',
    'const commands = {',
  ];
  const body = [];
  const entries = Object.entries(commands);
  for (let i = 0; i < entries.length; i++) {
    const [name, spec] = entries[i];
    const lines = [`  ${quoteJsKey(name)}: {`];
    lines.push(`    _package: '${spec.package}',`);
    lines.push(`    plugin: '${spec.plugin}',`);
    if (spec.method !== undefined && spec.method !== null) {
      lines.push(`    method: '${spec.method}',`);
    }
    if (Array.isArray(spec.argKeys) && spec.argKeys.length > 0) {
      const keys = spec.argKeys.map(k => `'${k}'`).join(', ');
      lines.push(`    argKeys: [${keys}],`);
    }
    lines.push('  },');
    body.push(lines.join('\n'));
  }
  const footer = ['};', '', 'export default commands;', ''];
  return [...header, ...body, ...footer].join('\n');
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------
function validate(commands, registry, allowlist, internalSet, aliasByDir) {
  const errors = [];
  const knownAliases = new Set(Object.keys(aliasByDir));
  knownAliases.add('misc'); // listed under modules.others
  // Pre-translate allowlist + internalSet (which are JSON-string sets)
  // into native sets of "alias::plugin::method" keys.
  const allowKeys = setToTriples(allowlist);
  const internalKeys = setToTriples(internalSet);

  for (const [name, spec] of Object.entries(commands)) {
    if (!spec.package || !spec.plugin) {
      errors.push(`'${name}': missing required 'package' or 'plugin'.`);
      continue;
    }
    if (!knownAliases.has(spec.package)) {
      errors.push(`'${name}': unknown package alias '${spec.package}'. ` +
        `Add it to resources/default-settings/jukebox.default.yaml ` +
        `modules.named, or fix the typo.`);
      continue;
    }
    const method = (spec.method === undefined || spec.method === null)
      ? 'None'
      : spec.method;
    const key = `${spec.package}::${spec.plugin}::${method}`;
    if (internalKeys.has(key)) {
      errors.push(`'${name}': resolves to internal-only RPC ` +
        `${spec.package}.${spec.plugin}.${method}. ` +
        `This triple is in KNOWN_INTERNAL_PLUGIN_METHODS and must NOT ` +
        `be exposed to the Web UI.`);
      continue;
    }
    if (!registry.has(key) && !allowKeys.has(key)) {
      errors.push(`'${name}': cannot resolve RPC target ` +
        `${spec.package}.${spec.plugin}` +
        (method === 'None' ? '' : `.${method}`) +
        `. Either:\n` +
        `    - add @plugs.tag / @plugs.register to the Python method\n` +
        `    - or add the triple to KNOWN_PLUGIN_METHOD_ALLOWLIST in ` +
        `rpc_command_alias.py if discovery isn't possible (e.g. flat ` +
        `module or dynamic registration).`);
    }
  }
  return errors;
}

function setToTriples(jsSet) {
  // jsSet members are JSON-stringified arrays like '["pkg","plug","meth"]'.
  const out = new Set();
  for (const member of jsSet) {
    try {
      const arr = JSON.parse(member);
      const method = arr[2] === null ? 'None' : String(arr[2]);
      out.add(`${arr[0]}::${arr[1]}::${method}`);
    } catch { /* skip malformed */ }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
function main() {
  const opts = parseArgs(process.argv);
  const log = opts.quiet ? () => {} : (...args) => console.log(...args);

  const pySrc = fs.readFileSync(opts.pySource, 'utf-8');
  const webCommands = extractTopLevelAssign(pySrc, 'web_command_definitions');
  if (!webCommands || typeof webCommands !== 'object') {
    console.error(`Failed to parse web_command_definitions from ${opts.pySource}`);
    process.exit(1);
  }
  const allowlist = extractTopLevelAssign(pySrc, 'KNOWN_PLUGIN_METHOD_ALLOWLIST') || new Set();
  const internalSet = extractTopLevelAssign(pySrc, 'KNOWN_INTERNAL_PLUGIN_METHODS') || new Set();

  const aliasByDir = parseModulesNamed(opts.yamlPath);
  log(`generate-commands: ${Object.keys(aliasByDir).length} aliases from ${path.relative(REPO_ROOT, opts.yamlPath)}`);

  const registry = scanRegistry(opts.componentsRoot, aliasByDir);
  log(`generate-commands: ${registry.size} plugin methods discovered via AST scan`);

  const errors = validate(webCommands, registry, allowlist, internalSet, aliasByDir);
  if (errors.length > 0) {
    console.error(`\n[generate-commands] VALIDATION FAILED (${errors.length} error${errors.length === 1 ? '' : 's'}):\n`);
    for (const e of errors) console.error(`  * ${e}\n`);
    console.error('No file was written.');
    process.exit(1);
  }

  const generated = emitJsCommands(webCommands);
  const existing = fs.existsSync(opts.jsTarget)
    ? fs.readFileSync(opts.jsTarget, 'utf-8')
    : null;

  if (opts.check) {
    if (existing !== generated) {
      console.error(`[generate-commands] --check failed: ${path.relative(REPO_ROOT, opts.jsTarget)} is out of date. Run 'npm run generate-commands'.`);
      process.exit(1);
    }
    log(`generate-commands: --check ok (${Object.keys(webCommands).length} commands)`);
    return;
  }

  fs.mkdirSync(path.dirname(opts.jsTarget), { recursive: true });
  fs.writeFileSync(opts.jsTarget, generated, 'utf-8');
  log(`generate-commands: wrote ${path.relative(REPO_ROOT, opts.jsTarget)} (${Object.keys(webCommands).length} commands)`);
}

if (require.main === module) {
  main();
}

module.exports = {
  extractTopLevelAssign,
  scanRegistry,
  parseModulesNamed,
  emitJsCommands,
  validate,
  PyParser,
};
