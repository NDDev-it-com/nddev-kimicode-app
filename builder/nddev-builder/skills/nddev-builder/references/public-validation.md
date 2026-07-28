# Public Validation

Run public-only checks from the `nddev-kimicode-app` repository root. The exact
cache-free public command set is owned by
`cli-tools/validate_public_contracts.py`; do not copy it into this reference.
Do not run private harness lanes from this public toolkit.

For non-live lifecycle checks, use an isolated temporary target and do not run
`install-cli`, `update-cli`, `migrate-cli`, or `launch` unless the caller has
explicitly requested real Kimi software execution.
