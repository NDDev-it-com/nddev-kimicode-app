# Setup Manager

`nddev-kimicode-app` manages an explicit Kimi Code CLI data root.

## Managed Files

- `config.toml`
- `tui.toml`
- `AGENTS.md`
- `mcp.json`
- `skills/nddev-builder/SKILL.md`
- `agents/nddev-builder.md`
- `hooks/nddev-builder-pretooluse.mjs`
- `plugins/managed/nddev-builder/`
- `NDDEV-KIMICODE-SETUP.json`

Managed TOML and Markdown content is written inside NDDev marker blocks so local
state outside those blocks survives install, switch, restore, and remove. Third-party
skills, agents, MCP servers, credentials, sessions, logs, and OAuth state are not
removed.

## Launch Isolation

`launch` refuses unmanaged or drifted targets. It sets `KIMI_CODE_HOME` to the target,
sets a target-local `HOME`, disables telemetry, auto-update preflight, and cron tools,
and constructs a fresh child environment without provider credentials.
