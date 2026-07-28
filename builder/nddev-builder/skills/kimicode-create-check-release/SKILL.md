---
name: kimicode-create-check-release
description: Create, check, and prepare public nddev-kimicode-app release artifacts without private harness files.
type: prompt
whenToUse: When changing public contracts, release metadata, docs, builder toolkit files, or public validation
disableModelInvocation: false
---

# Kimi Create, Check, And Release

Work only inside the public module. `cli-tools/validate_public_contracts.py`
owns the allowed public surface, validation contract, and cache-free command
regression.

Do not add private harness files, private tests, private benchmark outputs,
durable memories, generated evidence, live credentials, caches, logs, or root
registry changes to this public module.

Use isolated temporary targets for non-live manager checks. Do not run live
official binary installation from this skill unless the caller explicitly asks
for a real vendor smoke.

Versioning:

- The public module SemVer is owned by `VERSION` and mirrored in build metadata.
- The tested Kimi release is owned by `references/kimi-code-baseline.json`.
- The root/private registry pin is not a public-module change.
