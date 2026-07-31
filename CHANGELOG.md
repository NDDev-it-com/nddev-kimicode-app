# Changelog

## Unreleased

### Changed

- Advance the public build and native nddev-builder projection to `0.3.1`.
- Pin the official Kimi Code runtime, raw binary manifest, URLs, sizes, and
  SHA-256 digests to `0.31.1`.
- Public runtime metadata now contains only the official manifest and supported
  macOS/Ubuntu binary pins consumed by the setup manager.
- Non-runtime vendor distribution observations are no longer part of public
  manager stamps, baselines, manifests, or contracts.

## 0.3.0 - 2026-07-30

### Changed

- Advance all public release and nddev-builder projection version owners to
  0.3.0 without changing the established metadata schemas.

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
