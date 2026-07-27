---
name: nddev-builder
description: Route Kimi Code setup artifact work to the focused NDDev builder skills for native config, profiles, permissions, agents, skills, plugins, hooks, MCP, installation, and release validation.
type: prompt
whenToUse: When creating, switching, validating, or reviewing Kimi Code CLI setup artifacts
disableModelInvocation: false
---

# NDDev Builder

Use this entry skill as the router for `nddev-kimicode-app` setup artifact work.
Load the focused skill for the surface you are changing before editing.

- Configuration and profile rendering: use `kimicode-config-profile`.
- Permission and sandbox posture: use `kimicode-permissions-sandbox`.
- AGENTS.md, Agent Skills, and custom agents/subagents: use `kimicode-instructions-agents-skills`.
- Plugin source and native marketplace boundaries: use `kimicode-plugins-marketplace`.
- Hooks: use `kimicode-hooks`.
- MCP: use `kimicode-mcp`.
- Official binary installation, update, rollback, and legacy migration: use `kimicode-install-lifecycle`.
- Creator/checker/release validation workflow: use `kimicode-create-check-release`.

Reference files in this skill directory:

- `references/native-surfaces.md` records the native Kimi paths and schema owners.
- `references/public-validation.md` records public-only validation commands.

Do not copy version pins, release checksums, or current module SHAs into prompts or
docs. Those facts are owned by `references/kimi-code-baseline.json`,
`build/manifest.json`, `build/version.json`, `config/nddev-contract.json`, and
`cli-tools/nddev_kimicode.py`.
