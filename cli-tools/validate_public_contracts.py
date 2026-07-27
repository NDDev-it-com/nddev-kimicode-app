#!/usr/bin/env python3
"""Validate public nddev-kimicode-app release contracts."""

from __future__ import annotations

import argparse
import json
import re
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
KIMI_VERSION = "0.29.2"
KIMI_PACKAGE = "@moonshot-ai/kimi-code"
KIMI_COMMAND = "kimi"
CONTENT_SETUPS = ["nddev-builder"]
PROFILES = ["safe", "full-auto"]
DEFAULT_PROFILE = "full-auto"
MANIFEST_SHA256 = "6057703f6430964741198c81617737bcec917082d1ce4aadd7a1b8c29787ae9b"
INSTALL_SCRIPT_SHA256 = "638927825e96825edbb563de5e0cb06f8a0551c53e026ade8b717b0f25cb83d2"
NPM_INTEGRITY = "sha512-NmID/2+rCbZXvnQIBZxZlLzeUjETjb1BPzfkUoVs6AhQv9xuGKLzQvcUJB+yksRZnWE+ikLMWyIn75rVfMMP4w=="
NPM_SHASUM = "9e8da7ca4e822048a28d1e12ff46c8ea5ecb23ac"
BINARY_PLATFORMS = {
    "darwin-arm64": ("kimi-code-darwin-arm64", "25dc8b14f8bb5ef98470577265b1e9c95892c168f34e9639c5f63b48d4ece6fb"),
    "darwin-x64": ("kimi-code-darwin-x64", "fe59f14cab74971768377e586bf3be30c1ca04079c058d4b492827ca4dfd6b16"),
    "linux-arm64": ("kimi-code-linux-arm64", "5fb64e74eeec0b3900732cfbc3679cc505beb51aa323f486154fd79b0e20b26a"),
    "linux-x64": ("kimi-code-linux-x64", "f9977d259ed36019793cadf04b1f0343f12aaebfa76f90fa26cd3b02be671231"),
}
CONTRACT_KEYS = {
    "contract_version",
    "product_name",
    "github_repository",
    "license",
    "manifest_ref",
    "version_ref",
    "managed_state",
    "setup_system",
    "safety",
    "runtime_compatibility",
    "software_lifecycle",
    "runtime_launch",
    "builder_toolkit",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_workflows() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    for filename, workflow in REQUIRED_WORKFLOWS.items():
        path = workflow_root / filename
        if not path.is_file():
            raise ValueError(f"missing workflow {path.relative_to(ROOT)}")
        expected = f"uses: NDDev-it-com/ci-workflows/{workflow}@{SHARED_CI_COMMIT} # {SHARED_CI_VERSION}"
        text = path.read_text(encoding="utf-8")
        if text.count(expected) != 1:
            raise ValueError(f"{filename}: missing exact shared CI caller")


def validate_catalog() -> None:
    if (ROOT / "setups" / "balanced").exists():
        raise ValueError("balanced setup must not ship")
    if (ROOT / "profiles" / "yolo").exists():
        raise ValueError("yolo profile must not ship")
    for setup_id in CONTENT_SETUPS:
        setup = load_json(ROOT / "setups" / setup_id / "setup.json")
        if setup.get("id") != setup_id:
            raise ValueError(f"content setup id mismatch: {setup_id}")
    safe = load_json(ROOT / "profiles" / "safe" / "profile.json")
    full_auto = load_json(ROOT / "profiles" / "full-auto" / "profile.json")
    if safe.get("native_permission_mode") != "manual" or safe.get("plan_mode") is not True:
        raise ValueError("safe must map to native manual with plan mode")
    if full_auto.get("native_permission_mode") != "auto" or full_auto.get("plan_mode") is not False:
        raise ValueError("full-auto must map to native auto without plan mode")
    if full_auto.get("permission_rules") != []:
        raise ValueError("full-auto must not carry permission rules")


def validate_baseline(baseline: dict[str, Any]) -> None:
    release = baseline["release"]
    if release.get("npm_package") != KIMI_PACKAGE or release.get("npm_version") != KIMI_VERSION:
        raise ValueError("baseline release identity mismatch")
    if release.get("integrity") != NPM_INTEGRITY or release.get("shasum") != NPM_SHASUM:
        raise ValueError("baseline npm provenance mismatch")
    install = baseline["official_binary_install"]
    if install.get("install_script_sha256") != INSTALL_SCRIPT_SHA256:
        raise ValueError("install script digest mismatch")
    if install.get("manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("binary manifest digest mismatch")
    platforms = install.get("platforms")
    if not isinstance(platforms, dict) or sorted(platforms) != sorted(BINARY_PLATFORMS):
        raise ValueError("official binary platform set mismatch")
    for key, (filename, checksum) in BINARY_PLATFORMS.items():
        entry = platforms[key]
        if entry.get("filename") != filename or entry.get("checksum") != checksum:
            raise ValueError(f"official binary digest mismatch for {key}")
    if baseline["permission_model"].get("full_auto") != "auto with plan mode disabled":
        raise ValueError("baseline must record full-auto native auto mapping")
    if baseline["native_surfaces"].get("direct_plugin_install_state_write") is not False:
        raise ValueError("baseline must forbid direct plugin install-state writes")
    unsupported = baseline.get("unsupported", {})
    if unsupported.get("windows") is not True:
        raise ValueError("baseline must mark Windows unsupported")


def frontmatter(text: str, path: Path) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ValueError(f"{path.relative_to(ROOT)} missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"{path.relative_to(ROOT)} has unterminated frontmatter")
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.startswith("  "):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"')
    return fields


def validate_builder_toolkit() -> None:
    version = public_version()
    skill_root = ROOT / "builder" / "nddev-builder" / "skills"
    expected_skills = {
        "nddev-builder",
        "kimicode-config-profile",
        "kimicode-permissions-sandbox",
        "kimicode-instructions-agents-skills",
        "kimicode-plugins-marketplace",
        "kimicode-hooks",
        "kimicode-mcp",
        "kimicode-install-lifecycle",
        "kimicode-create-check-release",
    }
    actual_skills = {path.parent.name for path in skill_root.glob("*/SKILL.md")}
    if actual_skills != expected_skills:
        raise ValueError("builder toolkit skill set mismatch")
    for path in skill_root.glob("*/SKILL.md"):
        fields = frontmatter(path.read_text(encoding="utf-8"), path)
        if not fields.get("name") or not fields.get("description"):
            raise ValueError(f"{path.relative_to(ROOT)} missing required Kimi Skill fields")
    entry = (skill_root / "nddev-builder" / "SKILL.md").read_text(encoding="utf-8")
    for routed in sorted(expected_skills - {"nddev-builder"}):
        if routed not in entry:
            raise ValueError(f"entry skill does not route to {routed}")
    for reference in (
        skill_root / "nddev-builder" / "references" / "native-surfaces.md",
        skill_root / "nddev-builder" / "references" / "public-validation.md",
    ):
        if not reference.is_file():
            raise ValueError(f"missing routed reference {reference.relative_to(ROOT)}")
    agent_text = (ROOT / "builder" / "nddev-builder" / "agents" / "nddev-builder.md").read_text(encoding="utf-8")
    if re.search(r"^tools:", agent_text, re.MULTILINE):
        raise ValueError("builder agent must omit tools allowlist to inherit native tools")
    if "disallowedTools: []" not in agent_text:
        raise ValueError("builder agent must keep disallowedTools empty")
    plugin = load_json(ROOT / "builder" / "nddev-builder" / "kimi.plugin.json")
    if plugin.get("version") != version:
        raise ValueError("builder plugin version must match public build")
    if plugin.get("hooks") not in (None, []):
        raise ValueError("builder plugin source must not declare unconditional hooks")
    manager_text = (ROOT / "cli-tools" / "nddev_kimicode.py").read_text(encoding="utf-8")
    if "plugins/managed/nddev-builder" in manager_text:
        raise ValueError("manager must not write runtime-owned plugin managed directory")
    if 'profile_data["id"] == "safe"' not in manager_text:
        raise ValueError("blocking hook activation must be profile-specific to safe")


def public_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("VERSION must be a semantic version")
    return version


def validate_metadata() -> None:
    version = public_version()
    build = load_json(ROOT / "build" / "version.json")
    manifest = load_json(ROOT / "build" / "manifest.json")
    contract = load_json(ROOT / "config" / "nddev-contract.json")
    baseline = load_json(ROOT / "references" / "kimi-code-baseline.json")
    if build.get("build_version") != version or manifest.get("build_version") != version:
        raise ValueError("build version fields are not synchronized")
    if build.get("kimi_code_cli_tested") != KIMI_VERSION or manifest.get("kimi_code_cli_tested") != KIMI_VERSION:
        raise ValueError("tested Kimi release fields are not synchronized")
    if build.get("content_setup_ids") != CONTENT_SETUPS or manifest.get("content_setup_ids") != CONTENT_SETUPS:
        raise ValueError("content setup ids are not synchronized")
    if build.get("permission_profile_ids") != PROFILES or manifest.get("permission_profile_ids") != PROFILES:
        raise ValueError("permission profile ids are not synchronized")
    if build.get("default_permission_profile") != DEFAULT_PROFILE or manifest.get("default_permission_profile") != DEFAULT_PROFILE:
        raise ValueError("default profile must be full-auto")
    if contract.get("contract_version") != 3 or set(contract) != CONTRACT_KEYS:
        raise ValueError("contract v3 top-level keys are not exact")
    if contract.get("version_ref") != "build/version.json" or contract.get("manifest_ref") != "build/manifest.json":
        raise ValueError("contract refs are invalid")
    setup_system = contract["setup_system"]
    if setup_system.get("content_setup_ids") != CONTENT_SETUPS or setup_system.get("permission_profile_ids") != PROFILES:
        raise ValueError("contract catalog ids are not synchronized")
    if setup_system.get("full_auto_native_permission_mode") != "auto":
        raise ValueError("contract must map full-auto to native auto")
    if setup_system.get("yolo_profile_shipped") is not False:
        raise ValueError("contract must not ship yolo")
    if contract["safety"].get("full_auto_active_blocking_hooks") is not False:
        raise ValueError("contract must state full-auto has no active blocking hooks")
    software = contract["software_lifecycle"]
    if software.get("channel") != "official-binary" or software.get("manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("contract software lifecycle must use official binary manifest")
    if software.get("status_executes_binary") is not False:
        raise ValueError("software status must remain read-only")
    if contract["runtime_compatibility"].get("windows_supported") is not False:
        raise ValueError("Windows must be unsupported")
    validate_baseline(baseline)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    validate_catalog()
    validate_metadata()
    validate_builder_toolkit()
    validate_workflows()
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
