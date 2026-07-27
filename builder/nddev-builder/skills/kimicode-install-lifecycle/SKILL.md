---
name: kimicode-install-lifecycle
description: Create or review official Kimi binary installation, update, rollback, legacy Bun migration, and launch isolation in nddev-kimicode-app.
type: prompt
whenToUse: When changing install-cli, update-cli, migrate-cli, software-status, launch, binary provenance, rollback, or legacy software handling
disableModelInvocation: false
---

# Kimi Install Lifecycle

The manager owns a target-owned implementation of Kimi's official macOS/Linux
binary install channel. Do not pipe the official shell installer into live user
state.

Source owners:

- `cli-tools/nddev_kimicode.py` owns lifecycle behavior.
- `references/kimi-code-baseline.json` owns release provenance and checksums.
- `build/manifest.json` and `config/nddev-contract.json` describe the public contract.

Lifecycle rules:

- `install-cli` installs only when no target-owned software presence exists.
- `update-cli` repairs or updates current schema-2 official-binary state.
- `migrate-cli` is the only path from legacy Bun schema to official-binary schema.
- `software-status` is structural and must not execute `kimi`.
- `launch` requires current setup schema and current official-binary software schema.
- Legacy Bun state may be read for status, migrated, restored, or removed; it must never launch.
- Rollback restores prior binary tree, entrypoint, and stamp on failure.
- Official binary state is target-owned under `.nddev-kimicode-software/current` plus `bin/kimi`.

Do not add Windows support. NDDev supports macOS and Ubuntu/Linux glibc only.
