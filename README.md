# nddev-kimicode-app

Public setup manager for current Moonshot AI Kimi Code CLI.

The manager requires an explicit absolute target and never defaults to the user's live
`~/.kimi-code`. It writes target-bound setup files, stamps ownership, keeps rotating
backups, installs the pinned Kimi Code package into the target, and launches the
target-owned `bin/kimi` with an isolated `KIMI_CODE_HOME`.

## Commands

```bash
python3 cli-tools/nddev_kimicode.py list --json
python3 cli-tools/nddev_kimicode.py plan --setup safe --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py install --setup safe --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py switch --setup balanced --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py status --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py restore --backup 0 --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py remove --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py software-status --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py install-cli --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py update-cli --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py launch --target /absolute/target -- --version
```

## Runtime Baseline

The public contract targets only Kimi Code CLI package
`@moonshot-ai/kimi-code@0.29.1` and command `kimi`.

Package hashes, the official `postinstall`, and the target-owned Bun install contract
are recorded in `references/kimi-code-baseline.json`. The manager uses
`bun add --global --exact --trust @moonshot-ai/kimi-code@0.29.1` with stage-local
`BUN_INSTALL_GLOBAL_DIR`, `BUN_INSTALL_BIN`, `BUN_INSTALL_CACHE_DIR`, `HOME`,
`XDG_CONFIG_HOME`, and `TMPDIR`.
