#!/usr/bin/env python3
"""Validate static public nddev-kimicode-app release artifacts."""

from __future__ import annotations

import argparse
import ast
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = {
    "actionlint.yml",
    "codeql.yml",
    "dependency-review.yml",
    "release.yml",
    "scorecard.yml",
    "secret-scan.yml",
    "zizmor.yml",
}
PRIVATE_PARTS = {"validation", ".agents", ".serena", "__pycache__", ".pytest_cache"}
REQUIRED_MANAGER_FUNCTIONS = {
    "parse_args",
    "install_official_binary",
    "install_or_update_software",
    "publish_missing_lock_file",
    "publish_cleanup_intent",
    "publish_cleanup_journal",
    "reject_managed_launch_overrides",
    "prepare_launch_invocation",
    "launch",
}
SHARED_WORKFLOW_PIN = "2ccb80e96f5771b6a6b4eae63a4f47e232906dc7"
RELEASE_ROOTS = {
    ".claude",
    ".gds",
    ".github",
    "AGENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "VERSION",
    "build",
    "builder",
    "cli-tools",
    "config",
    "docs",
    "profiles",
    "references",
    "setups",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return argparse.ArgumentParser(description=__doc__).parse_args(argv)


def load_json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return value


def require_file(relative: str) -> Path:
    path = ROOT / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing regular public file: {relative}")
    return path


def manager_constants() -> dict[str, Any]:
    source = require_file("cli-tools/nddev_kimicode.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    constants: dict[str, Any] = {}
    functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = REQUIRED_MANAGER_FUNCTIONS - functions
    if missing:
        raise ValueError(f"manager functions are missing: {sorted(missing)}")
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    return constants


def validate_metadata() -> None:
    version = require_file("VERSION").read_text(encoding="ascii").strip()
    build = load_json("build/version.json")
    manifest = load_json("build/manifest.json")
    contract = load_json("config/nddev-contract.json")
    baseline = load_json("references/kimi-code-baseline.json")
    setup = load_json("setups/nddev-builder/setup.json")
    plugin = load_json("builder/nddev-builder/kimi.plugin.json")
    safe = load_json("profiles/safe/profile.json")
    full_auto = load_json("profiles/full-auto/profile.json")
    constants = manager_constants()

    if {version, build.get("build_version"), manifest.get("build_version"), plugin.get("version")} != {
        version
    }:
        raise ValueError("public build versions are not synchronized")
    runtime = baseline.get("release", {}).get("npm_version")
    if {
        runtime,
        build.get("kimi_code_cli_tested"),
        manifest.get("kimi_code_cli_tested"),
        contract.get("runtime_compatibility", {}).get("tested_release"),
        constants.get("KIMI_PACKAGE_VERSION"),
    } != {runtime}:
        raise ValueError("Kimi runtime versions are not synchronized")
    if build.get("content_setup_ids") != ["nddev-builder"]:
        raise ValueError("content setup catalog mismatch")
    if build.get("permission_profile_ids") != ["safe", "full-auto"]:
        raise ValueError("permission profile catalog mismatch")
    if setup.get("managed_surfaces") != [
        "AGENTS.md",
        "skills",
        "agents",
        "hooks",
        "mcp",
        "plugin_source",
    ]:
        raise ValueError("native setup surfaces mismatch")
    if safe.get("native_permission_mode") != "manual":
        raise ValueError("safe profile must use native manual permissions")
    if full_auto.get("native_permission_mode") != "auto":
        raise ValueError("full-auto profile must use native auto permissions")
    builder = contract.get("builder_toolkit", {})
    if builder.get("runtime_plugin_install_state_written") is not False:
        raise ValueError("runtime plugin installed state must remain vendor-owned")
    if builder.get("marketplace_manifest") is not None:
        raise ValueError("module must not synthesize a Kimi marketplace manifest")
    if "plugins/installed.json" in constants.get("CONTENT_MANAGED_BASE_PATHS", ()):
        raise ValueError("manager must not own Kimi plugin installed state")


def validate_integrity_metadata() -> None:
    baseline = load_json("references/kimi-code-baseline.json")
    manifest = load_json("build/manifest.json")
    contract = load_json("config/nddev-contract.json")
    observations = baseline.get("vendor_distribution_observations")
    if not isinstance(observations, dict):
        raise ValueError("vendor distribution observations are missing")
    if observations != manifest.get("software_install", {}).get(
        "vendor_distribution_observations"
    ):
        raise ValueError("manifest vendor observations drifted")
    if observations != contract.get("runtime_compatibility", {}).get(
        "vendor_distribution_observations"
    ):
        raise ValueError("contract vendor observations drifted")
    artifacts = baseline.get("official_binary_install", {}).get("platforms", {})
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "darwin-arm64",
        "darwin-x64",
        "linux-arm64",
        "linux-x64",
        "win32-arm64",
        "win32-x64",
    }:
        raise ValueError("official binary artifact catalog is incomplete")
    for platform, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            raise ValueError(f"{platform} artifact must be an object")
        if not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256"))):
            raise ValueError(f"{platform} artifact sha256 is invalid")
        if not isinstance(artifact.get("size_bytes"), int) or artifact["size_bytes"] <= 0:
            raise ValueError(f"{platform} artifact size is invalid")


def validate_builder_tree() -> None:
    root = ROOT / "builder" / "nddev-builder"
    required = {
        "agents/nddev-builder.md",
        "hooks/nddev-builder-pretooluse.py",
        "kimi.plugin.json",
        "skills/nddev-builder/SKILL.md",
    }
    for relative in required:
        require_file(f"builder/nddev-builder/{relative}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"builder tree contains a symlink: {path.relative_to(ROOT)}")


def validate_release_and_workflows() -> None:
    for workflow in WORKFLOWS:
        text = require_file(f".github/workflows/{workflow}").read_text(encoding="utf-8")
        if workflow in {"actionlint.yml", "codeql.yml", "dependency-review.yml", "scorecard.yml", "secret-scan.yml", "zizmor.yml"}:
            if SHARED_WORKFLOW_PIN not in text:
                raise ValueError(f"{workflow}: shared workflow pin mismatch")
    release = require_file(".github/workflows/release.yml").read_text(encoding="utf-8")
    required = {
        "permissions: {}",
        'tags:\n      - "[0-9]+.[0-9]+.[0-9]+"',
        f"release-supply-chain.yml@{SHARED_WORKFLOW_PIN}",
        "version: ${{ github.ref_name }}",
        "package_name: nddev-kimicode-app",
        "archive_paths:",
        "runtime_paths:",
    }
    missing = sorted(fragment for fragment in required if fragment not in release)
    if missing:
        raise ValueError(f"release workflow contract is incomplete: {missing}")
    folded = {
        token
        for line in release.splitlines()
        if line.startswith("        ")
        for token in line.split()
    }
    if not RELEASE_ROOTS.issubset(folded):
        raise ValueError(f"release archive closure is incomplete: {sorted(RELEASE_ROOTS - folded)}")
    for relative in RELEASE_ROOTS:
        path = ROOT / relative
        if not path.exists() or path.is_symlink():
            raise ValueError(f"release root is missing or unsafe: {relative}")


def validate_docs_and_runtime_integrity() -> None:
    for relative in ("README.md", "docs/SETUP_MANAGER.md"):
        if not require_file(relative).read_text(encoding="utf-8").strip():
            raise ValueError(f"{relative}: public documentation is empty")
    manager = require_file("cli-tools/nddev_kimicode.py").read_text(encoding="utf-8")
    forbidden = (
        "os.replace(temp_path, lock_path)",
        "NDDEV_KIMI_TEST_BOOTSTRAP",
    )
    present = sorted(fragment for fragment in forbidden if fragment in manager)
    if present:
        raise ValueError(f"manager contains forbidden runtime-integrity fragments: {present}")
    required = (
        "rename_no_replace",
        "O_NOFOLLOW",
        "cleanup_pending",
        "KIMI_CODE_HOME",
        "reject_managed_launch_overrides",
    )
    missing = sorted(fragment for fragment in required if fragment not in manager)
    if missing:
        raise ValueError(f"manager runtime-integrity fragments are missing: {missing}")


def validate_public_surface() -> None:
    claude = ROOT / ".claude"
    if not stat.S_ISDIR(claude.lstat().st_mode) or claude.is_symlink():
        raise ValueError(".claude must be a real directory")
    if sorted(path.name for path in claude.iterdir()) != ["CLAUDE.md"]:
        raise ValueError(".claude must contain exactly CLAUDE.md")
    require_file("AGENTS.md")
    bridge = require_file(".claude/CLAUDE.md")
    if bridge.read_bytes() != b"@../AGENTS.md\n":
        raise ValueError("Claude bridge must point to AGENTS.md")
    for path in ROOT.rglob("*"):
        if path.is_file() and PRIVATE_PARTS.intersection(path.relative_to(ROOT).parts):
            raise ValueError(f"private artifact is tracked in the public tree: {path}")


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    validate_metadata()
    validate_integrity_metadata()
    validate_builder_tree()
    validate_release_and_workflows()
    validate_docs_and_runtime_integrity()
    validate_public_surface()
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
