# NvManager Bug Report: Nested Dict Modifications Not Persisted

## ✅ RESOLVED (2026-02-06)

**Resolution:** NvManager has been removed and replaced with direct JSON persistence using `json.dump()` and `json.load()`.

This approach is simpler, more maintainable, and eliminates the nested dict modification bug. Components now manage their own state files explicitly.

**See implementations:**
- `src/jukebox/components/playermpd/__init__.py` - `_load_state()` / `_save_state()` methods
- `src/jukebox/components/playerpodcast/state_manager.py` - `_load()` / `_save()` methods

**Benefits of the new approach:**
- Simple and explicit (3-4 lines of code)
- No magic dict inheritance
- Reliable nested dict handling
- Easy to debug and maintain
- Standard Python practice

---

## Original Bug Report

## Summary
NvManager's hash-based save mechanism (`nv_dict.save_to_json()`) fails to detect changes to nested dictionaries, causing state modifications to not be written to disk.

## Location
`src/jukebox/jukebox/NvManager.py` - class `nv_dict`

## Root Cause
The `save_to_json()` method only saves if the dict's hash has changed:

```python
def save_to_json(self, filename=None):
    actual_hash = self.hash()
    if self.initial_hash != actual_hash:  # Only saves if hash changed
        # ... write to file
```

When modifying nested dictionaries (e.g., `state['episodes'][guid] = {...}`), the modification happens in-place on a nested dict object. While this DOES trigger `__setitem__` at the 'episodes' level, the hash calculation may not properly detect the change.

## Reproduction
```python
nvm = nv_manager()
state = nvm.load('test.json')

# Initialize nested structure
state['episodes'] = {}
state['episodes']['ep1'] = {'position': 0}
nvm.save_all()  # This works - top level modified

# Modify nested dict
state['episodes']['ep1']['position'] = 42
nvm.save_all()  # This FAILS - hash doesn't change
```

## Evidence
In podcast player testing:
- In-memory state dict showed 45 episodes with position data
- Manual JSON write succeeded with full data
- NvManager's save_all() completed without errors
- Actual file on disk remained empty `{}`

## Impact
- Podcast episode positions not persisting across restarts
- Any component using nested dicts with NvManager will have save issues
- Silent failure - no errors logged, appears to work

## Current Workaround
Direct JSON write in affected components:

```python
def _save(self):
    """Bypass NvManager - write directly to JSON"""
    with open(self.status_file, 'w') as f:
        json.dump(dict(self.state), f, indent=2)
```

## Proper Fix Options

### Option 1: Force dirty flag on nested modifications
Modify `nv_dict.__setitem__` to recursively mark parent as dirty when nested dicts change.

### Option 2: Deep hash calculation
Change hash calculation to properly detect nested changes (may be expensive).

### Option 3: Always save if dirty flag set
Add explicit dirty tracking instead of relying solely on hash comparison.

### Option 4: Deprecate hash-based saving
Remove hash check and always write when `save_all()` is called (simpler but more I/O).

## Recommendation
**Option 3** - Add explicit dirty flag that gets set on ANY modification (including nested). This is most reliable and performant.

## Test Case Needed
```python
def test_nested_dict_persistence():
    nvm = nv_manager()
    state = nvm.load('test.json')

    # Nested modification
    state['level1'] = {}
    state['level1']['level2'] = {}
    state['level1']['level2']['value'] = 'initial'
    nvm.save_all()

    # Modify deeply nested value
    state['level1']['level2']['value'] = 'modified'
    nvm.save_all()

    # Reload and verify
    state2 = nvm.load('test.json')
    assert state2['level1']['level2']['value'] == 'modified'
```

## Files Using NvManager
Check these components for similar issues:
- `src/jukebox/components/playerpodcast/state_manager.py` (workaround applied)
- `src/jukebox/components/playermpd/` (check if affected)
- Any other components loading nested state with NvManager
