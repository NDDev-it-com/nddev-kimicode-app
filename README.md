# nddev-kimicode-app

Public setup manager for current Moonshot AI Kimi Code CLI.

The manager requires an explicit absolute target and never defaults to the user's live
`~/.kimi-code`. It writes target-bound setup files, stamps ownership, keeps rotating
backups, and launches `kimi` with an isolated `KIMI_CODE_HOME`.

## Commands

```bash
python3 cli-tools/nddev_kimicode.py list --json
python3 cli-tools/nddev_kimicode.py plan --setup safe --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py install --setup safe --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py switch --setup balanced --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py status --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py restore --backup 0 --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py remove --target /absolute/target --json
python3 cli-tools/nddev_kimicode.py launch --target /absolute/target -- --version
```

## Runtime Baseline

The public contract targets only Kimi Code CLI package
`@moonshot-ai/kimi-code@0.29.1` and command `kimi`.

Package hashes and official sources are recorded in `references/kimi-code-baseline.json`.
