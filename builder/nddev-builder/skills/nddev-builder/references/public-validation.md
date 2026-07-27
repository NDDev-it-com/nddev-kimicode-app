# Public Validation

Run public-only checks from the `nddev-kimicode-app` repository root. Do not run
private harness lanes from this public toolkit.

```bash
python3 -m py_compile cli-tools/nddev_kimicode.py cli-tools/validate_public_contracts.py builder/nddev-builder/hooks/nddev-builder-pretooluse.py
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_kimicode.py list --json
```

For non-live lifecycle checks, use an isolated temporary target and do not run
`install-cli`, `update-cli`, `migrate-cli`, or `launch` unless the caller has
explicitly requested real Kimi software execution.

```bash
tmp=".tmp-kimicode-public-check"
cleanup() {
  if [ -e "$tmp" ]; then
    find "$tmp" -depth \( -type f -o -type l \) -delete
    find "$tmp" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT
cleanup
mkdir -p "$tmp/parent"
chmod 700 "$tmp/parent"
target="$PWD/$tmp/parent/kimi"
python3 cli-tools/nddev_kimicode.py plan --target "$target" --json
python3 cli-tools/nddev_kimicode.py install --target "$target" --json
python3 cli-tools/nddev_kimicode.py status --target "$target" --json
python3 cli-tools/nddev_kimicode.py switch-profile --profile safe --target "$target" --json
python3 cli-tools/nddev_kimicode.py remove --target "$target" --json
```
