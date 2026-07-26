---
name: nddev-builder
description: Build and review Kimi Code CLI setup artifacts inside an isolated NDDev target.
type: prompt
whenToUse: When creating, switching, validating, or reviewing Kimi Code CLI setup artifacts
disableModelInvocation: false
---

# NDDev Builder

Use this skill for Kimi Code CLI setup artifact work managed by
`nddev-kimicode-app`.

Operate only through confirmed Kimi Code CLI surfaces: `$KIMI_CODE_HOME/AGENTS.md`,
`$KIMI_CODE_HOME/skills/`, `$KIMI_CODE_HOME/agents/`, `$KIMI_CODE_HOME/mcp.json`,
`[[hooks]]` in `config.toml`, and native plugin manifests. Treat direct plugin
install-state writes and external marketplace publication as unavailable until the
public contract records a confirmed manifest.

Keep credentials, OAuth state, sessions, logs, and live user configuration outside the
managed target. Prefer explicit absolute paths, bounded reads, reversible writes, and
target-bound backups.
