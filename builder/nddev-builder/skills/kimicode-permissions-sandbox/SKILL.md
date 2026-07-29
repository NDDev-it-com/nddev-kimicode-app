---
name: kimicode-permissions-sandbox
description: Design or review Kimi permission profiles, launch override blocking, and target-owned isolation for nddev-kimicode-app.
type: prompt
whenToUse: When changing safe/full-auto semantics, permission rules, launch flags, sandbox assumptions, or auth isolation
disableModelInvocation: false
---

# Kimi Permissions And Sandbox

NDDev profiles map to documented native Kimi permission modes:

- `safe` maps to native `manual` with plan mode enabled.
- `full-auto` maps to native `auto` with plan mode disabled, no permission rules,
  and no active blocking hook.
- Native `yolo` is not shipped; it may be considered later only as a supervised profile.

Launch must enforce the stamped profile and reject one-shot CLI overrides that
change permissions, model selection, session binding, skills dirs, agent
selection, prompt mode, workspace scope, or update/migration behavior.
The official Kimi parser owner is recorded in `references/kimi-code-baseline.json`;
audit that source before changing launch override constants or regressions.
Do not copy the parser's full option or command list into this Skill, and do not
deny flags that are not accepted by the audited upstream parser.

Target isolation is separate from permission posture. The launch environment,
credential filtering, runtime temp scope, and telemetry/keep-alive settings are
owned by `cli-tools/nddev_kimicode.py` and summarized in
`config/nddev-contract.json`; do not duplicate that environment list here.

Never treat hooks as the only security boundary. Kimi hooks are fail-open by
design; manager-side target checks, launch override blocking, locks, backups,
rollback, and secret-filtered environments are the hard boundary.
