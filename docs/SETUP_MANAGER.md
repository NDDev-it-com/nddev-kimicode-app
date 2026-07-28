# Setup Manager

`nddev-kimicode-app` manages an explicit Kimi Code CLI data root.

## Managed Content

The manager writes NDDev-owned setup content into the explicit target. The exact
managed path set is owned by `cli-tools/nddev_kimicode.py:content_managed_paths`.
Managed TOML and Markdown content is written inside NDDev marker blocks so local
state outside those blocks survives install, profile switches, migration,
restore, and remove.

Runtime plugin install state remains Kimi-owned and is not written directly by
the manager.

## Profiles

`full-auto` is the default profile and maps to native Kimi `auto` mode. It does
not activate a blocking hook and does not add permission rules.

`safe` maps to native Kimi `manual` mode, enables plan mode, renders documented
permission rules, and may activate the supervised PreToolUse hook.

Native `yolo` is not shipped as an NDDev profile.

## Target-Owned Software

`software-status` is read-only: it checks the software stamp, target-owned
binary presence, entrypoint digest, and installed tree digest without executing
`kimi`.

`install-cli` installs a verified official Kimi binary into target-owned state
on supported macOS and Ubuntu hosts. `update-cli` repairs or updates current
official-binary state. `migrate-cli` is the only transition from legacy Bun
schema to official-binary schema.

Legacy Bun state may be read for status, migrated, restored, or removed. It must
never launch.

Release versions, URLs, manifest hashes, upstream platform assets, product host
mapping, and the no-official-floor Ubuntu/glibc observation are owned by
`references/kimi-code-baseline.json` and `config/nddev-contract.json`.

## Launch Isolation

`launch` refuses unsupported hosts, unmanaged, legacy, drifted, or
missing-current-software targets. It executes `/absolute/target/bin/kimi` with
target-local `HOME`, `TMPDIR`, and `KIMI_CODE_HOME`, disables telemetry, stops
background keep-alive on exit, and constructs a fresh child environment without
live provider credentials or `KIMI_MODEL_*` variables.

The lifecycle boundary is held from launch preflight through child process
completion and cleanup. While it is held, install, update, migrate, restore,
remove, and profile-switch mutations fail, including ordinary attempts by the
child process to bypass the managed lifecycle boundary. Before subprocess
handoff, the manager revalidates the target-owned executable and preserves
writable managed target and runtime state for the launched CLI.

Exact lock ordering, path protection, executable checks, runtime directory
checks, and portable handoff mechanics are owned by
`cli-tools/nddev_kimicode.py` and summarized by `config/nddev-contract.json`.
Official binary provenance is owned by `references/kimi-code-baseline.json`.
The launch boundary is cooperative lifecycle isolation, not an OS sandbox
against deliberate same-UID tampering outside the manager.

Child arguments that override managed permission mode, plan mode, prompt mode,
model selection, Skill directories, agents, sessions, extra workspace scope, or
software migration/update behavior are rejected before the target-owned binary
is spawned.

Unsupported host categories and exact product host IDs are owned by
`config/nddev-contract.json`. Ubuntu desktop and server share the same
`ID=ubuntu` glibc check.
