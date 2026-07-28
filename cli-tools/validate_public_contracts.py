#!/usr/bin/env python3
"""Validate public nddev-kimicode-app release contracts."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

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
RELEASE_WORKFLOW = ".github/workflows/release.yml"
RELEASE_PACKAGE_NAME = "nddev-kimicode-app"
CLAUDE_INSTRUCTION_PATH = ".claude/CLAUDE.md"
RELEASE_CALLER_PERMISSIONS = {
    "contents": "write",
    "id-token": "write",
    "attestations": "write",
    "artifact-metadata": "write",
}
RELEASE_PATHS = (
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
)
RELEASE_CONTRACT_ROOTS = (
    ".gds",
    ".github",
    "build",
    "builder",
    "cli-tools",
    "config",
    "docs",
    "profiles",
    "references",
    "setups",
)
PRIVATE_RELEASE_ROOTS = {"validation", ".agents", ".serena"}
PRIVATE_RELEASE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
PRIVATE_RELEASE_SUFFIXES = (".pyc", ".pyo")
PRIVATE_RELEASE_PREFIXES = (".tmp-kimicode-",)
PUBLIC_VALIDATION_DOCS = (
    Path("AGENTS.md"),
    Path("builder/nddev-builder/skills/nddev-builder/references/public-validation.md"),
    Path("builder/nddev-builder/skills/kimicode-create-check-release/SKILL.md"),
)
CACHE_FREE_PUBLIC_COMMANDS = (
    ("python3", "cli-tools/validate_public_contracts.py"),
    ("python3", "cli-tools/nddev_kimicode.py", "list", "--json"),
    ("python3", "cli-tools/nddev_kimicode.py", "--help"),
)
FORBIDDEN_PUBLIC_VALIDATION_COMMAND_TERMS = ("py_compile", "compileall")
KIMI_VERSION = "0.29.2"
KIMI_PACKAGE = "@moonshot-ai/kimi-code"
KIMI_COMMAND = "kimi"
PYTHON_REQUIRES = ">=3.9"
CONTENT_SETUPS = ["nddev-builder"]
PROFILES = ["safe", "full-auto"]
DEFAULT_PROFILE = "full-auto"
MANIFEST_SHA256 = "6057703f6430964741198c81617737bcec917082d1ce4aadd7a1b8c29787ae9b"
CODE_KIMI_MANIFEST_SIZE_BYTES = 929
GITHUB_RELEASE_API_URL = (
    "https://api.github.com/repos/MoonshotAI/kimi-code/releases/tags/"
    "%40moonshot-ai%2Fkimi-code%400.29.2"
)
GITHUB_RELEASE_ASSET_NAMES = [
    "kimi-code-darwin-arm64.zip",
    "kimi-code-darwin-arm64.zip.sha256",
    "kimi-code-darwin-x64.zip",
    "kimi-code-darwin-x64.zip.sha256",
    "kimi-code-linux-arm64.zip",
    "kimi-code-linux-arm64.zip.sha256",
    "kimi-code-linux-x64.zip",
    "kimi-code-linux-x64.zip.sha256",
    "kimi-code-win32-arm64.zip",
    "kimi-code-win32-arm64.zip.sha256",
    "kimi-code-win32-x64.zip",
    "kimi-code-win32-x64.zip.sha256",
    "manifest.json",
]
GITHUB_RELEASE_PLATFORM_ZIPS = [
    name for name in GITHUB_RELEASE_ASSET_NAMES if name.endswith(".zip")
]
GITHUB_RELEASE_SHA256_SIDECARS = [
    name for name in GITHUB_RELEASE_ASSET_NAMES if name.endswith(".zip.sha256")
]
GITHUB_RELEASE_MANIFEST_ASSET_SHA256 = (
    "650a07b7b10f74eec20fb12b452f80b5319e6250563abf60acee97fc3aac9e12"
)
INSTALL_SCRIPT_SHA256 = "638927825e96825edbb563de5e0cb06f8a0551c53e026ade8b717b0f25cb83d2"
INSTALL_POWERSHELL_SHA256 = "28a0473a7c56d41eae52cb4dbd3232f87a9133dd7af416a6a04dfbf7856fa9fc"
INSTALL_POWERSHELL_SIZE_BYTES = 15891
NPM_INTEGRITY = "sha512-NmID/2+rCbZXvnQIBZxZlLzeUjETjb1BPzfkUoVs6AhQv9xuGKLzQvcUJB+yksRZnWE+ikLMWyIn75rVfMMP4w=="
NPM_SHASUM = "9e8da7ca4e822048a28d1e12ff46c8ea5ecb23ac"
OBSERVED_BINARY_ARTIFACTS = {
    "darwin-arm64": {
        "filename": "kimi-code-darwin-arm64",
        "url": "https://code.kimi.com/kimi-code/binaries/0.29.2/kimi-code-darwin-arm64",
        "size_bytes": 160002496,
        "sha256": "25dc8b14f8bb5ef98470577265b1e9c95892c168f34e9639c5f63b48d4ece6fb",
        "supported_product_hosts": ["macos-arm64"],
    },
    "darwin-x64": {
        "filename": "kimi-code-darwin-x64",
        "url": "https://code.kimi.com/kimi-code/binaries/0.29.2/kimi-code-darwin-x64",
        "size_bytes": 162344320,
        "sha256": "fe59f14cab74971768377e586bf3be30c1ca04079c058d4b492827ca4dfd6b16",
        "supported_product_hosts": ["macos-x64"],
    },
    "linux-arm64": {
        "filename": "kimi-code-linux-arm64",
        "url": "https://code.kimi.com/kimi-code/binaries/0.29.2/kimi-code-linux-arm64",
        "size_bytes": 160500864,
        "sha256": "5fb64e74eeec0b3900732cfbc3679cc505beb51aa323f486154fd79b0e20b26a",
        "supported_product_hosts": ["ubuntu-glibc-arm64"],
    },
    "linux-x64": {
        "filename": "kimi-code-linux-x64",
        "url": "https://code.kimi.com/kimi-code/binaries/0.29.2/kimi-code-linux-x64",
        "size_bytes": 162860224,
        "sha256": "f9977d259ed36019793cadf04b1f0343f12aaebfa76f90fa26cd3b02be671231",
        "supported_product_hosts": ["ubuntu-glibc-x64"],
    },
    "win32-arm64": {
        "filename": "kimi-code-win32-arm64.exe",
        "url": "https://code.kimi.com/kimi-code/binaries/0.29.2/kimi-code-win32-arm64.exe",
        "size_bytes": 120212992,
        "sha256": "26cd0ab7267aab92530a9584778deb5fa2c37c44131c8b2d8ec653e474f288c8",
        "supported_product_hosts": [],
    },
    "win32-x64": {
        "filename": "kimi-code-win32-x64.exe",
        "url": "https://code.kimi.com/kimi-code/binaries/0.29.2/kimi-code-win32-x64.exe",
        "size_bytes": 131644416,
        "sha256": "32ea71e814b53958afaa37f15982647e6c832cb70922941ca35a57d01f64e12f",
        "supported_product_hosts": [],
    },
}
BINARY_PLATFORMS = {
    key: (value["filename"], value["sha256"]) for key, value in OBSERVED_BINARY_ARTIFACTS.items()
}
OBSERVED_VENDOR_PLATFORMS = list(OBSERVED_BINARY_ARTIFACTS)
SUPPORTED_HOSTS = ["macos-arm64", "macos-x64", "ubuntu-glibc-arm64", "ubuntu-glibc-x64"]
HOST_TO_VENDOR_PLATFORM = {
    "macos-arm64": "darwin-arm64",
    "macos-x64": "darwin-x64",
    "ubuntu-glibc-arm64": "linux-arm64",
    "ubuntu-glibc-x64": "linux-x64",
}
UNSUPPORTED_HOST_CATEGORIES = [
    "windows",
    "non-ubuntu-linux",
    "linux-musl",
    "unsupported-architecture",
]
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


def load_manager() -> Any:
    path = ROOT / "cli-tools" / "nddev_kimicode.py"
    module_name = "_nddev_kimicode_public_validator"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError("could not load nddev_kimicode.py for isolated regressions")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - surfaced as validator failure.
        raise ValueError(f"could not import nddev_kimicode.py: {exc}") from exc
    return module


def require_mapping(value: Any, expected_keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if set(value) != expected_keys:
        raise ValueError(f"{label} keys are not exact")
    return value


def validate_vendor_distribution_observations(value: Any, label: str) -> None:
    observations = require_mapping(
        value,
        {"github_release_assets", "code_kimi_binary_manifest", "product_selections"},
        label,
    )
    github = require_mapping(
        observations["github_release_assets"],
        {
            "source_family",
            "release_url",
            "api_url",
            "release_id",
            "tag",
            "asset_count",
            "platform_zip_count",
            "sha256_sidecar_count",
            "manifest_count",
            "assets",
        },
        f"{label}.github_release_assets",
    )
    if github.get("source_family") != "github-release-assets":
        raise ValueError(f"{label}: GitHub source family mismatch")
    if github.get("api_url") != GITHUB_RELEASE_API_URL:
        raise ValueError(f"{label}: GitHub release API URL mismatch")
    if (
        github.get("asset_count") != 13
        or github.get("platform_zip_count") != 6
        or github.get("sha256_sidecar_count") != 6
        or github.get("manifest_count") != 1
    ):
        raise ValueError(f"{label}: GitHub release asset counts are incomplete")
    assets = github.get("assets")
    if not isinstance(assets, dict) or sorted(assets) != GITHUB_RELEASE_ASSET_NAMES:
        raise ValueError(f"{label}: GitHub release asset name set is incomplete")
    for name, asset in assets.items():
        if set(asset) != {"kind", "url", "size_bytes", "sha256"}:
            raise ValueError(f"{label}: GitHub release asset keys are not exact for {name}")
        if name in GITHUB_RELEASE_PLATFORM_ZIPS:
            expected_kind = "platform-zip"
        elif name in GITHUB_RELEASE_SHA256_SIDECARS:
            expected_kind = "sha256-sidecar"
        else:
            expected_kind = "manifest"
        if asset.get("kind") != expected_kind:
            raise ValueError(f"{label}: GitHub release asset kind mismatch for {name}")
        if not isinstance(asset.get("size_bytes"), int) or asset["size_bytes"] <= 0:
            raise ValueError(f"{label}: GitHub release asset size is invalid for {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(asset.get("sha256"))):
            raise ValueError(f"{label}: GitHub release asset sha256 is invalid for {name}")
    if assets["manifest.json"]["sha256"] != GITHUB_RELEASE_MANIFEST_ASSET_SHA256:
        raise ValueError(f"{label}: GitHub release manifest asset digest mismatch")

    code_kimi = require_mapping(
        observations["code_kimi_binary_manifest"],
        {
            "source_family",
            "manifest_url",
            "manifest_sha256",
            "manifest_size_bytes",
            "version",
            "tag",
            "platform_count",
            "observed_vendor_platforms",
            "platforms",
        },
        f"{label}.code_kimi_binary_manifest",
    )
    if code_kimi.get("source_family") != "code.kimi.com-binary-manifest":
        raise ValueError(f"{label}: code.kimi.com source family mismatch")
    if (
        code_kimi.get("manifest_sha256") != MANIFEST_SHA256
        or code_kimi.get("manifest_size_bytes") != CODE_KIMI_MANIFEST_SIZE_BYTES
        or code_kimi.get("version") != KIMI_VERSION
        or code_kimi.get("platform_count") != 6
    ):
        raise ValueError(f"{label}: code.kimi.com manifest observation mismatch")
    if code_kimi.get("observed_vendor_platforms") != OBSERVED_VENDOR_PLATFORMS:
        raise ValueError(f"{label}: code.kimi.com observed platform set mismatch")
    if code_kimi.get("platforms") != OBSERVED_BINARY_ARTIFACTS:
        raise ValueError(f"{label}: code.kimi.com platform observations mismatch")

    product = require_mapping(
        observations["product_selections"],
        {
            "supported_hosts",
            "host_to_vendor_platform",
            "unsupported_host_categories",
            "ubuntu_glibc_version_floor",
            "ubuntu_glibc_version_floor_source",
        },
        f"{label}.product_selections",
    )
    if (
        product.get("supported_hosts") != SUPPORTED_HOSTS
        or product.get("host_to_vendor_platform") != HOST_TO_VENDOR_PLATFORM
        or product.get("unsupported_host_categories") != UNSUPPORTED_HOST_CATEGORIES
    ):
        raise ValueError(f"{label}: product selections do not match canonical host support")
    if product.get("ubuntu_glibc_version_floor") is not None:
        raise ValueError(f"{label}: product selections must not invent an Ubuntu/glibc floor")
    if product.get("ubuntu_glibc_version_floor_source") != "no-official-floor":
        raise ValueError(f"{label}: product selections must record no-official-floor")

    manager = load_manager()
    if observations != manager.KIMI_VENDOR_DISTRIBUTION_OBSERVATIONS:
        raise ValueError(f"{label}: vendor distribution observations differ from manager")


def yaml_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def strip_yaml_comment(raw: str) -> str:
    return raw.split("#", 1)[0].strip()


def find_yaml_key(lines: list[str], *, key: str, indent: int) -> tuple[int, str]:
    prefix = " " * indent + f"{key}:"
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index, strip_yaml_comment(line[len(prefix) :])
    raise ValueError(f"{RELEASE_WORKFLOW}: missing {key}")


def find_yaml_child(
    lines: list[str], *, parent_index: int, key: str, indent: int
) -> tuple[int, str]:
    parent_indent = yaml_indent(lines[parent_index])
    prefix = " " * indent + f"{key}:"
    for index in range(parent_index + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current_indent = yaml_indent(line)
        if current_indent <= parent_indent:
            break
        if line.startswith(prefix):
            return index, strip_yaml_comment(line[len(prefix) :])
    raise ValueError(f"{RELEASE_WORKFLOW}: missing {key}")


def parse_yaml_mapping_children(lines: list[str], *, parent_index: int) -> dict[str, str]:
    parent_indent = yaml_indent(lines[parent_index])
    child_indent = parent_indent + 2
    result: dict[str, str] = {}
    for line in lines[parent_index + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current_indent = yaml_indent(line)
        if current_indent <= parent_indent:
            break
        if current_indent == child_indent and ":" in stripped:
            key, value = stripped.split(":", 1)
            result[key.strip()] = strip_yaml_comment(value)
    return result


def release_publish_job(lines: list[str]) -> int:
    jobs_index, _value = find_yaml_key(lines, key="jobs", indent=0)
    publish_index, _value = find_yaml_child(lines, parent_index=jobs_index, key="publish", indent=2)
    return publish_index


def release_workflow_paths(lines: list[str], *, with_index: int, key: str) -> list[str]:
    key_index, raw_value = find_yaml_child(lines, parent_index=with_index, key=key, indent=6)
    if raw_value in {">", ">-", "|", "|-"}:
        parts: list[str] = []
        key_indent = yaml_indent(lines[key_index])
        for line in lines[key_index + 1 :]:
            if not line.strip():
                continue
            current_indent = yaml_indent(line)
            if current_indent <= key_indent:
                break
            parts.append(line.strip())
        raw_value = " ".join(parts)
    try:
        paths = shlex.split(raw_value)
    except ValueError as exc:
        raise ValueError(f"{RELEASE_WORKFLOW}: {key} is not parseable: {exc}") from exc
    if not paths:
        raise ValueError(f"{RELEASE_WORKFLOW}: {key} must not be empty")
    return paths


def has_development_git_metadata() -> bool:
    return (ROOT / ".git").exists()


def tracked_files() -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"could not list tracked release files: {exc}") from exc
    return {entry for entry in result.stdout.split("\0") if entry}


def release_relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def validate_release_marker_free(paths: set[str], *, label: str) -> None:
    for raw in paths:
        relative = Path(raw)
        parts = relative.parts
        if not parts:
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} contains an empty path")
        if parts[0] in PRIVATE_RELEASE_ROOTS:
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} contains private root {parts[0]}")
        if any(part in PRIVATE_RELEASE_PARTS for part in parts):
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} contains generated cache path {raw}")
        if any(part.startswith(PRIVATE_RELEASE_PREFIXES) for part in parts):
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} contains temporary path {raw}")
        if relative.name.endswith(PRIVATE_RELEASE_SUFFIXES):
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} contains generated bytecode {raw}")


def cache_residue_paths(root: Path) -> list[str]:
    residue: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in PRIVATE_RELEASE_PARTS for part in relative.parts):
            residue.append(relative.as_posix())
            continue
        if any(part.startswith(PRIVATE_RELEASE_PREFIXES) for part in relative.parts):
            residue.append(relative.as_posix())
            continue
        if relative.name.endswith(PRIVATE_RELEASE_SUFFIXES):
            residue.append(relative.as_posix())
    return sorted(residue)


def validate_cache_residue_free(root: Path, *, label: str) -> None:
    residue = cache_residue_paths(root)
    if residue:
        sample = ", ".join(residue[:20])
        if len(residue) > 20:
            sample += f", ... ({len(residue)} total)"
        raise ValueError(f"{label} created generated cache residue: {sample}")


def release_tree_files() -> tuple[set[str], set[str]]:
    files: set[str] = set()
    entries: set[str] = set()
    for path in ROOT.rglob("*"):
        relative = release_relative(path)
        if relative == ".git" or relative.startswith(".git/"):
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{RELEASE_WORKFLOW}: archive tree contains symlink {relative}")
        if stat.S_ISDIR(info.st_mode):
            entries.add(relative)
            continue
        if stat.S_ISREG(info.st_mode):
            entries.add(relative)
            files.add(relative)
            continue
        raise ValueError(
            f"{RELEASE_WORKFLOW}: archive tree contains unsupported path type {relative}"
        )
    if len(entries) > 10000 or len(files) > 5000:
        raise ValueError(f"{RELEASE_WORKFLOW}: archive tree is unexpectedly large")
    return files, entries


def validate_release_file_set(files: set[str], *, label: str) -> None:
    for raw in files:
        path = ROOT / raw
        try:
            info = path.lstat()
        except FileNotFoundError:
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} path does not exist: {raw}") from None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} contains symlink {raw}")
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} path is not a regular file: {raw}")


def release_file_set() -> tuple[set[str], str]:
    if has_development_git_metadata():
        files = tracked_files()
        validate_release_file_set(files, label="tracked files")
        validate_release_marker_free(files, label="tracked files")
        return files, "tracked files"
    files, entries = release_tree_files()
    validate_release_marker_free(entries, label="archive tree")
    return files, "archive tree"


def validate_claude_instruction(files: set[str], *, root: Path | None = None) -> None:
    base = ROOT if root is None else root
    claude_dir = base / ".claude"
    try:
        claude_info = claude_dir.lstat()
    except FileNotFoundError:
        raise ValueError(f"{RELEASE_WORKFLOW}: .claude directory is missing") from None
    if stat.S_ISLNK(claude_info.st_mode):
        raise ValueError(f"{RELEASE_WORKFLOW}: .claude must be a real directory, not a symlink")
    if not stat.S_ISDIR(claude_info.st_mode):
        raise ValueError(f"{RELEASE_WORKFLOW}: .claude must be a real directory")
    claude_entries = sorted(child.name for child in claude_dir.iterdir())
    if claude_entries != ["CLAUDE.md"]:
        raise ValueError(f"{RELEASE_WORKFLOW}: .claude must contain exactly CLAUDE.md")

    if CLAUDE_INSTRUCTION_PATH not in files:
        raise ValueError(
            f"{RELEASE_WORKFLOW}: {CLAUDE_INSTRUCTION_PATH} is not covered by archive closure"
        )
    bridge = base / CLAUDE_INSTRUCTION_PATH
    try:
        bridge_info = bridge.lstat()
    except FileNotFoundError:
        raise ValueError(f"{CLAUDE_INSTRUCTION_PATH}: bridge file is missing") from None
    if stat.S_ISLNK(bridge_info.st_mode):
        raise ValueError(f"{CLAUDE_INSTRUCTION_PATH}: must be a regular file, not a symlink")
    if not stat.S_ISREG(bridge_info.st_mode):
        raise ValueError(f"{CLAUDE_INSTRUCTION_PATH}: must be a regular file")
    if bridge.read_bytes() != b"@../AGENTS.md\n":
        raise ValueError(
            f"{CLAUDE_INSTRUCTION_PATH}: must contain exactly @../AGENTS.md followed by newline"
        )

    agents = base / "AGENTS.md"
    try:
        agents_info = agents.lstat()
    except FileNotFoundError:
        raise ValueError(f"{CLAUDE_INSTRUCTION_PATH}: AGENTS.md target is missing") from None
    if stat.S_ISLNK(agents_info.st_mode):
        raise ValueError(
            f"{CLAUDE_INSTRUCTION_PATH}: AGENTS.md target must be a regular file, not a symlink"
        )
    if not stat.S_ISREG(agents_info.st_mode):
        raise ValueError(f"{CLAUDE_INSTRUCTION_PATH}: AGENTS.md target must be a regular file")


def write_valid_claude_bridge(root: Path) -> set[str]:
    (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
    claude_dir = root / ".claude"
    claude_dir.mkdir()
    (claude_dir / "CLAUDE.md").write_bytes(b"@../AGENTS.md\n")
    return {"AGENTS.md", CLAUDE_INSTRUCTION_PATH}


def expect_claude_bridge_rejected(root: Path, files: set[str], expected: str) -> None:
    try:
        validate_claude_instruction(files, root=root)
    except ValueError as exc:
        if expected not in str(exc):
            raise ValueError(
                f"Claude bridge structural check returned unstable error: {exc}"
            ) from exc
        return
    raise ValueError(f"Claude bridge structural check unexpectedly allowed {expected}")


def validate_claude_bridge_structural_regression() -> None:
    with tempfile.TemporaryDirectory(prefix=".tmp-kimicode-claude-valid-") as temp:
        root = Path(temp) / "archive"
        root.mkdir()
        files = write_valid_claude_bridge(root)
        validate_claude_instruction(files, root=root)

    def run_case(
        label: str, mutate: Any, expected: str, files_override: set[str] | None = None
    ) -> None:
        with tempfile.TemporaryDirectory(prefix=f".tmp-kimicode-claude-{label}-") as temp:
            root = Path(temp) / "archive"
            root.mkdir()
            files = write_valid_claude_bridge(root)
            mutate(root)
            expect_claude_bridge_rejected(
                root, files if files_override is None else files_override, expected
            )

    run_case(
        "extra-entry",
        lambda root: (root / ".claude" / "extra").write_text("extra\n", encoding="utf-8"),
        ".claude must contain exactly CLAUDE.md",
    )

    def replace_claude_dir_with_symlink(root: Path) -> None:
        claude_dir = root / ".claude"
        (claude_dir / "CLAUDE.md").unlink()
        claude_dir.rmdir()
        target = root / "real-claude"
        target.mkdir()
        (target / "CLAUDE.md").write_bytes(b"@../AGENTS.md\n")
        claude_dir.symlink_to(target, target_is_directory=True)

    run_case(
        "dir-symlink",
        replace_claude_dir_with_symlink,
        ".claude must be a real directory, not a symlink",
    )

    def replace_bridge_with_symlink(root: Path) -> None:
        bridge = root / ".claude" / "CLAUDE.md"
        bridge.unlink()
        bridge.symlink_to("../AGENTS.md")

    run_case(
        "bridge-symlink",
        replace_bridge_with_symlink,
        "must be a regular file, not a symlink",
    )

    def replace_bridge_with_directory(root: Path) -> None:
        bridge = root / ".claude" / "CLAUDE.md"
        bridge.unlink()
        bridge.mkdir()

    run_case(
        "bridge-directory",
        replace_bridge_with_directory,
        "must be a regular file",
    )
    run_case(
        "wrong-bytes",
        lambda root: (root / ".claude" / "CLAUDE.md").write_bytes(b"@../README.md\n"),
        "must contain exactly @../AGENTS.md followed by newline",
    )
    run_case(
        "missing-fileset",
        lambda _root: None,
        f"{CLAUDE_INSTRUCTION_PATH} is not covered by archive closure",
        files_override={"AGENTS.md"},
    )

    def replace_agents_with_symlink(root: Path) -> None:
        agents = root / "AGENTS.md"
        agents.unlink()
        target = root / "AGENTS.real.md"
        target.write_text("# Real instructions\n", encoding="utf-8")
        agents.symlink_to(target.name)

    run_case(
        "agents-symlink",
        replace_agents_with_symlink,
        "AGENTS.md target must be a regular file, not a symlink",
    )


def covered_release_files(
    paths: list[str], files: set[str], *, label: str, file_set_label: str
) -> set[str]:
    covered: set[str] = set()
    for raw in paths:
        relative = Path(raw)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} path is unsafe: {raw}")
        absolute = ROOT / relative
        try:
            info = absolute.lstat()
        except FileNotFoundError:
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} path does not exist: {raw}")
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{RELEASE_WORKFLOW}: {label} path must not be a symlink: {raw}")
        if stat.S_ISREG(info.st_mode):
            if raw not in files:
                raise ValueError(
                    f"{RELEASE_WORKFLOW}: {label} file is not in {file_set_label}: {raw}"
                )
            covered.add(raw)
            continue
        if stat.S_ISDIR(info.st_mode):
            prefix = raw.rstrip("/") + "/"
            matches = {entry for entry in files if entry.startswith(prefix)}
            if not matches:
                raise ValueError(
                    f"{RELEASE_WORKFLOW}: {label} directory has no files in {file_set_label}: {raw}"
                )
            covered.update(matches)
            continue
        raise ValueError(
            f"{RELEASE_WORKFLOW}: {label} path must be a regular file or directory: {raw}"
        )
    return covered


def validate_release_workflow(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    _permissions_index, top_permissions = find_yaml_key(lines, key="permissions", indent=0)
    if top_permissions != "{}":
        raise ValueError(f"{RELEASE_WORKFLOW}: top-level permissions must be empty")
    if '      - "[0-9]+.[0-9]+.[0-9]+"' not in text:
        raise ValueError(f"{RELEASE_WORKFLOW}: release tags must be numeric SemVer")
    publish_index = release_publish_job(lines)
    permissions_index, _value = find_yaml_child(
        lines, parent_index=publish_index, key="permissions", indent=4
    )
    if (
        parse_yaml_mapping_children(lines, parent_index=permissions_index)
        != RELEASE_CALLER_PERMISSIONS
    ):
        raise ValueError(f"{RELEASE_WORKFLOW}: publish job permissions mismatch")
    _uses_index, uses = find_yaml_child(lines, parent_index=publish_index, key="uses", indent=4)
    expected_uses = (
        f"NDDev-it-com/ci-workflows/.github/workflows/release-supply-chain.yml@{SHARED_CI_COMMIT}"
    )
    if uses != expected_uses:
        raise ValueError(f"{RELEASE_WORKFLOW}: release job must call the pinned shared workflow")
    with_index, _value = find_yaml_child(lines, parent_index=publish_index, key="with", indent=4)
    _version_index, version = find_yaml_child(
        lines, parent_index=with_index, key="version", indent=6
    )
    if version != "${{ github.ref_name }}":
        raise ValueError(f"{RELEASE_WORKFLOW}: version input must be github.ref_name")
    _package_index, package_name = find_yaml_child(
        lines, parent_index=with_index, key="package_name", indent=6
    )
    if package_name != RELEASE_PACKAGE_NAME:
        raise ValueError(f"{RELEASE_WORKFLOW}: package_name input mismatch")

    archive_paths = release_workflow_paths(lines, with_index=with_index, key="archive_paths")
    runtime_paths = release_workflow_paths(lines, with_index=with_index, key="runtime_paths")
    if tuple(archive_paths) != RELEASE_PATHS:
        raise ValueError(f"{RELEASE_WORKFLOW}: archive_paths must be explicit and canonical")
    if tuple(runtime_paths) != RELEASE_PATHS:
        raise ValueError(f"{RELEASE_WORKFLOW}: runtime_paths must be explicit and canonical")
    if not set(runtime_paths).issubset(set(archive_paths)):
        raise ValueError(f"{RELEASE_WORKFLOW}: runtime_paths must be a subset of archive_paths")
    for root in RELEASE_CONTRACT_ROOTS:
        if root not in archive_paths or root not in runtime_paths:
            raise ValueError(f"{RELEASE_WORKFLOW}: release paths missing contract root {root}")
    release_files, file_set_label = release_file_set()
    validate_claude_instruction(release_files)
    archive_covered = covered_release_files(
        archive_paths, release_files, label="archive_paths", file_set_label=file_set_label
    )
    runtime_covered = covered_release_files(
        runtime_paths, release_files, label="runtime_paths", file_set_label=file_set_label
    )
    if not runtime_covered <= archive_covered:
        missing = ", ".join(sorted(runtime_covered - archive_covered))
        raise ValueError(
            f"{RELEASE_WORKFLOW}: runtime_paths are not covered by archive_paths: {missing}"
        )
    if archive_covered != release_files:
        missing = ", ".join(sorted(release_files - archive_covered))
        raise ValueError(
            f"{RELEASE_WORKFLOW}: archive_paths do not cover {file_set_label}: {missing}"
        )
    if runtime_covered != release_files:
        missing = ", ".join(sorted(release_files - runtime_covered))
        raise ValueError(
            f"{RELEASE_WORKFLOW}: runtime_paths do not cover {file_set_label}: {missing}"
        )


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
        if filename == "release.yml":
            validate_release_workflow(path)


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
    if release.get("github_release_api_url") != GITHUB_RELEASE_API_URL:
        raise ValueError("baseline GitHub release API observation mismatch")
    if release.get("integrity") != NPM_INTEGRITY or release.get("shasum") != NPM_SHASUM:
        raise ValueError("baseline npm provenance mismatch")
    install = baseline["official_binary_install"]
    if install.get("source_family") != "code.kimi.com-binary-manifest":
        raise ValueError("official binary install must declare the code.kimi.com source family")
    if install.get("manifest_size_bytes") != CODE_KIMI_MANIFEST_SIZE_BYTES:
        raise ValueError("official binary manifest size mismatch")
    if install.get("install_script_sha256") != INSTALL_SCRIPT_SHA256:
        raise ValueError("install script digest mismatch")
    if (
        install.get("install_powershell_sha256") != INSTALL_POWERSHELL_SHA256
        or install.get("install_powershell_size_bytes") != INSTALL_POWERSHELL_SIZE_BYTES
        or install.get("install_powershell_product_supported") is not False
    ):
        raise ValueError("PowerShell install surface must remain observed and product-unsupported")
    if install.get("manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("binary manifest digest mismatch")
    platforms = install.get("platforms")
    if not isinstance(platforms, dict) or sorted(platforms) != sorted(BINARY_PLATFORMS):
        raise ValueError("official binary platform set mismatch")
    if install.get("observed_vendor_platforms") != OBSERVED_VENDOR_PLATFORMS:
        raise ValueError("baseline must preserve observed vendor platform keys separately")
    if install.get("production_supported_hosts") != SUPPORTED_HOSTS:
        raise ValueError("baseline must scope production support to canonical NDDev hosts")
    if install.get("host_to_vendor_platform") != HOST_TO_VENDOR_PLATFORM:
        raise ValueError("baseline must map supported hosts to observed vendor asset keys")
    if install.get("ubuntu_glibc_version_floor") is not None:
        raise ValueError("baseline must not invent an upstream Ubuntu/glibc version floor")
    if install.get("ubuntu_glibc_version_floor_source") != "no-official-floor":
        raise ValueError("baseline must record no-official-floor for Ubuntu/glibc")
    for key, artifact in OBSERVED_BINARY_ARTIFACTS.items():
        entry = platforms[key]
        expected = dict(artifact)
        expected["checksum"] = artifact["sha256"]
        if entry != expected:
            raise ValueError(f"official binary observation mismatch for {key}")
    validate_vendor_distribution_observations(
        baseline.get("vendor_distribution_observations"),
        "baseline vendor distribution observations",
    )
    if baseline["permission_model"].get("full_auto") != "auto with plan mode disabled":
        raise ValueError("baseline must record full-auto native auto mapping")
    if baseline["native_surfaces"].get("direct_plugin_install_state_write") is not False:
        raise ValueError("baseline must forbid direct plugin install-state writes")
    parser = baseline["runtime"].get("cli_parser")
    if (
        not isinstance(parser, dict)
        or parser.get("source_path") != "apps/kimi-code/src/cli/commands.ts"
        or parser.get("git_commit") != "8a45f10eddbb35c317047e82e567cdb59a220b4f"
        or parser.get("source_url")
        != "https://github.com/MoonshotAI/kimi-code/blob/8a45f10eddbb35c317047e82e567cdb59a220b4f/apps/kimi-code/src/cli/commands.ts"
    ):
        raise ValueError("baseline must point to the official Kimi CLI parser owner")
    unsupported = baseline.get("unsupported", {})
    if unsupported.get("windows") is not True:
        raise ValueError("baseline must mark Windows unsupported")
    for host in ("non_ubuntu_linux", "linux_musl", "unsupported_architecture"):
        if unsupported.get(host) is not True:
            raise ValueError(f"baseline must mark {host} unsupported")


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


def public_validation_doc_commands(path: Path) -> dict[int, tuple[str, ...]]:
    text = path.read_text(encoding="utf-8")
    relative = path.relative_to(ROOT)
    for forbidden in FORBIDDEN_PUBLIC_VALIDATION_COMMAND_TERMS:
        if forbidden in text:
            raise ValueError(f"{relative}: public validation docs must not publish {forbidden}")
    commands: dict[int, tuple[str, ...]] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped.startswith("python3 "):
            continue
        try:
            command = tuple(shlex.split(stripped))
        except ValueError as exc:
            raise ValueError(
                f"{relative}:{line_number}: public validation command is not parseable: {exc}"
            ) from exc
        if any(term in command for term in FORBIDDEN_PUBLIC_VALIDATION_COMMAND_TERMS):
            raise ValueError(
                f"{relative}:{line_number}: public validation command uses cache-producing compiler"
            )
        commands[line_number] = command
    return commands


def validate_documented_public_command(
    command: tuple[str, ...], relative: Path, line_number: int
) -> None:
    if len(command) < 2 or command[0] != "python3":
        raise ValueError(
            f"{relative}:{line_number}: public validation command must start with python3"
        )
    script = Path(command[1])
    if script.is_absolute() or ".." in script.parts:
        raise ValueError(
            f"{relative}:{line_number}: public validation command script path is unsafe"
        )
    script_path = ROOT / script
    if not script_path.is_file():
        raise ValueError(f"{relative}:{line_number}: public validation command script is missing")
    argv = list(command[2:])
    module = load_source_for_parse(script_path)
    parse_args = getattr(module, "parse_args", None)
    if parse_args is None:
        raise ValueError(
            f"{relative}:{line_number}: public validation command has no parse_args owner"
        )
    try:
        parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise ValueError(
                f"{relative}:{line_number}: public validation command argv is rejected"
            ) from exc


def load_source_for_parse(path: Path) -> Any:
    module_name = "_nddev_kimicode_doc_parse_" + re.sub(r"[^A-Za-z0-9_]", "_", path.as_posix())
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load {path.relative_to(ROOT)} for documented command parsing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - surfaced as validator failure.
        raise ValueError(f"could not import {path.relative_to(ROOT)}: {exc}") from exc
    return module


def validate_public_validation_docs() -> None:
    for relative in PUBLIC_VALIDATION_DOCS:
        path = ROOT / relative
        if not path.is_file():
            raise ValueError(f"missing public validation document {relative}")
        for line_number, command in public_validation_doc_commands(path).items():
            validate_documented_public_command(command, relative, line_number)


def extract_git_archive(destination: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"could not export clean git archive: {exc}") from exc
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            member_path = Path(member.name)
            if member_path.is_absolute() or any(
                part in {"", ".", ".."} for part in member_path.parts
            ):
                raise ValueError(f"git archive contains unsafe path {member.name}")
            if member.issym() or member.islnk():
                raise ValueError(f"git archive contains link {member.name}")
            output = destination / member_path
            if member.isdir():
                output.mkdir(mode=member.mode & 0o777, parents=True, exist_ok=True)
                output.chmod(member.mode & 0o777)
                continue
            if not member.isfile():
                raise ValueError(f"git archive contains unsupported entry {member.name}")
            output.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"git archive could not read {member.name}")
            with source, output.open("xb") as handle:
                shutil.copyfileobj(source, handle)
            output.chmod(member.mode & 0o777)


def validate_archive_public_commands_cache_free() -> None:
    if not has_development_git_metadata():
        return
    with tempfile.TemporaryDirectory(prefix=".tmp-kimicode-public-archive-") as temp:
        archive_root = Path(temp) / "archive"
        archive_root.mkdir()
        extract_git_archive(archive_root)
        validate_cache_residue_free(archive_root, label="clean git archive")
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPYCACHEPREFIX"] = str(Path(temp) / "pycache")
        env["RUFF_CACHE_DIR"] = str(Path(temp) / "ruff-cache")
        env.pop("PYTHONPATH", None)
        for command in CACHE_FREE_PUBLIC_COMMANDS:
            completed = subprocess.run(
                list(command),
                cwd=archive_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            if completed.returncode != 0:
                details = (completed.stderr or completed.stdout).strip()
                raise ValueError(
                    f"archive public command failed ({shlex.join(command)}): {details}"
                )
            validate_cache_residue_free(
                archive_root,
                label=f"archive public command {shlex.join(command)}",
            )


def validate_system_python_compatibility() -> None:
    system_python = Path("/usr/bin/python3")
    if not system_python.is_file():
        raise ValueError("required system Python is missing: /usr/bin/python3")
    with tempfile.TemporaryDirectory(prefix=".tmp-kimicode-system-python-") as temp:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPYCACHEPREFIX"] = str(Path(temp) / "pycache")
        env.pop("PYTHONPATH", None)
        compile_script = """
from pathlib import Path
roots = [Path("cli-tools"), Path("builder")]
for root in roots:
    for path in sorted(root.rglob("*.py"), key=lambda item: item.as_posix()):
        compile(path.read_text(encoding="utf-8"), path.as_posix(), "exec")
"""
        for command in (
            [str(system_python), "-B", "-c", compile_script],
            [
                str(system_python),
                "-B",
                str(ROOT / "cli-tools" / "nddev_kimicode.py"),
                "list",
                "--json",
            ],
        ):
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            if completed.returncode != 0:
                details = (completed.stderr or completed.stdout).strip()
                raise ValueError(
                    f"system Python compatibility command failed ({shlex.join(command)}): {details}"
                )
        validate_cache_residue_free(ROOT, label="system Python compatibility")


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
    agent_text = (ROOT / "builder" / "nddev-builder" / "agents" / "nddev-builder.md").read_text(
        encoding="utf-8"
    )
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
    if build.get("python_requires") != PYTHON_REQUIRES:
        raise ValueError("build/version.json must require Python >=3.9")
    if (
        build.get("kimi_code_cli_tested") != KIMI_VERSION
        or manifest.get("kimi_code_cli_tested") != KIMI_VERSION
    ):
        raise ValueError("tested Kimi release fields are not synchronized")
    if (
        build.get("content_setup_ids") != CONTENT_SETUPS
        or manifest.get("content_setup_ids") != CONTENT_SETUPS
    ):
        raise ValueError("content setup ids are not synchronized")
    if (
        build.get("permission_profile_ids") != PROFILES
        or manifest.get("permission_profile_ids") != PROFILES
    ):
        raise ValueError("permission profile ids are not synchronized")
    if (
        build.get("default_permission_profile") != DEFAULT_PROFILE
        or manifest.get("default_permission_profile") != DEFAULT_PROFILE
    ):
        raise ValueError("default profile must be full-auto")
    if contract.get("contract_version") != 3 or set(contract) != CONTRACT_KEYS:
        raise ValueError("contract v3 top-level keys are not exact")
    if (
        contract.get("version_ref") != "build/version.json"
        or contract.get("manifest_ref") != "build/manifest.json"
    ):
        raise ValueError("contract refs are invalid")
    setup_system = contract["setup_system"]
    if (
        setup_system.get("content_setup_ids") != CONTENT_SETUPS
        or setup_system.get("permission_profile_ids") != PROFILES
    ):
        raise ValueError("contract catalog ids are not synchronized")
    if setup_system.get("full_auto_native_permission_mode") != "auto":
        raise ValueError("contract must map full-auto to native auto")
    if setup_system.get("yolo_profile_shipped") is not False:
        raise ValueError("contract must not ship yolo")
    if (
        setup_system.get("update_command")
        != "python3 cli-tools/nddev_kimicode.py update --target /absolute/target --json"
    ):
        raise ValueError("contract must expose distinct setup update command")
    if manifest.get("setup_lifecycle") != {
        "update_command": "python3 cli-tools/nddev_kimicode.py update --target /absolute/target --json",
        "update_identity": "refreshes the installed setup/profile identity from the current public catalog",
        "update_absent_noop": False,
    }:
        raise ValueError("manifest must expose setup update lifecycle")
    if contract["safety"].get("full_auto_active_blocking_hooks") is not False:
        raise ValueError("contract must state full-auto has no active blocking hooks")
    if contract["safety"].get("launch_holds_lifecycle_lock") is not True:
        raise ValueError("contract must state launch holds the lifecycle lock")
    if contract["safety"].get("launch_uses_external_product_coordination_lock") is not True:
        raise ValueError("contract must state launch uses external product coordination")
    if contract["safety"].get("launch_uses_external_target_bound_lifecycle_lock") is not True:
        raise ValueError("contract must state launch uses an external target-bound lifecycle lock")
    if contract["safety"].get("launch_keeps_external_lock_file_persistent") is not True:
        raise ValueError("contract must state external lifecycle lock files are persistent")
    if contract["safety"].get("external_anchor_publication_no_replace") is not True:
        raise ValueError("contract must state external anchors use no-replace publication")
    if contract["safety"].get("external_anchor_final_path_commit_point") is not True:
        raise ValueError("contract must state final-path anchor publication is the commit point")
    if contract["safety"].get("external_product_anchor_monotonic") is not True:
        raise ValueError("contract must state product anchors are monotonic")
    if contract["safety"].get("external_target_anchor_monotonic") is not True:
        raise ValueError("contract must state target anchors are monotonic")
    if contract["safety"].get("read_only_commands_do_not_create_external_anchors") is not True:
        raise ValueError("contract must state read-only commands do not create external anchors")
    if contract["safety"].get("read_only_cold_no_anchor_double_check") is not True:
        raise ValueError("contract must state cold read-only double-checks anchor absence")
    cleanup_safety_keys = (
        "cleanup_journal_two_phase_no_replace",
        "cleanup_journal_path_safe_relative_tombstones",
        "cleanup_pending_read_only_report_only",
        "cleanup_pending_malformed_state_fails_closed",
        "cleanup_pending_mutations_drain_first",
        "cleanup_pending_noop_is_not_true_noop",
    )
    for key in cleanup_safety_keys:
        if contract["safety"].get(key) is not True:
            raise ValueError(f"contract must state cleanup journal safety key: {key}")
    if contract["safety"].get("launch_keeps_internal_lock_file_persistent") is not True:
        raise ValueError("contract must state internal lifecycle lock files are persistent")
    if contract["safety"].get("launch_protects_internal_lock_directory_while_held") is not True:
        raise ValueError(
            "contract must state internal lifecycle lock directory is protected while held"
        )
    if contract["safety"].get("launch_uses_stable_fcntl_flock") is not True:
        raise ValueError("contract must state launch uses a stable fcntl flock")
    if contract["safety"].get("launch_preserves_mutable_runtime_state_paths") is not True:
        raise ValueError("contract must state launch preserves mutable runtime state paths")
    if (
        contract["safety"].get("launch_protects_dedicated_lock_and_artifact_directories")
        is not True
    ):
        raise ValueError(
            "contract must state launch protects only dedicated lock and artifact directories"
        )
    if contract["safety"].get("launch_revalidates_executable_before_handoff") is not True:
        raise ValueError("contract must state launch revalidates the executable before handoff")
    runtime_launch = contract["runtime_launch"]
    if runtime_launch.get("pre_login_supported") is not True:
        raise ValueError("contract must keep pre-login launch supported")
    if "child process completion" not in runtime_launch.get("lifecycle_lock_scope", ""):
        raise ValueError("contract must document launch lock scope through child completion")
    if "managed target root" not in runtime_launch.get("mutable_runtime_paths", ""):
        raise ValueError("contract must document writable runtime state paths")
    if "only the dedicated lock directory" not in runtime_launch.get(
        "pre_handoff_executable_revalidation", ""
    ):
        raise ValueError("contract must document narrow launch path protection")
    if "pinned official-binary digest" not in runtime_launch.get(
        "pre_handoff_executable_revalidation", ""
    ):
        raise ValueError("contract must document pinned digest revalidation before launch handoff")
    if "latest revalidated path handoff" not in runtime_launch.get(
        "portable_handoff_mechanism", ""
    ):
        raise ValueError("contract must document portable latest-path handoff")
    if "exact-inode fd execution is not the portable macOS contract" not in runtime_launch.get(
        "portable_handoff_mechanism", ""
    ):
        raise ValueError("contract must not overclaim portable exact-inode execution")
    if "product handoff" not in runtime_launch.get("lifecycle_lock_scope", "").lower():
        raise ValueError("contract must document external lock acquisition order")
    if "fcntl.flock" not in runtime_launch.get("lifecycle_lock_mechanism", ""):
        raise ValueError("contract must document the stable flock mechanism")
    if "fixed validated product/UID 0700 system temp root" not in runtime_launch.get(
        "lifecycle_lock_mechanism", ""
    ):
        raise ValueError("contract must document fixed bootstrap root")
    mechanism = runtime_launch.get("lifecycle_lock_mechanism", "")
    for required in (
        "monotonic 0600 external product anchor named global.lock",
        "monotonic 0600 canonical target anchor",
        "complete fsynced no-replace binding publication",
        "final-path visibility is the rollback commit point",
        "parent-directory sync completes crash durability",
        "never truncated, rebound, replaced, or unlinked",
        "Read-only status, plan, and software-status do not create anchors",
        "immutable complete cleanup journal",
        "relative tombstone names",
        "no-replace publication",
        "read-only report-only cleanup_pending state",
        "malformed-state fail-closed",
        "mutation-only drain",
    ):
        if required not in mechanism:
            raise ValueError(f"contract must document lifecycle mechanism: {required}")
    if "restored to 0700" not in runtime_launch.get("lifecycle_lock_mechanism", ""):
        raise ValueError("contract must document internal lock directory restoration")
    if "dedicated target-local lock directory" not in runtime_launch.get(
        "lifecycle_lock_mechanism", ""
    ):
        raise ValueError("contract must document the dedicated lock directory")
    if "same-UID" not in runtime_launch.get("same_uid_tamper_boundary", ""):
        raise ValueError("contract must document the same-UID tamper boundary")
    same_uid_boundary = runtime_launch.get("same_uid_tamper_boundary", "")
    for required in (
        "No OS sandbox or independent trust anchor is claimed",
        "target entrypoint replacement",
        "not authenticity against a same-UID writer",
    ):
        if required not in same_uid_boundary:
            raise ValueError(f"contract must state same-UID boundary: {required}")
    for forbidden in (
        "executable os.replace swaps are denied",
        "same-UID chmod protection",
    ):
        if forbidden in same_uid_boundary:
            raise ValueError(f"contract must not overclaim same-UID launch protection: {forbidden}")
    if manifest.get("runtime_launch") != {
        "external_product_coordination_lock": True,
        "external_target_bound_lifecycle_lock": True,
        "external_product_anchor_persistent_inode": True,
        "external_target_anchor_persistent_inode": True,
        "external_lock_persistent_inode": True,
        "external_lock_fixed_system_bootstrap_root": True,
        "external_anchor_no_replace_publication": True,
        "external_anchor_final_path_commit_point": True,
        "external_anchor_hardlink_publication": False,
        "read_only_external_anchor_no_create": True,
        "read_only_cold_no_anchor_double_check": True,
        "different_targets_concurrent_after_product_handoff": True,
        "cleanup_journal_no_replace_publication": True,
        "cleanup_journal_relative_tombstones": True,
        "cleanup_pending_read_only_report_only": True,
        "cleanup_pending_malformed_state_fails_closed": True,
        "cleanup_pending_mutations_drain_first": True,
        "cleanup_journal_hardlink_alias_recovery": True,
        "internal_lock_persistent_inode": True,
        "internal_lock_directory_protected_while_held": True,
        "holds_lifecycle_lock_through_child": True,
        "stable_fcntl_flock_lifecycle_lock": True,
        "latest_revalidated_path_handoff": True,
        "mutable_runtime_state_writable_during_launch": True,
        "pre_handoff_executable_revalidation": True,
        "exact_inode_exec": False,
        "same_uid_tamper_authenticity": False,
        "runtime_dirs_private": True,
    }:
        raise ValueError("manifest must expose launch lock and executable revalidation facts")
    software = contract["software_lifecycle"]
    if (
        software.get("channel") != "official-binary"
        or software.get("manifest_sha256") != MANIFEST_SHA256
    ):
        raise ValueError("contract software lifecycle must use official binary manifest")
    if software.get("status_executes_binary") is not False:
        raise ValueError("software status must remain read-only")
    if (
        software.get("remove_command")
        != "python3 cli-tools/nddev_kimicode.py remove-cli --target /absolute/target --json"
    ):
        raise ValueError("contract must expose remove-cli")
    if software.get("remove_absent_noop") is not True:
        raise ValueError("contract must declare deterministic absent remove-cli no-op")
    if "only target-owned software paths" not in software.get("remove_precondition", ""):
        raise ValueError("contract must scope remove-cli to target-owned software paths")
    if manifest["software_install"].get("remove_absent_noop") is not True:
        raise ValueError("manifest must expose deterministic absent remove-cli no-op")
    expected_powershell = {
        "powershell_script_url": "https://code.kimi.com/kimi-code/install.ps1",
        "powershell_script_sha256": INSTALL_POWERSHELL_SHA256,
        "powershell_script_size_bytes": INSTALL_POWERSHELL_SIZE_BYTES,
        "product_supported": False,
    }
    if (runtime_compatibility := contract["runtime_compatibility"]).get(
        "official_windows_install_surface"
    ) != expected_powershell:
        raise ValueError("contract must preserve product-unsupported PowerShell surface")
    if manifest["software_install"].get("official_windows_install_surface") != expected_powershell:
        raise ValueError("manifest must preserve product-unsupported PowerShell surface")
    validate_vendor_distribution_observations(
        runtime_compatibility.get("vendor_distribution_observations"),
        "contract vendor distribution observations",
    )
    validate_vendor_distribution_observations(
        manifest["software_install"].get("vendor_distribution_observations"),
        "manifest vendor distribution observations",
    )
    if runtime_compatibility.get("observed_vendor_platforms") != OBSERVED_VENDOR_PLATFORMS:
        raise ValueError("contract must preserve observed vendor platform keys")
    if runtime_compatibility.get("observed_vendor_artifacts") != OBSERVED_BINARY_ARTIFACTS:
        raise ValueError("contract must preserve observed vendor artifact observations")
    if runtime_compatibility.get("supported_hosts") != SUPPORTED_HOSTS:
        raise ValueError("contract must support only canonical NDDev hosts")
    if runtime_compatibility.get("host_to_vendor_platform") != HOST_TO_VENDOR_PLATFORM:
        raise ValueError("contract must map supported hosts to observed vendor asset keys")
    if runtime_compatibility.get("unsupported_host_categories") != UNSUPPORTED_HOST_CATEGORIES:
        raise ValueError("contract unsupported host categories mismatch")
    if runtime_compatibility.get("ubuntu_glibc_version_floor") is not None:
        raise ValueError("contract must not invent an upstream Ubuntu/glibc version floor")
    if runtime_compatibility.get("ubuntu_glibc_version_floor_source") != "no-official-floor":
        raise ValueError("contract must record no-official-floor for Ubuntu/glibc")
    if runtime_compatibility.get("windows_supported") is not False:
        raise ValueError("Windows must be unsupported")
    if runtime_compatibility.get("generic_linux_supported") is not False:
        raise ValueError("generic Linux must not be supported")
    for host in ("non_ubuntu_linux_supported", "linux_musl_supported"):
        if runtime_compatibility.get(host) is not False:
            raise ValueError(f"{host} must be unsupported")
    software_runtime = manifest["software_runtime"]
    if software_runtime.get("observed_vendor_platforms") != OBSERVED_VENDOR_PLATFORMS:
        raise ValueError("manifest must preserve observed vendor platform keys")
    if software_runtime.get("observed_vendor_artifacts") != OBSERVED_BINARY_ARTIFACTS:
        raise ValueError("manifest must preserve observed vendor artifact observations")
    if software_runtime.get("supported_hosts") != SUPPORTED_HOSTS:
        raise ValueError("manifest must support only canonical NDDev hosts")
    if software_runtime.get("host_to_vendor_platform") != HOST_TO_VENDOR_PLATFORM:
        raise ValueError("manifest must map supported hosts to observed vendor asset keys")
    if software_runtime.get("unsupported_host_categories") != UNSUPPORTED_HOST_CATEGORIES:
        raise ValueError("manifest unsupported host categories mismatch")
    if software_runtime.get("ubuntu_glibc_version_floor") is not None:
        raise ValueError("manifest must not invent an upstream Ubuntu/glibc version floor")
    if software_runtime.get("ubuntu_glibc_version_floor_source") != "no-official-floor":
        raise ValueError("manifest must record no-official-floor for Ubuntu/glibc")
    if "supported_platforms" in software_runtime:
        raise ValueError("manifest must not call observed linux assets supported platforms")
    validate_baseline(baseline)


def validate_runtime_contract_sources() -> None:
    manager = load_manager()
    manager_text = (ROOT / "cli-tools" / "nddev_kimicode.py").read_text(encoding="utf-8")
    if manager.CLEANUP_JOURNAL_MAX_BYTES != manager.METADATA_MAX_BYTES:
        raise ValueError("cleanup journal byte bound must share the metadata size bound")
    for forbidden in (
        "NDDEV_KIMICODE_TEST",
        "ENABLE_TEST_OVERRIDES",
        "NDDEV_KIMICODE_BOOTSTRAP_ROOT",
        "NDDEV_KIMICODE_LOCK_ROOT",
        "KIMI_CODE_BOOTSTRAP_ROOT",
    ):
        if forbidden in manager_text:
            raise ValueError("manager must not expose public test environment switches")
    fixed_start = manager_text.index("def fixed_system_temp_root")
    fixed_end = manager_text.index("def ensure_external_lock_root")
    fixed_source = manager_text[fixed_start:fixed_end]
    for required in ('Path("/private/tmp")', 'Path("/tmp")', "stat.S_ISVTX"):
        if required not in fixed_source:
            raise ValueError(f"manager system bootstrap root resolver is missing {required}")
    for forbidden in ("tempfile.gettempdir", "os.environ"):
        if forbidden in fixed_source:
            raise ValueError("manager bootstrap root must not derive from ambient runtime state")
    for required in (
        "lock_mode: int = fcntl.LOCK_EX",
        "fcntl.flock(fd, lock_mode | fcntl.LOCK_NB)",
        'kind="external-bootstrap"',
        'kind="external-product"',
        'kind="target-internal"',
        "EXTERNAL_LOCK_NAMESPACE",
        "EXTERNAL_PRODUCT_ANCHOR_NAME",
        "RENAME_EXCL_DARWIN",
        "RENAME_NOREPLACE_LINUX",
        "ensure_external_lock_root()",
        "external_product_anchor_path(external_lock_root)",
        "acquire_product_coordination_lock(",
        "release_product_coordination_lock(releasing_product_fd)",
        "acquire_existing_lock_file(",
        "publish_missing_lock_file(",
        "rename_no_replace(stage, path, label)",
        "published = True",
        "if info.st_nlink != 1",
        "protect_internal_lock_parent(lock_parent)",
        "validate_lock_binding",
        "binding is malformed",
        "current.st_dev != info.st_dev or current.st_ino != info.st_ino",
        "external_lock_root=external_lock_root",
        "canonicalize_target_under_product_lock(target)",
        "release_lock_file(releasing_bootstrap_fd, bootstrap_path, remove_file=False)",
        "release_lock_file(releasing_internal_fd, internal_path, remove_file=False)",
        "os.fchmod(fd, 0o500)",
        "lock_path(target).parent",
        "with protected_launch_path(invocation.target):",
        "expected_digest=invocation.expected_entrypoint_digest",
        "host_platform_key = require_supported_product_host().vendor_platform_key",
        "launch requires current target-owned Kimi Code binary: host platform",
        "is_current_owner(opened)",
        "opened.st_dev != info.st_dev or opened.st_ino != info.st_ino",
        "target-owned Kimi Code entrypoint digest does not match pinned binary",
    ):
        if required not in manager_text:
            raise ValueError(f"manager is missing launch hardening fragment: {required}")
    for forbidden in (
        "os.link(",
        "publish_lock_payload",
        "os.ftruncate(fd, 0)",
    ):
        if (
            forbidden
            in manager_text[
                manager_text.index("def validate_lock_info") : manager_text.index(
                    "def protect_internal_lock_parent"
                )
            ]
        ):
            raise ValueError(
                f"manager must not use unsafe external anchor publication: {forbidden}"
            )
    cleanup_start = manager_text.index("def cleanup_journal_dir")
    cleanup_end = manager_text.index("def require_tree_entry_identity")
    cleanup_source = manager_text[cleanup_start:cleanup_end]
    for required in (
        "CLEANUP_JOURNAL_MAX_BYTES = METADATA_MAX_BYTES",
        "CLEANUP_INTENT_MAX_BYTES",
        "class CleanupSourceAdmission",
        "def cleanup_operation_kind_for_source",
        "def cleanup_source_admission",
        "def validate_cleanup_source_binding",
        "def cleanup_parent_binding",
        'validate_cleanup_parent_binding(target, intent.get("cleanup_parent"))',
        '"operation_kind"',
        '"parent_st_dev"',
        '"parent_st_ino"',
        "cleanup source is not a declared machine-generated object",
        "def serialized_cleanup_journal_bytes",
        "def serialized_cleanup_intent_bytes",
        "def build_cleanup_journal_for_entries",
        "def build_cleanup_intent",
        "def recover_cleanup_intent_for_mutation",
        "len(data) > CLEANUP_JOURNAL_MAX_BYTES",
        "len(serialized_journal) > CLEANUP_JOURNAL_MAX_BYTES",
    ):
        if required not in manager_text:
            raise ValueError(
                f"cleanup journal implementation is missing bound fragment: {required}"
            )
    for required in (
        "relative_name",
        "cleanup_journal_stage_alias_pattern",
        "read_final_cleanup_journal_json(target)",
        "stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE",
        "info.st_nlink != 1",
        "opened.st_nlink != 1",
        "recover_cleanup_journal_publication_alias_for_mutation(target)",
        "read_cleanup_journal_with_publication_alias",
        "rename_no_replace(stage, journal_path, CLEANUP_JOURNAL_NAME)",
        "CleanupJournalPublishResult(published=True, cleanup_pending=True)",
        "unknown_entries = set(entries) - {CLEANUP_JOURNAL_NAME} - seen",
        "cleanup_pending_metadata",
        "journal: dict[str, Any]",
        "serialized_journal: bytes",
        "intent: dict[str, Any]",
        "serialized_intent: bytes",
        "write_cleanup_journal_stage(stage, serialized_journal)",
        "publish_cleanup_intent(target, intent, serialized_intent)",
        "remove_cleanup_intent_file(target)",
    ):
        if required not in cleanup_source:
            raise ValueError(f"cleanup journal implementation is missing {required}")
    for forbidden in (
        '"path": str(',
        '"absolute_path"',
        "os.replace(stage, journal_path)",
        "atomic_write(journal_path",
        "fragment in path.name",
    ):
        if forbidden in cleanup_source:
            raise ValueError(f"cleanup journal must not publish unsafe path state: {forbidden}")
    write_stage_source = manager_text[
        manager_text.index("def write_cleanup_journal_stage") : manager_text.index(
            "def publish_cleanup_journal"
        )
    ]
    if "canonical_json(" in write_stage_source:
        raise ValueError("cleanup journal stage writer must use prebuilt bounded bytes")
    finish_source = manager_text[
        manager_text.index("def finish_cleanup_journal") : manager_text.index(
            "def require_tree_entry_identity"
        )
    ]
    if (
        "promotion.journal" not in finish_source
        or "promotion.serialized_journal" not in finish_source
        or "remove_cleanup_intent_file(target)" not in finish_source
    ):
        raise ValueError("cleanup journal publication must use the prebuilt bounded payload")
    write_setup_source = manager_text[
        manager_text.index("def write_setup") : manager_text.index("def restore_backup")
    ]
    update_setup_source = manager_text[
        manager_text.index("def update_setup") : manager_text.index("def _plan_payload_locked")
    ]
    for label, source in (
        ("write_setup", write_setup_source),
        ("update_setup", update_setup_source),
    ):
        if "backup_cleanup_sources = backup_result.cleanup_sources" not in source:
            raise ValueError(f"{label} must defer backup retirement cleanup")
        if source.index("file_transaction.commit()") > source.index(
            "finish_cleanup_journal(target, list(backup_cleanup_sources))"
        ):
            raise ValueError(f"{label} must commit file transaction before backup cleanup")
    readonly_status_source = manager_text[
        manager_text.index("def _status_payload_locked") : manager_text.index("def status_payload")
    ]
    if "cleanup_pending_metadata(target)" not in readonly_status_source:
        raise ValueError("status must report cleanup_pending without draining")
    if 'software["current"] and not cleanup_metadata' not in readonly_status_source:
        raise ValueError("status launch_allowed must be false while cleanup is pending")
    readonly_software_source = manager_text[
        manager_text.index("def _software_status_payload_locked") : manager_text.index(
            "def software_status_payload"
        )
    ]
    if "cleanup_pending_metadata(target)" not in readonly_software_source:
        raise ValueError("software-status must report cleanup_pending without draining")
    protected_start = manager_text.index("def protected_launch_path")
    protected_end = manager_text.index("def revalidate_launch_executable")
    protected_source = manager_text[protected_start:protected_end]
    if "        target,\n" in protected_source:
        raise ValueError("launch protection must not chmod the managed target root")
    canonical_start = manager_text.index("def lock_canonical_target")
    canonical_end = manager_text.index("def canonicalize_target_under_product_lock")
    canonical_source = manager_text[canonical_start:canonical_end]
    for forbidden in ("resolve(", "stat_existing(", "reject_symlink_ancestors("):
        if forbidden in canonical_source:
            raise ValueError("lock canonical target must remain lexical before external locking")
    external_start = manager_text.index("def external_lifecycle_lock")
    external_end = manager_text.index("def target_lock")
    external_source = manager_text[external_start:external_end]
    product_index = external_source.index("product_fd = acquire_product_coordination_lock(")
    canonicalize_index = external_source.index(
        "canonical_target_path = canonicalize_target_under_product_lock(target)"
    )
    bootstrap_index = external_source.index("bootstrap_fd = acquire_lock_file(")
    if not product_index < canonicalize_index < bootstrap_index:
        raise ValueError(
            "external lifecycle lock must product-coordinate before canonical target locking"
        )
    readonly_source = manager_text[
        manager_text.index("def readonly_external_lifecycle_lock") : manager_text.index(
            "def target_lock"
        )
    ]
    for required in (
        "publish_missing=False",
        "lock_mode=fcntl.LOCK_SH",
        "RetryReadOnlyLifecycle",
        "stat_existing(\n                external_product_anchor_path(external_lock_root)",
    ):
        if required not in readonly_source:
            raise ValueError(f"read-only lifecycle path is missing {required}")
    target_lock_start = manager_text.index("def target_lock")
    target_lock_end = manager_text.index("def safe_target_path")
    target_lock_source = manager_text[target_lock_start:target_lock_end]
    if "with external_lifecycle_lock(target)" not in target_lock_source:
        raise ValueError("target lock must acquire external lifecycle coordination first")
    external_index = target_lock_source.index("with external_lifecycle_lock(target)")
    for fragment in (
        "target = Path(canonical_target)",
        'stat_existing(target.parent, "target parent")',
        'stat_existing(target, "target")',
        "snapshot_tree(\n                    lock_parent_path(target)",
    ):
        if fragment not in target_lock_source:
            raise ValueError(f"target lock is missing ordered fragment: {fragment}")
        if target_lock_source.index(fragment) < external_index:
            raise ValueError("target filesystem inspection precedes external lifecycle lock")
    status_start = manager_text.index("def status_payload")
    status_end = manager_text.index("def stamp_managed_paths")
    status_source = manager_text[status_start:status_end]
    if "run_under_readonly_external_lifecycle(target, _status_payload_locked)" not in status_source:
        raise ValueError("status must read target state under external lifecycle coordination")
    software_start = manager_text.index("def software_status_payload")
    software_end = manager_text.index("def parse_os_release")
    software_source = manager_text[software_start:software_end]
    if (
        "run_under_readonly_external_lifecycle(target, _software_status_payload_locked)"
        not in software_source
    ):
        raise ValueError(
            "software-status must read target state under external lifecycle coordination"
        )
    plan_start = manager_text.index("def plan_payload")
    plan_end = manager_text.index("def software_root")
    plan_source = manager_text[plan_start:plan_end]
    if "run_under_readonly_external_lifecycle(" not in plan_source:
        raise ValueError("plan must read target state under external lifecycle coordination")
    install_start = manager_text.index("def install_or_update_software")
    install_end = manager_text.index("def verify_removed_software_postcondition")
    install_source = manager_text[install_start:install_end]
    if "path_exists_no_follow(target)" in install_source:
        raise ValueError("software install/update must not inspect target before target_lock")
    if install_source.index("with target_lock(target") > install_source.index(
        "_software_status_payload_locked(target)"
    ):
        raise ValueError("software install/update status must run after target_lock acquisition")
    software_commit_start = manager_text.index("def commit_software_transactions")
    software_commit_end = manager_text.index("def rollback_software_transactions")
    software_commit_source = manager_text[software_commit_start:software_commit_end]
    for required in (
        "software_cleanup_tombstones(",
        "stage_root=stage_root",
        "return finish_cleanup_journal(",
    ):
        if required not in software_commit_source:
            raise ValueError(f"software cleanup commit is missing {required}")
    if "commit_software_transactions(" not in install_source:
        raise ValueError("software install/update must use coordinated cleanup commit")
    if install_source.index("verify_installed_software_postcondition(") > install_source.index(
        "commit_software_transactions("
    ):
        raise ValueError("software cleanup commit must follow installed-state postcondition")
    remove_start = manager_text.index("def remove_software")
    remove_end = manager_text.index("def reject_managed_launch_overrides")
    remove_source = manager_text[remove_start:remove_end]
    if remove_source.index("with target_lock(target") > remove_source.index(
        "_software_status_payload_locked(target)"
    ):
        raise ValueError("remove-cli status must run after target_lock acquisition")
    if "commit_software_transactions(" not in remove_source:
        raise ValueError("remove-cli must use coordinated cleanup commit")
    if remove_source.index("verify_removed_software_postcondition(target)") > remove_source.index(
        "commit_software_transactions("
    ):
        raise ValueError("remove-cli cleanup commit must follow removed-state postcondition")
    dispatch_start = manager_text.index("def dispatch")
    dispatch_end = manager_text.index("def main")
    dispatch_source = manager_text[dispatch_start:dispatch_end]
    switch_source = dispatch_source[
        dispatch_source.index('if args.command == "switch-profile"') : dispatch_source.index(
            'if args.command == "migrate"'
        )
    ]
    if "read_stamp(target)" in switch_source:
        raise ValueError("switch-profile dispatch must not read target state before lifecycle lock")
    prepare_start = manager_text.index("def prepare_launch_invocation(")
    prepare_end = manager_text.index("def launch(")
    prepare_source = manager_text[prepare_start:prepare_end]
    if prepare_source.index(
        "host_platform_key = require_supported_product_host().vendor_platform_key"
    ) > prepare_source.index("with target_lock(target):"):
        raise ValueError(
            "prepare launch must reject unsupported hosts before acquiring lifecycle locks"
        )
    launch_start = manager_text.index("def launch(")
    launch_end = manager_text.index("def parse_args")
    launch_source = manager_text[launch_start:launch_end]
    if launch_source.index(
        "host_platform_key = require_supported_product_host().vendor_platform_key"
    ) > launch_source.index("with target_lock(target):"):
        raise ValueError("launch must reject unsupported hosts before acquiring lifecycle locks")
    for label, source in (("prepare launch", prepare_source), ("launch", launch_source)):
        if "drain_cleanup_journal(target)" not in source:
            raise ValueError(f"{label} must drain cleanup before persistent launch state")
        if source.index("drain_cleanup_journal(target)") > source.index(
            "prepare_launch_invocation_locked("
        ):
            raise ValueError(f"{label} must drain cleanup before launch preparation")



def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    validate_catalog()
    validate_metadata()
    validate_builder_toolkit()
    validate_public_validation_docs()
    validate_system_python_compatibility()
    validate_archive_public_commands_cache_free()
    validate_runtime_contract_sources()
    validate_workflows()
    validate_claude_bridge_structural_regression()
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
