---
name: kimicode-hooks
description: Create or review documented Kimi hook rules and regular-file hook adapters for nddev-kimicode-app.
type: prompt
whenToUse: When changing hook adapters, [[hooks]] config, plugin hook declarations, or hook safety claims
disableModelInvocation: false
---

# Kimi Hooks

Config owner:

- `cli-tools/nddev_kimicode.py` owns hook path selection and rendered config.
- The default `full-auto` profile does not activate blocking hooks.
- The `safe` profile may activate a `PreToolUse` hook as a supervised-mode guard.

Do not add extra fields to `[[hooks]]`; Kimi fails config loading on unsupported
hook fields. Audit the manager renderer before changing hook schema assumptions.

Adapter rules:

- Keep adapters deterministic regular files.
- Read JSON from stdin.
- Exit `0` to allow.
- Exit `2` to block with a message.
- Do not write logs, caches, credentials, sessions, or plugin install records.
- Do not depend on Node for the default public projection; the official binary install does not require Node.

Hooks are fail-open and are not the sole security boundary. Keep hard safety in
the manager's filesystem, lock, rollback, launch, and environment controls.
