# Setup Manager

`nddev-kimicode-app` manages an explicit Kimi Code CLI data root.

## Managed Content

The manager writes NDDev-owned content to these target paths:

- `config.toml`
- `tui.toml`
- `AGENTS.md`
- `mcp.json`
- `skills/`
- `agents/nddev-builder.md`
- `hooks/nddev-builder-pretooluse.py`
- `NDDEV-KIMICODE-SETUP.json`

Managed TOML and Markdown content is written inside NDDev marker blocks so local
state outside those blocks survives install, profile switches, migration,
restore, and remove.

The manager does not write runtime-owned plugin install state:

- `plugins/installed.json`
- `plugins/managed/`

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

`install-cli` installs a verified official Kimi binary into target-owned state.
`update-cli` repairs or updates current official-binary state. `migrate-cli` is
the only transition from legacy Bun schema to official-binary schema.

Legacy Bun state may be read for status, migrated, restored, or removed. It must
never launch.

Release versions, URLs, manifest hashes, and platform binary digests are owned
by `references/kimi-code-baseline.json`.

## Launch Isolation

`launch` refuses unmanaged, legacy, drifted, or missing-current-software targets.
It executes `/absolute/target/bin/kimi` with target-local `HOME`, `TMPDIR`, and
`KIMI_CODE_HOME`, disables telemetry, stops background keep-alive on exit, and
constructs a fresh child environment without live provider credentials or
`KIMI_MODEL_*` variables.

The target lifecycle lock is a target-local regular file held with
`fcntl.flock` on an open fd from launch preflight through child process
completion and lock cleanup, so install, update, migrate, restore, remove, or
profile-switch mutations fail while the child is running. Immediately before the
subprocess handoff, the manager makes the executable and software parent chain
read/execute-only, reopens the target-owned executable without following
symlinks, and checks regular file type, current-user ownership, mode, stable
inode, and the pinned official-binary digest. Runtime `HOME` and `TMPDIR`
directories are rechecked as real private directories before handoff.

The portable launch contract is a write-protected verified-path handoff. It does
not claim exact-inode fd execution on macOS, and it is not an OS sandbox against
deliberate same-UID `chmod` or tampering outside the manager. Ordinary unlink,
rename, and `os.replace` swaps are denied while the protected launch path is
held.

Child arguments that override managed permission mode, plan mode, prompt mode,
model selection, Skill directories, agents, sessions, extra workspace scope, or
software migration/update behavior are rejected before the target-owned binary
is spawned.
