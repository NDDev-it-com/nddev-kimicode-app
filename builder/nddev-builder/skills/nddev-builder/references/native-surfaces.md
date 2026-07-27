# Kimi Native Surfaces

This reference names stable Kimi Code paths and schema owners used by
`nddev-kimicode-app`. Volatile release pins and checksums are owned by
`references/kimi-code-baseline.json` and the manager.

## Target Root

The manager launches Kimi with `KIMI_CODE_HOME` set to the explicit target.
Kimi-specific user state lives under that root:

- `config.toml`: runtime config, permission mode, loop control, background limits, hooks, extra skill and agent dirs.
- `tui.toml`: TUI preferences, including `[upgrade].auto_install`.
- `AGENTS.md`: global Kimi-specific instructions.
- `mcp.json`: user-level MCP declarations.
- `skills/`: Kimi-specific user Agent Skills.
- `agents/`: Kimi-specific custom agents and subagents.
- `hooks/`: regular-file hook adapters available to profiles that explicitly activate `[[hooks]]`.
- `credentials/`, `sessions/`, `logs/`, `updates/`, `user-history/`: runtime-owned Kimi state.

## Runtime-Owned Paths

Do not write these directly:

- `plugins/installed.json`
- `plugins/managed/`
- `credentials/`
- `sessions/`
- `logs/`
- `updates/`
- `user-history/`

Use Kimi's native UI or slash commands for runtime-owned plugin and auth state.
The NDDev manager only writes the documented configuration and content projection.
