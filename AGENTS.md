# nddev-kimicode-app

This public repository owns the Kimi Code setup manager, public contracts,
release metadata, documentation, and the public nddev-builder toolkit.

Private harness tests, benchmarks, root registry pins, durable memories, and
operational skills live outside this repository.

## Boundaries

- Keep public runtime implementation in `cli-tools/`.
- Keep public content setup sources in `setups/`, `profiles/`, and
  `builder/nddev-builder/`.
- Keep public contract facts in `config/`, `build/`, and `references/`.
- Do not add private QA, generated evidence, live credentials, logs, caches, or
  root registry changes.

## Kimi Facts

Do not copy volatile release pins or checksum lists into prose. Use these owners:

- `references/kimi-code-baseline.json`
- `build/manifest.json`
- `build/version.json`
- `config/nddev-contract.json`
- `cli-tools/nddev_kimicode.py`

## Public Checks

`cli-tools/validate_public_contracts.py` owns the public validation contract and
its cache-free command regression. Do not duplicate the current check list in
documentation.
