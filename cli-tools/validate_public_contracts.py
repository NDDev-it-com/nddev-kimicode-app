#!/usr/bin/env python3
"""Validate public nddev-kimicode-app release contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHARED_CI_COMMIT = "2ccb80e96f5771b6a6b4eae63a4f47e232906dc7"
SHARED_CI_VERSION = "0.12.0"
REQUIRED_WORKFLOWS = {
    "actionlint.yml": ".github/workflows/actionlint.yml",
    "codeql.yml": ".github/workflows/public-codeql.yml",
    "dependency-review.yml": ".github/workflows/public-dependency-review.yml",
    "release.yml": ".github/workflows/release-supply-chain.yml",
    "scorecard.yml": ".github/workflows/public-scorecard-json.yml",
    "secret-scan.yml": ".github/workflows/secret-scan.yml",
    "zizmor.yml": ".github/workflows/zizmor-sarif.yml",
}
SETUP_ORDER = ["safe", "balanced", "full-auto"]
KIMI_PACKAGE = "@moonshot-ai/kimi-code"
KIMI_VERSION = "0.29.1"
KIMI_COMMAND = "kimi"
KIMI_BIN = "dist/main.mjs"
KIMI_POSTINSTALL = "node scripts/postinstall.mjs"
BUN_INSTALL_ARGV = ["add", "--global", "--exact", "--trust", f"{KIMI_PACKAGE}@{KIMI_VERSION}"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def setup_ids() -> list[str]:
    ids: list[str] = []
    for setup_id in SETUP_ORDER:
        setup_json = ROOT / "setups" / setup_id / "setup.json"
        setup = load_json(setup_json)
        ids.append(str(setup["id"]))
        if setup_json.parent.name != setup["id"]:
            raise ValueError(f"{setup_json}: directory name and id differ")
        if setup.get("nddev_builder_default") is not True:
            raise ValueError(f"{setup_json}: nddev-builder must be default-on")
    return ids


def validate_workflows() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    for filename, workflow in REQUIRED_WORKFLOWS.items():
        path = workflow_root / filename
        if not path.is_file():
            raise ValueError(f"missing workflow {path.relative_to(ROOT)}")
        expected = (
            f"uses: NDDev-it-com/ci-workflows/{workflow}@{SHARED_CI_COMMIT} # {SHARED_CI_VERSION}"
        )
        text = path.read_text(encoding="utf-8")
        if text.count(expected) != 1:
            raise ValueError(f"{filename}: missing exact shared CI caller")


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    build = load_json(ROOT / "build" / "version.json")
    manifest = load_json(ROOT / "build" / "manifest.json")
    contract = load_json(ROOT / "config" / "nddev-contract.json")
    baseline = load_json(ROOT / "references" / "kimi-code-baseline.json")
    ids = setup_ids()
    if version != "0.1.0":
        raise ValueError("VERSION must be 0.1.0")
    if build.get("build_version") != version or manifest.get("build_version") != version:
        raise ValueError("build version fields are not synchronized")
    if contract.get("version_ref") != "build/version.json":
        raise ValueError("contract version_ref must point at build/version.json")
    if contract.get("manifest_ref") != "build/manifest.json":
        raise ValueError("contract manifest_ref must point at build/manifest.json")
    if "skeleton" in contract:
        raise ValueError("contract must not expose skeleton status")
    if manifest.get("setup_ids") != ids or contract["setup_system"]["setup_ids"] != ids:
        raise ValueError("setup ids are not synchronized")
    if build.get("kimi_code_cli_tested") != baseline["release"]["npm_version"]:
        raise ValueError("tested Kimi Code CLI version differs from baseline release")
    if baseline["release"]["npm_package"] != KIMI_PACKAGE:
        raise ValueError("baseline package must be @moonshot-ai/kimi-code")
    if baseline["release"]["npm_version"] != KIMI_VERSION:
        raise ValueError("baseline version must be 0.29.1")
    if baseline["runtime"]["command"] != KIMI_COMMAND:
        raise ValueError("baseline command must be kimi")
    if baseline["runtime"]["bin"].get(KIMI_COMMAND) != KIMI_BIN:
        raise ValueError("baseline package bin must match official manifest")
    if baseline["release"]["scripts"].get("postinstall") != KIMI_POSTINSTALL:
        raise ValueError("baseline must record the official postinstall script")
    if baseline["runtime"].get("node_engine_runtime") != ">=22.19.0":
        raise ValueError("baseline must record Kimi Code Node runtime requirement")
    if "npm_install" in baseline["runtime"]:
        raise ValueError("runtime baseline must not expose npm install as managed execution")
    software = contract.get("software_lifecycle")
    if not isinstance(software, dict):
        raise ValueError("contract must expose software_lifecycle")
    if software.get("install_argv") != BUN_INSTALL_ARGV:
        raise ValueError("software_lifecycle must use exact bun add --global --exact --trust argv")
    if software.get("trust_required") is not True:
        raise ValueError("software_lifecycle must require trust for Kimi postinstall")
    if software.get("status_executes_binary") is not False:
        raise ValueError("software status must remain read-only")
    if "present=true" not in str(software.get("presence_signal", "")):
        raise ValueError("software lifecycle must expose a stable presence signal")
    if "refuses any existing" not in str(software.get("install_precondition", "")):
        raise ValueError("software lifecycle must document install precondition")
    if "repairs existing" not in str(software.get("update_precondition", "")):
        raise ValueError("software lifecycle must document update repair precondition")
    if software.get("entrypoint_kind") != "node-wrapper":
        raise ValueError("software lifecycle must generate a node wrapper")
    if software.get("entrypoint_main") != ".nddev-kimicode-software/current/install/global/node_modules/@moonshot-ai/kimi-code/dist/main.mjs":
        raise ValueError("software lifecycle must bind wrapper to persisted main.mjs")
    if software.get("node_runtime") != {
        "resolution": "absolute node path resolved during install/update",
        "minimum_version": "22.19.0",
        "recorded_in_stamp": True,
    }:
        raise ValueError("software lifecycle must record absolute node runtime in stamp")
    if software.get("persisted_stage_paths") != ["install/global", "bin"]:
        raise ValueError("software lifecycle must persist only install/global and bin")
    if software.get("ephemeral_stage_paths") != ["home", "xdg-config", "cache", "tmp"]:
        raise ValueError("software lifecycle must keep home/config/cache/tmp ephemeral")
    if software.get("stage_env") != {
        "BUN_INSTALL_GLOBAL_DIR": "<stage>/install/global",
        "BUN_INSTALL_BIN": "<stage>/bin",
        "BUN_INSTALL_CACHE_DIR": "<stage>/cache",
        "HOME": "<stage>/home",
        "XDG_CONFIG_HOME": "<stage>/xdg-config",
        "TMPDIR": "<stage>/tmp",
    }:
        raise ValueError("software lifecycle stage env differs from target-owned Bun contract")
    if build.get("software_install_argv") != BUN_INSTALL_ARGV:
        raise ValueError("build version must expose exact Bun install argv")
    if manifest.get("software_install", {}).get("argv") != BUN_INSTALL_ARGV:
        raise ValueError("manifest must expose exact Bun install argv")
    if manifest.get("software_runtime", {}).get("entrypoint_kind") != "node-wrapper":
        raise ValueError("manifest must expose node wrapper runtime")
    if baseline["software_install"]["argv"] != BUN_INSTALL_ARGV:
        raise ValueError("baseline must expose exact Bun install argv")
    if baseline["software_install"].get("node_minimum") != "22.19.0":
        raise ValueError("baseline must expose node minimum")
    if contract["plugin_marketplace"]["external_marketplace_published"] is not None:
        raise ValueError("external marketplace must remain null until published")
    if contract["plugin_marketplace"]["marketplace_manifest"] is not None:
        raise ValueError("marketplace manifest must remain null until published")
    for relative in (
        "builder/nddev-builder/kimi.plugin.json",
        "builder/nddev-builder/skills/nddev-builder/SKILL.md",
        "builder/nddev-builder/agents/nddev-builder.md",
        "builder/nddev-builder/hooks/nddev-builder-pretooluse.mjs",
        "cli-tools/nddev_kimicode.py",
    ):
        if not (ROOT / relative).is_file():
            raise ValueError(f"missing required public path {relative}")
    validate_workflows()
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
