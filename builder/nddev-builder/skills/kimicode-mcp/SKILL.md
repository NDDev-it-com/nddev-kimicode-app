---
name: kimicode-mcp
description: Create or review Kimi MCP declarations and boundaries for nddev-kimicode-app.
type: prompt
whenToUse: When changing mcp.json, plugin mcpServers, MCP server defaults, tool allowlists, or credential handling
disableModelInvocation: false
---

# Kimi MCP

Managed target path:

- `$KIMI_CODE_HOME/mcp.json`

Schema:

```json
{
  "mcpServers": {}
}
```

Kimi supports stdio, HTTP, and SSE MCP server declarations. NDDev ships no
default MCP servers because bundled servers would add process, credential, and
network boundaries that must be reviewed explicitly.

Rules:

- Put user-level MCP declarations in `mcp.json`, not `config.toml`.
- Keep default `mcpServers` empty unless the public contract adds a reviewed server.
- Do not embed secrets in `env`, `headers`, or static URLs.
- For HTTP/SSE bearer tokens, use Kimi's documented `bearerTokenEnvVar` only when the launch environment intentionally provides it.
- Plugin `mcpServers` may exist in source manifests, but only Kimi's native plugin enablement can activate them.
