---
name: kimicode-plugins-marketplace
description: Create or review Kimi plugin source manifests and marketplace boundaries without writing runtime-owned plugin install state.
type: prompt
whenToUse: When changing kimi.plugin.json, plugin source layout, marketplace documentation, plugin hooks, plugin MCP, or plugin enablement claims
disableModelInvocation: false
---

# Kimi Plugins And Marketplace

Kimi supports native plugins, marketplace catalogs, and slash commands. NDDev
ships plugin source, but does not emulate runtime installation.

Public source path:

- `builder/nddev-builder/kimi.plugin.json`

Supported manifest fields used by NDDev:

- `name`
- `version`
- `description`
- `interface`
- `skills`
- `sessionStart`
- `skillInstructions`
- `mcpServers`

Native plugin hook fields are not declared in the current NDDev source manifest.
Profile-specific hook activation is rendered only by `cli-tools/nddev_kimicode.py`
into `$KIMI_CODE_HOME/config.toml`.

Boundaries:

- Do not write `$KIMI_CODE_HOME/plugins/installed.json`.
- Do not write `$KIMI_CODE_HOME/plugins/managed/`.
- Do not claim a plugin is enabled unless Kimi's native `/plugins` flow performed it.
- Local plugin installs are copied by Kimi into its managed plugin directory and require `/reload` or a new session.
- Marketplace source may be documented only when a real catalog is published or explicitly configured.

The default NDDev builder activation uses ordinary Kimi-native files: AGENTS.md,
Skills, custom agents, MCP JSON, and projected hook source files. The default
`full-auto` profile does not activate a blocking policy hook. Plugin source
packaging is provided for users or future native plugin installation, not as a
direct install-state write.
