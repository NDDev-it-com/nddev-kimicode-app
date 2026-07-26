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

## Target-Owned Software

`software-status` is read-only: it checks the software stamp, exact package manifest,
entrypoint digest, and persisted install tree digest without executing `kimi`. It also
reports `present` and `presence` for any target-owned software artifact:
`NDDEV-KIMICODE-SOFTWARE.json`, `.nddev-kimicode-software`,
`.nddev-kimicode-software/current`, or `bin/kimi`.

`install-cli` and `update-cli` install the exact package
`@moonshot-ai/kimi-code@0.29.1` through Bun using:

```bash
bun add --global --exact --trust @moonshot-ai/kimi-code@0.29.1
```

The Bun subprocess receives only stage-local `BUN_INSTALL_GLOBAL_DIR`,
`BUN_INSTALL_BIN`, `BUN_INSTALL_CACHE_DIR`, `HOME`, `XDG_CONFIG_HOME`, `TMPDIR`, and
`PATH`. Provider credentials, package-manager auth tokens, and user config paths are
not inherited. The manager persists only `install/global` and `bin` from the stage,
materializes safe internal symlinks as private regular files, rejects escaping
symlinks, resolves `node >=22.19.0`, probes a staged `bin/kimi --version` wrapper,
and atomically swaps the target tree with rollback.

The final target `bin/kimi` is a generated private wrapper. It invokes the persisted
`dist/main.mjs` with the absolute Node path and Node version recorded at install or
update time, so launch does not depend on finding `node` through `PATH`.
The software receipt also records the official npm integrity, shasum, unpacked size,
and file count for the pinned `@moonshot-ai/kimi-code` package.

`install-cli` is only for fresh targets or already-current idempotency. If any partial
target-owned software artifact is present, it fails closed and directs repair through
`update-cli`. `update-cli` requires existing target-owned software presence and repairs
partial or stale software state transactionally.

## Launch Isolation

`launch` refuses unmanaged, drifted, or missing-current-software targets. It executes
`/absolute/target/bin/kimi` with `PATH=/usr/bin:/bin`, sets `KIMI_CODE_HOME` to the
target, sets a target-local `HOME`, disables telemetry, auto-update preflight, and
cron tools, and constructs a fresh child environment without provider credentials.
Child arguments that override managed model, permission, prompt/autopilot, Skill,
agent, update, or extra workspace scope are rejected before the target-owned binary is
spawned.
