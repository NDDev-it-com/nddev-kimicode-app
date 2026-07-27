---
name: kimicode-instructions-agents-skills
description: Create or review Kimi AGENTS.md instructions, Agent Skills, and custom agent/subagent files in the NDDev builder projection.
type: prompt
whenToUse: When changing AGENTS.md, skills, custom agents, subagents, routing, or prompt-tool boundaries
disableModelInvocation: false
---

# Kimi Instructions, Agents, And Skills

Managed target paths:

- `$KIMI_CODE_HOME/AGENTS.md`
- `$KIMI_CODE_HOME/skills/`
- `$KIMI_CODE_HOME/agents/`

Skill rules:

- Prefer directory-form Skills: `<skill-name>/SKILL.md`.
- Directory-form `SKILL.md` must include `name` and `description`.
- Use `type: prompt` for reusable prompt workflows.
- Use `whenToUse` for routing.
- Use `disableModelInvocation` only when the workflow must be manual.
- Put reference files under the same Skill directory and route to them explicitly.

Agent rules:

- Custom agents are Markdown files under `$KIMI_CODE_HOME/agents/`.
- Use frontmatter with `name`, `description`, `whenToUse`, `override`, and `disallowedTools`.
- Omit `tools` when the agent should inherit the full native tool surface.
- Do not set `override: true` unless replacing a built-in agent is intentional and documented.
- Keep credential, session, log, and runtime-state access out of agent prompts.

AGENTS.md rules:

- Keep it hierarchical and low-entropy.
- Point to code-owned facts instead of copying version pins or checksum lists.
- State that `plugins/installed.json` is runtime-owned and must not be written directly.
