# nddev-kimicode-app

Public setup manager for Moonshot AI Kimi Code CLI.

The manager requires an explicit absolute target and never defaults to the
user's live `~/.kimi-code`. It writes target-bound setup files, stamps ownership,
keeps rotating backups, installs a target-owned official Kimi binary, and
launches `bin/kimi` with isolated `HOME`, `TMPDIR`, and `KIMI_CODE_HOME`.
Launch runs in the caller's current project directory by default, or in an
explicit absolute project directory passed with manager `--workspace`.

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
python3 cli-tools/nddev_kimicode.py launch --target /absolute/target [--workspace /absolute/project] --
```

## Runtime Baseline

The current Kimi release, official binary manifest, platform checksums, npm
metadata, and source URLs are owned by `references/kimi-code-baseline.json`.
The public contract is owned by `config/nddev-contract.json`, and command
behavior is owned by `cli-tools/nddev_kimicode.py`.

`software-status` is structural and does not execute `kimi`. `install-cli`,
`update-cli`, and `migrate-cli` are the only commands that acquire target-owned
Kimi software.

`launch` holds the managed lifecycle boundary until the child process exits, so
setup, profile, software, restore, and remove mutations fail while the managed
CLI is running. The manager revalidates the target-owned Kimi executable before
handoff, passes an explicit child working directory, and preserves writable
target and runtime state for the launched CLI.
Exact lock ordering, path protection, executable checks, and portable handoff
mechanics are owned by `cli-tools/nddev_kimicode.py` and summarized by
`config/nddev-contract.json`; official binary provenance is owned by
`references/kimi-code-baseline.json`. This is cooperative lifecycle isolation,
not an OS sandbox against deliberate same-UID tampering outside the manager.

## Builder Toolkit

The `nddev-builder` content setup projects the full public builder toolkit under
`builder/nddev-builder/skills/` into `$KIMI_CODE_HOME/skills/`, plus the custom
agent, MCP JSON, AGENTS.md block, and hook source file. Plugin source packaging
is provided at `builder/nddev-builder/kimi.plugin.json`, but the manager never
writes Kimi runtime-owned `plugins/installed.json`.
