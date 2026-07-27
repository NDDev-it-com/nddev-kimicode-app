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

The module does not ship `balanced`, `yolo`, or Windows support.

## Commands

```bash
python3 cli-tools/nddev_kimicode.py list --json
python3 cli-tools/nddev_kimicode.py plan --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py install --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py switch-profile --profile safe --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py migrate --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py status --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py restore --backup 0 --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py remove --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py software-status --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py install-cli --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py update-cli --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py migrate-cli --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py launch --target /absolute/target --
```

## Runtime Baseline

The current Kimi release, official binary manifest, platform checksums, npm
metadata, and source URLs are owned by `references/kimi-code-baseline.json`.
The public contract is owned by `config/nddev-contract.json`, and command
behavior is owned by `cli-tools/nddev_kimicode.py`.

`software-status` is structural and does not execute `kimi`. `install-cli`,
`update-cli`, and `migrate-cli` are the only commands that acquire target-owned
Kimi software.

`launch` holds a target-local `fcntl.flock` lifecycle lock until the child
process exits. Immediately before spawning, it temporarily makes only the
dedicated lock directory, launcher `bin/` directory, and immutable software
artifact directories read/execute-only, reopens `bin/kimi` without following
symlinks, checks regular-file status, current-user ownership, private executable
mode, stable inode, and pinned official-binary digest, then launches the
verified path while the protection and lock are still held. The managed target,
runtime `HOME`, `TMPDIR`, KIMI_CODE_HOME, config, session, plugin, MCP, and log
locations remain writable by the launched CLI. This is a portable
write-protected verified-path handoff, not exact-inode fd execution. Deliberate
same-UID `chmod` or tampering outside the manager is outside the enforceable
isolation boundary.

## Builder Toolkit

The `nddev-builder` content setup projects the full public builder toolkit under
`builder/nddev-builder/skills/` into `$KIMI_CODE_HOME/skills/`, plus the custom
agent, MCP JSON, AGENTS.md block, and hook source file. Plugin source packaging
is provided at `builder/nddev-builder/kimi.plugin.json`, but the manager never
writes Kimi runtime-owned `plugins/installed.json`.
