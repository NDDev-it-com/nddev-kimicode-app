# Kimi Native Surfaces

This reference names the source-of-truth owners for Kimi Code surfaces used by
`nddev-kimicode-app`. Volatile release pins, checksums, managed paths, and
generated target files are owned by machine-readable sources.

## Target Root

The manager launches Kimi with `KIMI_CODE_HOME` set to the explicit target. The
exact managed path set is owned by
`cli-tools/nddev_kimicode.py:content_managed_paths`, and the public contract
summary is owned by `config/nddev-contract.json`.

## Runtime-Owned Paths

Use Kimi's native UI or slash commands for runtime-owned plugin and auth state.
The NDDev manager only writes the documented setup projection owned by the
manager and contract.

## CLI Parser Owner

The official Kimi CLI parser owner is recorded in
`references/kimi-code-baseline.json`. Use that source path before changing
managed launch-boundary constants or regressions. This reference intentionally
does not copy the parser's full option or command list.
