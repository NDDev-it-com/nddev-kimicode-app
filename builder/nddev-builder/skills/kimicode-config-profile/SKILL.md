---
name: kimicode-config-profile
description: Create or review nddev-kimicode-app content setup and profile rendering for documented Kimi config.toml and tui.toml fields.
type: prompt
whenToUse: When changing Kimi setup catalogs, profile descriptors, config.toml rendering, tui.toml rendering, or managed stamps
disableModelInvocation: false
---

# Kimi Config And Profile

Use only documented Kimi config locations and fields.

Managed target paths:

- `$KIMI_CODE_HOME/config.toml`
- `$KIMI_CODE_HOME/tui.toml`
- `$KIMI_CODE_HOME/NDDEV-KIMICODE-SETUP.json`

Public source owners:

- `setups/nddev-builder/setup.json` owns the content setup identity.
- `profiles/safe/profile.json` owns NDDev safe mode.
- `profiles/full-auto/profile.json` owns NDDev full-auto mode.
- `cli-tools/nddev_kimicode.py` owns render logic and stamp schema.
- `config/nddev-contract.json` owns the public contract description.

Rendering rules:

- Top-level `default_permission_mode`, `default_plan_mode`, `extra_skill_dirs`, and `extra_agent_dirs` belong in `config.toml`.
- `[loop_control].max_steps_per_turn` belongs in `config.toml`.
- `[background].max_running_tasks` belongs in `config.toml`.
- `[[permission.rules]]` belongs in `config.toml`.
- `[[hooks]]` belongs in `config.toml` only for profiles that intentionally activate hooks; it only uses `event`, `matcher`, `command`, and `timeout`.
- `[upgrade].auto_install = false` belongs in `tui.toml`.
- MCP servers belong in `mcp.json`, not `config.toml`.
- Do not add `[plugins]`, `[permissions] allow/deny`, or `mcp_config_file`.

The default profile is `full-auto`. Preserve `safe` as the official manual mode.
Do not ship `balanced` or `yolo`. Do not activate a blocking hook in `full-auto`.
