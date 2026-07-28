---
name: kimicode-config-profile
description: Create or review nddev-kimicode-app content setup and profile rendering for documented Kimi config.toml and tui.toml fields.
type: prompt
whenToUse: When changing Kimi setup catalogs, profile descriptors, config.toml rendering, tui.toml rendering, or managed stamps
disableModelInvocation: false
---

# Kimi Config And Profile

Use only documented Kimi config locations and fields.

Public source owners:

- `setups/nddev-builder/setup.json` owns the content setup identity.
- `profiles/safe/profile.json` owns NDDev safe mode.
- `profiles/full-auto/profile.json` owns NDDev full-auto mode.
- `cli-tools/nddev_kimicode.py` owns render logic, managed path selection, and stamp schema.
- `config/nddev-contract.json` owns the public contract description.

Rendering rules:

- Keep setup and profile inputs declarative; do not duplicate rendered field
  lists in this Skill.
- Audit `cli-tools/nddev_kimicode.py` before changing rendered Kimi config or
  stamp behavior.
- Do not add undocumented Kimi config sections or plugin install-state writes
  without updating the public contract.

The default profile is `full-auto`. Preserve `safe` as the official manual mode.
Do not ship `balanced` or `yolo`. Do not activate a blocking hook in `full-auto`.
