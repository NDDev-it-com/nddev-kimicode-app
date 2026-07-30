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

    schemas = {
        "build/version.json": build.get("schema_version"),
        "build/manifest.json": manifest.get("schema_version"),
        "config/nddev-contract.json": contract.get("contract_version"),
        "references/kimi-code-baseline.json": baseline.get("schema_version"),
    }
    if schemas != {
        "build/version.json": 4,
        "build/manifest.json": 3,
        "config/nddev-contract.json": 4,
        "references/kimi-code-baseline.json": 3,
    }:
        raise ValueError(f"public metadata schema versions are not synchronized: {schemas}")
    if {
        version,
        build.get("build_version"),
        manifest.get("build_version"),
        plugin.get("version"),
    } != {version}:
        raise ValueError("public build versions are not synchronized")
    runtime = baseline.get("release", {}).get("version")
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
    build = load_json("build/version.json")
    baseline = load_json("references/kimi-code-baseline.json")
    manifest = load_json("build/manifest.json")
    contract = load_json("config/nddev-contract.json")
    manager_source = require_file("cli-tools/nddev_kimicode.py").read_text(encoding="utf-8")
    manager_tree = ast.parse(manager_source)
    manager_assignments = {
        target.id
        for node in manager_tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    forbidden_constants = {
        "KIMI_GITHUB_RELEASE_ASSETS",
        "KIMI_GITHUB_RELEASE_API_URL",
        "KIMI_GITHUB_RELEASE_ID",
        "KIMI_GITHUB_RELEASE_URL",
        "KIMI_GIT_COMMIT",
        "KIMI_GIT_TAG",
        "KIMI_GIT_TAG_OBJECT",
        "KIMI_INSTALL_POWERSHELL_SHA256",
        "KIMI_INSTALL_POWERSHELL_SIZE_BYTES",
        "KIMI_INSTALL_POWERSHELL_URL",
        "KIMI_INSTALL_SCRIPT_SHA256",
        "KIMI_INSTALL_SCRIPT_URL",
        "KIMI_LATEST_URL",
        "KIMI_NPM_FILE_COUNT",
        "KIMI_NPM_INTEGRITY",
        "KIMI_NPM_METADATA_SHA256",
        "KIMI_NPM_SHASUM",
        "KIMI_NPM_UNPACKED_SIZE",
        "KIMI_OBSERVED_BINARY_PLATFORMS",
        "KIMI_OBSERVED_VENDOR_PLATFORMS",
        "KIMI_PACKAGE_NAME",
        "KIMI_UBUNTU_GLIBC_VERSION_FLOOR",
        "KIMI_VENDOR_DISTRIBUTION_OBSERVATIONS",
    }
    present_constants = sorted(forbidden_constants & manager_assignments)
    if present_constants:
        raise ValueError(f"manager exposes raw vendor observations: {present_constants}")

    source_contract_keys: set[str] | None = None
    for node in manager_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "software_source_contract":
            returns = [
                candidate
                for candidate in ast.walk(node)
                if isinstance(candidate, ast.Return) and isinstance(candidate.value, ast.Dict)
            ]
            if len(returns) == 1:
                keys = returns[0].value.keys
                if all(
                    isinstance(key, ast.Constant) and isinstance(key.value, str) for key in keys
                ):
                    source_contract_keys = {str(key.value) for key in keys}
            break
    if source_contract_keys != {"channel", "manifest_url", "manifest_sha256"}:
        raise ValueError(
            f"manager source contract exposes non-runtime keys: {source_contract_keys}"
        )

    forbidden_keys = {
        "checksum",
        "file_count",
        "git_commit",
        "git_tag",
        "git_tag_object",
        "github_release_api_url",
        "github_release_id",
        "github_release_url",
        "install_powershell_product_supported",
        "install_powershell_sha256",
        "install_powershell_size_bytes",
        "install_powershell_url",
        "install_script_sha256",
        "install_script_url",
        "integrity",
        "kimi_code_cli_package",
        "latest_url",
        "manifest_size_bytes",
        "node_engine",
        "npm_alternative_recorded",
        "npm_metadata_sha256",
        "npm_package",
        "observed_at",
        "observed_vendor_artifacts",
        "observed_vendor_platforms",
        "official_windows_install_surface",
        "published_at",
        "shasum",
        "source_family",
        "source_path",
        "source_url",
        "supported_product_hosts",
        "tarball",
        "ubuntu_glibc_version_floor",
        "ubuntu_glibc_version_floor_source",
        "unpacked_size",
        "vendor_distribution_observations",
    }

    def find_forbidden_keys(value: object, path: str) -> list[str]:
        findings: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key in forbidden_keys:
                    findings.append(child_path)
                findings.extend(find_forbidden_keys(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                findings.extend(find_forbidden_keys(child, f"{path}[{index}]"))
        return findings

    public_documents = {
        "build/version.json": build,
        "baseline": baseline,
        "manifest": manifest,
        "contract": contract,
    }
    raw_key_paths = sorted(
        path
        for owner, value in public_documents.items()
        for path in find_forbidden_keys(value, owner)
    )
    if raw_key_paths:
        raise ValueError(f"public metadata exposes raw vendor keys: {raw_key_paths}")

    observation_text = manager_source + json.dumps(public_documents, sort_keys=True)
    forbidden_endpoints = {
        "@moonshot-ai/kimi-code",
        "https://api.github.com/repos/MoonshotAI/kimi-code",
        "https://code.kimi.com/kimi-code/install.",
        "https://code.kimi.com/kimi-code/latest",
        "https://github.com/MoonshotAI/kimi-code",
        "https://registry.npmjs.org/@moonshot-ai",
        "win32-",
    }
    present_endpoints = sorted(
        endpoint for endpoint in forbidden_endpoints if endpoint in observation_text
    )
    if present_endpoints:
        raise ValueError(f"public metadata exposes raw vendor endpoints: {present_endpoints}")

    public_owners = {
        "baseline": baseline,
        "manifest": manifest.get("software_install", {}),
        "contract": contract.get("runtime_compatibility", {}),
    }
    for owner, value in public_owners.items():
        if not isinstance(value, dict):
            raise ValueError(f"{owner} integrity metadata must be an object")

    official_install = baseline.get("official_binary_install", {})
    manifest_install = manifest.get("software_install", {})
    contract_lifecycle = contract.get("software_lifecycle", {})
    pin_owners = {
        "baseline official install": official_install,
        "manifest software install": manifest_install,
        "contract software lifecycle": contract_lifecycle,
    }
    for owner, value in pin_owners.items():
        if not isinstance(value, dict):
            raise ValueError(f"{owner} must be an object")
    manifest_identity = {
        (
            owner.get("manifest_url"),
            owner.get("manifest_sha256"),
        )
        for owner in pin_owners.values()
    }
    if len(manifest_identity) != 1:
        raise ValueError("official binary manifest pins drifted")

    artifacts = official_install.get("platforms", {})
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "darwin-arm64",
        "darwin-x64",
        "linux-arm64",
        "linux-x64",
    }:
        raise ValueError("supported official binary artifact catalog is invalid")
    artifact_fields = (
        "filename",
        "url",
        "size_bytes",
        "sha256",
    )
    artifact_projection = {
        platform: {field: artifact.get(field) for field in artifact_fields}
        for platform, artifact in artifacts.items()
        if isinstance(artifact, dict)
    }
    manifest_runtime = manifest.get("software_runtime", {})
    contract_runtime = contract.get("runtime_compatibility", {})
    manifest_artifacts = manifest_runtime.get("supported_binary_artifacts")
    contract_artifacts = contract_runtime.get("supported_binary_artifacts")
    if artifact_projection != manifest_artifacts or artifact_projection != contract_artifacts:
        raise ValueError("official binary platform pins drifted")
    supported_platforms = list(artifacts)
    if (
        official_install.get("supported_vendor_platforms") != supported_platforms
        or manifest_runtime.get("supported_vendor_platforms") != supported_platforms
        or contract_runtime.get("supported_vendor_platforms") != supported_platforms
    ):
        raise ValueError("supported vendor platform catalogs drifted")
    for platform, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            raise ValueError(f"{platform} artifact must be an object")
        if set(artifact) != set(artifact_fields):
            raise ValueError(f"{platform} artifact keys are invalid")
        expected_url = (
            f"https://code.kimi.com/kimi-code/binaries/"
            f"{baseline.get('release', {}).get('version')}/{artifact.get('filename')}"
        )
        if artifact.get("url") != expected_url:
            raise ValueError(f"{platform} artifact URL is invalid")
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
        if workflow in {
            "actionlint.yml",
            "codeql.yml",
            "dependency-review.yml",
            "scorecard.yml",
            "secret-scan.yml",
            "zizmor.yml",
        }:
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
