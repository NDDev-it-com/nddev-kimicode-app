---
name: kimicode-install-lifecycle
description: Create or review official Kimi binary installation, update, rollback, legacy Bun migration, and launch isolation in nddev-kimicode-app.
type: prompt
whenToUse: When changing install-cli, update-cli, migrate-cli, software-status, launch, binary provenance, rollback, or legacy software handling
disableModelInvocation: false
---

# Kimi Install Lifecycle

The manager owns a target-owned implementation of Kimi's official binary
install channel for the supported product hosts in `config/nddev-contract.json`.
Do not pipe the official shell installer into live user state.

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
- Rollback restores prior target-owned software state on failure.
- Ubuntu desktop and server share the same `ID=ubuntu` glibc host check, and the upstream baseline records no official Ubuntu/glibc version floor.

Do not copy the unsupported-category or platform-asset table into this Skill;
those values belong in `config/nddev-contract.json` and
`references/kimi-code-baseline.json`.
