# Changelog

## 0.2.0 - 2026-07-27

### Added

- Official Kimi Code binary lifecycle for the pinned public baseline.
- Orthogonal `nddev-builder` content setup and `safe`/`full-auto` permission profiles.
- Full public nddev-builder Agent Skills toolkit for Kimi-native setup surfaces.
- Legacy Bun software migration path that refuses legacy launch.

### Changed

- `full-auto` now maps to native Kimi `auto` mode and is the default profile.
- `safe` maps to native Kimi `manual` mode.
- Builder plugin files are source packaging only; the manager does not write
  Kimi runtime-owned plugin install state.

### Removed

- Removed shipped `balanced` setup.
- Removed Windows support from the NDDev public contract.
