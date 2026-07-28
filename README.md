# nddev-kimicode-app

Public setup manager for Moonshot AI Kimi Code CLI.

The manager requires an explicit absolute target and never defaults to the
user's live `~/.kimi-code`. It writes target-bound setup files, stamps ownership,
keeps rotating backups, installs a target-owned official Kimi binary, and
launches `bin/kimi` with isolated `HOME`, `TMPDIR`, and `KIMI_CODE_HOME`.

## Model

`nddev-kimicode-app` separates content setup from permission profile:

- Content setup: `nddev-builder`.
- Default permission profile: `full-auto`, mapped to documented native Kimi
  `auto` mode.
- Safe permission profile: `safe`, mapped to documented native Kimi `manual`
  mode.

The module does not ship `balanced` or `yolo`. Production host support is
macOS plus Ubuntu desktop/server on the supported architectures. Exact product
host IDs, unsupported categories, and vendor asset mapping are owned by
`config/nddev-contract.json`.

## Commands

`cli-tools/nddev_kimicode.py` owns the command parser and JSON payloads. Use
`--help` from the repository root when you need the current command surface.

## Runtime Baseline

The current Kimi release, official binary manifest, upstream platform assets,
npm metadata, and source URLs are owned by
`references/kimi-code-baseline.json`. Supported product hosts and their mapping
to upstream asset keys are owned by `config/nddev-contract.json`; command
behavior is owned by `cli-tools/nddev_kimicode.py`.

`software-status` is structural and does not execute `kimi`. `install-cli`,
`update-cli`, `migrate-cli`, and `remove-cli` own the target-owned Kimi software
lifecycle. `remove-cli` is a deterministic no-op when target-owned software
presence is absent. Ubuntu desktop and server share the same `ID=ubuntu` glibc
host check; upstream publishes no official Ubuntu/glibc version floor.

`launch` holds the managed lifecycle boundary until the child process exits, so
setup, profile, software, restore, and remove mutations fail while the managed
CLI is running. The manager revalidates the target-owned Kimi executable before
handoff while preserving writable target and runtime state for the launched CLI.
Exact lock ordering, path protection, executable checks, and portable handoff
mechanics are owned by `cli-tools/nddev_kimicode.py` and summarized by
`config/nddev-contract.json`; official binary provenance is owned by
`references/kimi-code-baseline.json`. This is cooperative lifecycle isolation,
not an OS sandbox against deliberate same-UID tampering outside the manager.

## Builder Toolkit

The `nddev-builder` content setup projects the public builder toolkit into the
explicit target. The exact managed path set is owned by
`cli-tools/nddev_kimicode.py:content_managed_paths`; plugin source packaging is
provided for native Kimi workflows, but runtime plugin install state remains
Kimi-owned.
