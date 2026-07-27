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

Target isolation is separate from permission posture:

- `HOME` points to `$KIMI_CODE_HOME/.nddev-kimicode-runtime/home`.
- `KIMI_CODE_HOME` points to the explicit target.
- `TMPDIR` points to target-owned runtime temp state.
- `KIMI_DISABLE_TELEMETRY=1` is set.
- `KIMI_CODE_BACKGROUND_KEEP_ALIVE_ON_EXIT=0` is set.
- Live provider credentials and `KIMI_MODEL_*` variables are not inherited.

Never treat hooks as the only security boundary. Kimi hooks are fail-open by
design; manager-side target checks, launch override blocking, locks, backups,
rollback, and secret-filtered environments are the hard boundary.
