#!/usr/bin/env python3
"""Validate public nddev-kimicode-app release contracts."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
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


def find_yaml_child(lines: list[str], *, parent_index: int, key: str, indent: int) -> tuple[int, str]:
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
        raise ValueError(f"{RELEASE_WORKFLOW}: archive tree contains unsupported path type {relative}")
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
        raise ValueError(f"{RELEASE_WORKFLOW}: {CLAUDE_INSTRUCTION_PATH} is not covered by archive closure")
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
        raise ValueError(f"{CLAUDE_INSTRUCTION_PATH}: must contain exactly @../AGENTS.md followed by newline")

    agents = base / "AGENTS.md"
    try:
        agents_info = agents.lstat()
    except FileNotFoundError:
        raise ValueError(f"{CLAUDE_INSTRUCTION_PATH}: AGENTS.md target is missing") from None
    if stat.S_ISLNK(agents_info.st_mode):
        raise ValueError(f"{CLAUDE_INSTRUCTION_PATH}: AGENTS.md target must be a regular file, not a symlink")
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
            raise ValueError(f"Claude bridge structural check returned unstable error: {exc}") from exc
        return
    raise ValueError(f"Claude bridge structural check unexpectedly allowed {expected}")


def validate_claude_bridge_structural_regression() -> None:
    with tempfile.TemporaryDirectory(prefix=".tmp-kimicode-claude-valid-") as temp:
        root = Path(temp) / "archive"
        root.mkdir()
        files = write_valid_claude_bridge(root)
        validate_claude_instruction(files, root=root)

    def run_case(label: str, mutate: Any, expected: str, files_override: set[str] | None = None) -> None:
        with tempfile.TemporaryDirectory(prefix=f".tmp-kimicode-claude-{label}-") as temp:
            root = Path(temp) / "archive"
            root.mkdir()
            files = write_valid_claude_bridge(root)
            mutate(root)
            expect_claude_bridge_rejected(root, files if files_override is None else files_override, expected)

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


def covered_release_files(paths: list[str], files: set[str], *, label: str, file_set_label: str) -> set[str]:
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
                raise ValueError(f"{RELEASE_WORKFLOW}: {label} file is not in {file_set_label}: {raw}")
            covered.add(raw)
            continue
        if stat.S_ISDIR(info.st_mode):
            prefix = raw.rstrip("/") + "/"
            matches = {entry for entry in files if entry.startswith(prefix)}
            if not matches:
                raise ValueError(f"{RELEASE_WORKFLOW}: {label} directory has no files in {file_set_label}: {raw}")
            covered.update(matches)
            continue
        raise ValueError(f"{RELEASE_WORKFLOW}: {label} path must be a regular file or directory: {raw}")
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
    permissions_index, _value = find_yaml_child(lines, parent_index=publish_index, key="permissions", indent=4)
    if parse_yaml_mapping_children(lines, parent_index=permissions_index) != RELEASE_CALLER_PERMISSIONS:
        raise ValueError(f"{RELEASE_WORKFLOW}: publish job permissions mismatch")
    _uses_index, uses = find_yaml_child(lines, parent_index=publish_index, key="uses", indent=4)
    expected_uses = (
        f"NDDev-it-com/ci-workflows/.github/workflows/release-supply-chain.yml@{SHARED_CI_COMMIT}"
    )
    if uses != expected_uses:
        raise ValueError(f"{RELEASE_WORKFLOW}: release job must call the pinned shared workflow")
    with_index, _value = find_yaml_child(lines, parent_index=publish_index, key="with", indent=4)
    _version_index, version = find_yaml_child(lines, parent_index=with_index, key="version", indent=6)
    if version != "${{ github.ref_name }}":
        raise ValueError(f"{RELEASE_WORKFLOW}: version input must be github.ref_name")
    _package_index, package_name = find_yaml_child(lines, parent_index=with_index, key="package_name", indent=6)
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
    archive_covered = covered_release_files(archive_paths, release_files, label="archive_paths", file_set_label=file_set_label)
    runtime_covered = covered_release_files(runtime_paths, release_files, label="runtime_paths", file_set_label=file_set_label)
    if not runtime_covered <= archive_covered:
        missing = ", ".join(sorted(runtime_covered - archive_covered))
        raise ValueError(f"{RELEASE_WORKFLOW}: runtime_paths are not covered by archive_paths: {missing}")
    if archive_covered != release_files:
        missing = ", ".join(sorted(release_files - archive_covered))
        raise ValueError(f"{RELEASE_WORKFLOW}: archive_paths do not cover {file_set_label}: {missing}")
    if runtime_covered != release_files:
        missing = ", ".join(sorted(release_files - runtime_covered))
        raise ValueError(f"{RELEASE_WORKFLOW}: runtime_paths do not cover {file_set_label}: {missing}")


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
    parser = baseline["runtime"].get("cli_parser")
    if (
        not isinstance(parser, dict)
        or parser.get("source_path") != "apps/kimi-code/src/cli/commands.ts"
        or parser.get("git_commit") != "8a45f10eddbb35c317047e82e567cdb59a220b4f"
        or parser.get("source_url")
        != "https://github.com/MoonshotAI/kimi-code/blob/8a45f10eddbb35c317047e82e567cdb59a220b4f/apps/kimi-code/src/cli/commands.ts"
    ):
        raise ValueError("baseline must point to the official Kimi CLI parser owner")
    grammar = baseline["runtime"].get("native_cli_grammar")
    if not isinstance(grammar, dict):
        raise ValueError("baseline must record the native Kimi CLI grammar")
    if grammar.get("source_url") != "https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command.html":
        raise ValueError("baseline native CLI grammar must point to the official Kimi command reference")
    if grammar.get("short_value_flags") != ["-S", "-m", "-p", "-r"]:
        raise ValueError("baseline native CLI short value flags are out of sync")
    if grammar.get("short_boolean_flags") != ["-V", "-h", "-c", "-y"]:
        raise ValueError("baseline native CLI boolean short flags are out of sync")
    if grammar.get("workspace_expansion_flags") != ["--add-dir"]:
        raise ValueError("baseline native CLI workspace expansion flags are out of sync")
    if grammar.get("hidden_aliases") != {"-r": "--session", "--auto-approve": "--yolo", "--yes": "--yolo"}:
        raise ValueError("baseline native CLI hidden aliases are out of sync")
    if grammar.get("unsupported_short_flags") != ["-C"]:
        raise ValueError("baseline native CLI unsupported short flags are out of sync")
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
    if contract["safety"].get("launch_holds_lifecycle_lock") is not True:
        raise ValueError("contract must state launch holds the lifecycle lock")
    if contract["safety"].get("launch_uses_external_product_lifecycle_lock") is not True:
        raise ValueError("contract must state launch uses an external product lifecycle lock")
    if contract["safety"].get("launch_uses_external_target_bound_lifecycle_lock") is not True:
        raise ValueError("contract must state launch uses an external target-bound lifecycle lock")
    if contract["safety"].get("launch_keeps_external_lock_file_persistent") is not True:
        raise ValueError("contract must state external lifecycle lock files are persistent")
    if contract["safety"].get("launch_keeps_internal_lock_file_persistent") is not True:
        raise ValueError("contract must state internal lifecycle lock files are persistent")
    if contract["safety"].get("launch_protects_internal_lock_directory_while_held") is not True:
        raise ValueError("contract must state internal lifecycle lock directory is protected while held")
    if contract["safety"].get("launch_uses_stable_fcntl_flock") is not True:
        raise ValueError("contract must state launch uses a stable fcntl flock")
    if contract["safety"].get("launch_preserves_mutable_runtime_state_paths") is not True:
        raise ValueError("contract must state launch preserves mutable runtime state paths")
    if contract["safety"].get("launch_protects_dedicated_lock_and_artifact_directories") is not True:
        raise ValueError("contract must state launch protects only dedicated lock and artifact directories")
    if contract["safety"].get("launch_revalidates_executable_before_handoff") is not True:
        raise ValueError("contract must state launch revalidates the executable before handoff")
    runtime_launch = contract["runtime_launch"]
    if runtime_launch.get("pre_login_supported") is not True:
        raise ValueError("contract must keep pre-login launch supported")
    if "child process completion" not in runtime_launch.get("lifecycle_lock_scope", ""):
        raise ValueError("contract must document launch lock scope through child completion")
    if "managed target root" not in runtime_launch.get("mutable_runtime_paths", ""):
        raise ValueError("contract must document writable runtime state paths")
    if "only the dedicated lock directory" not in runtime_launch.get("pre_handoff_executable_revalidation", ""):
        raise ValueError("contract must document narrow launch path protection")
    if "pinned official-binary digest" not in runtime_launch.get("pre_handoff_executable_revalidation", ""):
        raise ValueError("contract must document pinned digest revalidation before launch handoff")
    if "write-protected verified-path handoff" not in runtime_launch.get("portable_handoff_mechanism", ""):
        raise ValueError("contract must document portable verified-path handoff")
    if "exact-inode fd execution is not the portable macOS contract" not in runtime_launch.get("portable_handoff_mechanism", ""):
        raise ValueError("contract must not overclaim portable exact-inode execution")
    lifecycle_scope = runtime_launch.get("lifecycle_lock_scope", "").lower()
    if "external product coordination" not in lifecycle_scope:
        raise ValueError("contract must document external product coordination")
    if "canonical external target lock" not in lifecycle_scope:
        raise ValueError("contract must document external target handoff")
    if "fcntl.flock" not in runtime_launch.get("lifecycle_lock_mechanism", ""):
        raise ValueError("contract must document the stable flock mechanism")
    if "fixed validated system temp root" not in runtime_launch.get("lifecycle_lock_mechanism", ""):
        raise ValueError("contract must document fixed bootstrap root")
    if "lock files are never unlinked" not in runtime_launch.get("lifecycle_lock_mechanism", ""):
        raise ValueError("contract must document persistent lifecycle lock files")
    if "restored to 0700" not in runtime_launch.get("lifecycle_lock_mechanism", ""):
        raise ValueError("contract must document internal lock directory restoration")
    if "dedicated target-local lock directory" not in runtime_launch.get("lifecycle_lock_mechanism", ""):
        raise ValueError("contract must document the dedicated lock directory")
    if "same-UID" not in runtime_launch.get("same_uid_tamper_boundary", ""):
        raise ValueError("contract must document the same-UID tamper boundary")
    if runtime_launch.get("workspace_default_source") != "captured-caller-cwd":
        raise ValueError("contract must document captured caller cwd as the default launch workspace")
    if runtime_launch.get("manager_workspace_argument") != "--workspace":
        raise ValueError("contract must document the manager workspace argument")
    if runtime_launch.get("child_cwd_policy") != "explicit-subprocess-cwd":
        raise ValueError("contract must document explicit subprocess cwd handoff")
    if runtime_launch.get("native_cwd_flag") is not None:
        raise ValueError("contract must not invent an upstream Kimi cwd flag")
    if "--add-dir" not in runtime_launch.get("workspace_expansion_blocked", []):
        raise ValueError("contract must document blocked native workspace expansion")
    if manifest.get("runtime_launch") != {
        "external_target_bound_lifecycle_lock": True,
        "external_product_lifecycle_lock": True,
        "external_product_to_target_handoff": True,
        "external_lock_persistent_inode": True,
        "external_lock_fixed_system_bootstrap_root": True,
        "internal_lock_persistent_inode": True,
        "internal_lock_directory_protected_while_held": True,
        "holds_lifecycle_lock_through_child": True,
        "stable_fcntl_flock_lifecycle_lock": True,
        "write_protected_verified_path_handoff": True,
        "mutable_runtime_state_writable_during_launch": True,
        "pre_handoff_executable_revalidation": True,
        "exact_inode_exec": False,
        "runtime_dirs_private": True,
        "default_workspace_source": "captured-caller-cwd",
        "manager_workspace_argument": "--workspace",
        "explicit_child_cwd": True,
        "native_cwd_flag": None,
        "blocks_native_add_dir_workspace_expansion": True,
    }:
        raise ValueError("manifest must expose launch lock, executable revalidation, and workspace facts")
    software = contract["software_lifecycle"]
    if software.get("channel") != "official-binary" or software.get("manifest_sha256") != MANIFEST_SHA256:
        raise ValueError("contract software lifecycle must use official binary manifest")
    if software.get("status_executes_binary") is not False:
        raise ValueError("software status must remain read-only")
    if contract["runtime_compatibility"].get("windows_supported") is not False:
        raise ValueError("Windows must be unsupported")
    validate_baseline(baseline)


def make_isolated_target(label: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temp = tempfile.TemporaryDirectory(prefix=f".tmp-kimicode-{label}-", dir=str(ROOT))
    parent = Path(temp.name) / "parent"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    return temp, parent / "target"


def directory_metadata_snapshot(path: Path) -> tuple[Any, ...]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"snapshot path is not a directory: {path}")
    return (
        info.st_dev,
        info.st_ino,
        stat.S_IMODE(info.st_mode),
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_atime_ns,
        info.st_mtime_ns,
    )


def directory_restorable_metadata_snapshot(path: Path) -> tuple[Any, ...]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"snapshot path is not a directory: {path}")
    return (
        info.st_dev,
        info.st_ino,
        stat.S_IMODE(info.st_mode),
        info.st_uid,
        info.st_atime_ns,
        info.st_mtime_ns,
    )


def pin_directory_metadata(path: Path, offset: int) -> tuple[Any, ...]:
    base = 1_700_000_000_000_000_000 + offset
    os.utime(path, ns=(base, base + 123_456_789))
    return directory_metadata_snapshot(path)


def write_stub_software(manager: Any, target: Path, binary_bytes: bytes | None = None) -> None:
    platform_key = "linux-x64"
    if binary_bytes is None:
        binary_bytes = b"#!/bin/sh\nprintf 'kimi-code 0.29.2\\n'\n"
    binary_sha = manager.sha256_bytes(binary_bytes)
    patched_platforms = dict(manager.KIMI_BINARY_PLATFORMS)
    patched_platforms[platform_key] = {
        "filename": "kimi-code-public-validator-stub",
        "checksum": binary_sha,
    }
    manager.KIMI_BINARY_PLATFORMS = patched_platforms

    software_bin = manager.software_current(target) / "bin"
    software_bin.mkdir(mode=0o700, parents=True)
    manager.software_root(target).chmod(0o700)
    manager.software_current(target).chmod(0o700)
    software_bin.chmod(0o700)
    current_binary = software_bin / manager.KIMI_COMMAND
    current_binary.write_bytes(binary_bytes)
    current_binary.chmod(0o700)

    entrypoint_bin = target / "bin"
    entrypoint_bin.mkdir(mode=0o700)
    entrypoint_bin.chmod(0o700)
    entrypoint = entrypoint_bin / manager.KIMI_COMMAND
    entrypoint.write_bytes(binary_bytes)
    entrypoint.chmod(0o700)

    binary = patched_platforms[platform_key]
    stamp = manager.software_stamp(
        target,
        platform_key=platform_key,
        binary={
            "filename": binary["filename"],
            "url": f"{manager.KIMI_BINARY_BASE}/{manager.KIMI_PACKAGE_VERSION}/{binary['filename']}",
            "sha256": binary["checksum"],
        },
        entrypoint_digest=manager.file_sha256(entrypoint, label="stub Kimi Code entrypoint"),
        installed_tree_digest=manager.tree_sha256(manager.software_current(target)),
        version_probe_digest=manager.sha256_bytes(b"public-validator-stub-version-probe"),
    )
    manager.atomic_write(manager.software_stamp_path(target), manager.canonical_json(stamp), target)


def file_sha256_no_follow(path: Path, max_bytes: int) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"snapshot file is too large: {path}")
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(fd)


def bootstrap_tree_snapshot(manager: Any, *, system_root: Path | None = None) -> tuple[Any, ...] | None:
    root = (system_root or manager.fixed_system_temp_root()) / manager.EXTERNAL_LOCK_ROOT_NAME
    try:
        info = root.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return (("<root-symlink>",),)
    if not stat.S_ISDIR(info.st_mode):
        return (("<root-non-directory>",),)
    entries: list[tuple[Any, ...]] = [
        (
            "<root>",
            info.st_dev,
            info.st_ino,
            stat.S_IMODE(info.st_mode),
            info.st_uid,
            info.st_nlink,
        )
    ]
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        return (*entries, (f"<unreadable:{exc.errno}>",))
    if len(children) > 256:
        raise ValueError("bootstrap snapshot is unexpectedly large")
    for child in children:
        child_info = child.lstat()
        child_entry: tuple[Any, ...]
        if stat.S_ISREG(child_info.st_mode):
            child_entry = (
                child.name,
                "file",
                child_info.st_dev,
                child_info.st_ino,
                stat.S_IMODE(child_info.st_mode),
                child_info.st_uid,
                child_info.st_nlink,
                child_info.st_size,
                file_sha256_no_follow(child, max_bytes=manager.METADATA_MAX_BYTES),
            )
        elif stat.S_ISDIR(child_info.st_mode):
            child_entry = (
                child.name,
                "directory",
                child_info.st_dev,
                child_info.st_ino,
                stat.S_IMODE(child_info.st_mode),
                child_info.st_uid,
                child_info.st_nlink,
            )
        else:
            child_entry = (
                child.name,
                "other",
                child_info.st_dev,
                child_info.st_ino,
                stat.S_IMODE(child_info.st_mode),
                child_info.st_uid,
                child_info.st_nlink,
            )
        entries.append(child_entry)
    return tuple(entries)


def run_with_injected_bootstrap_root(manager: Any, callback: Any) -> None:
    original_resolver = manager.fixed_system_temp_root
    before = bootstrap_tree_snapshot(manager)
    with tempfile.TemporaryDirectory(prefix=".tmp-kimicode-bootstrap-") as temp:
        injected_root = Path(temp) / "system-root"
        injected_root.mkdir(mode=0o777)
        injected_root.chmod(0o1777)
        if ROOT in injected_root.resolve().parents:
            raise ValueError("injected bootstrap root must be outside the source tree")
        if stat.S_IMODE(injected_root.lstat().st_mode) != 0o1777:
            raise ValueError("injected bootstrap system root must be sticky 01777")
        manager.fixed_system_temp_root = lambda: injected_root
        try:
            if manager.fixed_system_temp_root() != injected_root:
                raise ValueError("bootstrap root monkeypatch was not installed")
            callback()
        finally:
            manager.fixed_system_temp_root = original_resolver
    after = bootstrap_tree_snapshot(manager)
    if after != before:
        raise ValueError("runtime regressions created artifacts in the real system bootstrap root")


def validate_status_launch_allowed_regression(manager: Any) -> None:
    temp, target = make_isolated_target("status-")
    try:
        manager.write_setup(
            target,
            manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
            manager.load_profile(manager.DEFAULT_PROFILE),
        )
        fresh_status = manager.status_payload(target)
        if fresh_status.get("launch_allowed") is not False:
            raise ValueError("fresh managed setup without software must not be launch_allowed")
        if fresh_status.get("software_current") is not False:
            raise ValueError("fresh managed setup must report software_current false")

        original_platforms = manager.KIMI_BINARY_PLATFORMS
        try:
            write_stub_software(manager, target)
            software = manager.software_status_payload(target)
            if software.get("current") is not True:
                raise ValueError(f"stub software must be current: {software.get('drift')}")
            ready_status = manager.status_payload(target)
            if ready_status.get("launch_allowed") is not True:
                raise ValueError("current clean setup with current target-owned software must be launch_allowed")
        finally:
            manager.KIMI_BINARY_PLATFORMS = original_platforms
    finally:
        temp.cleanup()


def validate_corrupt_backup_regression(manager: Any) -> None:
    temp, target = make_isolated_target("backup-")
    try:
        setup = manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP)
        manager.write_setup(target, setup, manager.load_profile(manager.DEFAULT_PROFILE))
        manager.write_setup(target, setup, manager.load_profile("safe"), require_existing=True)
        before = manager.status_payload(target)
        backup_path = manager.backup_pool(target) / "0" / manager.BACKUP_NAME
        envelope = manager.read_json_file(backup_path, max_bytes=manager.METADATA_MAX_BYTES, label=manager.BACKUP_NAME)
        files = envelope.get("files")
        if not isinstance(files, dict):
            raise ValueError("backup regression could not find backup files")
        corrupt_relative = "skills/nddev-builder/SKILL.md"
        if corrupt_relative not in files:
            raise ValueError("backup regression could not find routed skill payload")
        files[corrupt_relative] = "!!!!"
        manager.atomic_write(backup_path, manager.canonical_json(envelope), backup_path.parent)
        try:
            manager.restore_backup(target, 0)
        except manager.KimicodeSetupError as exc:
            if str(exc) != "backup file payload is invalid base64":
                raise ValueError(f"corrupt backup returned unstable error: {exc}") from exc
        else:
            raise ValueError("corrupt backup restore unexpectedly succeeded")
        after = manager.status_payload(target)
        if after.get("permission_profile_id") != before.get("permission_profile_id") or after.get("drift"):
            raise ValueError("corrupt backup restore did not roll back cleanly")
    finally:
        temp.cleanup()


def validate_external_lock_binding_regression(manager: Any) -> None:
    temp, target = make_isolated_target("external-lock-binding-")
    try:
        setup = manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP)
        manager.write_setup(target, setup, manager.load_profile(manager.DEFAULT_PROFILE))
        canonical_target = manager.lock_canonical_target(target)
        lock_path = manager.bootstrap_lock_path(target, canonical_target)
        internal_path = manager.lock_path(target)
        if not internal_path.is_file():
            raise ValueError("target lifecycle lock must be persistent after normal release")
        internal_info = internal_path.lstat()
        valid_payload = manager.canonical_json(
            manager.lock_payload("external-bootstrap", canonical_target, lock_path)
        )

        lock_path.write_bytes(b"")
        lock_path.chmod(0o600)
        try:
            manager.write_setup(target, setup, manager.load_profile("safe"), require_existing=True)
        except manager.KimicodeSetupError as exc:
            if "binding is missing" not in str(exc):
                raise ValueError(f"empty external lock binding returned unstable error: {exc}") from exc
        else:
            raise ValueError("empty external lock binding unexpectedly succeeded")
        lock_path.write_bytes(valid_payload)
        lock_path.chmod(0o600)
        manager.write_setup(target, setup, manager.load_profile("safe"), require_existing=True)
        if not lock_path.is_file():
            raise ValueError("external bootstrap lock must be persistent after normal release")
        first_info = lock_path.lstat()
        if not internal_path.is_file():
            raise ValueError("target lifecycle lock disappeared after normal release")
        if (internal_info.st_dev, internal_info.st_ino) != (internal_path.lstat().st_dev, internal_path.lstat().st_ino):
            raise ValueError("target lifecycle lock inode changed across normal release")

        lock_path.write_bytes(b"not json\n")
        lock_path.chmod(0o600)
        try:
            manager.write_setup(target, setup, manager.load_profile(manager.DEFAULT_PROFILE), require_existing=True)
        except manager.KimicodeSetupError as exc:
            if "binding is malformed" not in str(exc):
                raise ValueError(f"malformed external lock binding returned unstable error: {exc}") from exc
        else:
            raise ValueError("malformed external lock binding unexpectedly succeeded")
        lock_path.write_bytes(valid_payload)
        lock_path.chmod(0o600)

        payload = manager.lock_payload(
            "external-bootstrap",
            str(target.parent / "other-target"),
            lock_path,
        )
        lock_path.write_bytes(manager.canonical_json(payload))
        lock_path.chmod(0o600)
        try:
            manager.write_setup(target, setup, manager.load_profile(manager.DEFAULT_PROFILE), require_existing=True)
        except manager.KimicodeSetupError as exc:
            if "different canonical target" not in str(exc):
                raise ValueError(f"external lock binding returned unstable error: {exc}") from exc
        else:
            raise ValueError("external lock binding mismatch unexpectedly succeeded")
        lock_path.write_bytes(valid_payload)
        lock_path.chmod(0o600)

        payload = manager.lock_payload("external-bootstrap", canonical_target, target / "wrong.lock")
        lock_path.write_bytes(manager.canonical_json(payload))
        lock_path.chmod(0o600)
        try:
            manager.write_setup(target, setup, manager.load_profile(manager.DEFAULT_PROFILE), require_existing=True)
        except manager.KimicodeSetupError as exc:
            if "different lock path" not in str(exc):
                raise ValueError(f"external lock path binding returned unstable error: {exc}") from exc
        else:
            raise ValueError("external lock path binding mismatch unexpectedly succeeded")

        lock_path.write_bytes(valid_payload)
        lock_path.chmod(0o600)
        manager.write_setup(target, setup, manager.load_profile("safe"), require_existing=True)
        second_info = lock_path.lstat()
        if (first_info.st_dev, first_info.st_ino) != (second_info.st_dev, second_info.st_ino):
            raise ValueError("external bootstrap lock inode changed across normal release")
    finally:
        temp.cleanup()


def write_lock_stage_alias(
    manager: Any,
    path: Path,
    *,
    canonical_target: str,
    kind: str,
    pid: int,
    nonce: int,
    payload_override: dict[str, Any] | None = None,
) -> Path:
    payload = payload_override or manager.lock_payload(kind, canonical_target, path)
    stage = path.with_name(f"{manager.lock_stage_prefix(path)}{pid}.{nonce}")
    stage.write_bytes(manager.canonical_json(payload))
    stage.chmod(0o600)
    return stage


def expect_lock_operation_rejected(manager: Any, operation: Any, expected: str) -> None:
    try:
        operation()
    except manager.KimicodeSetupError as exc:
        if expected not in str(exc):
            raise ValueError(f"lock operation returned unstable error: {exc}") from exc
        return
    raise ValueError(f"lock operation unexpectedly succeeded; expected {expected}")


def expect_operation_failed(operation: Any, label: str) -> None:
    try:
        operation()
    except BaseException:
        return
    raise ValueError(f"{label} unexpectedly succeeded")


def patch_fsync_to_fail_second_call(manager: Any) -> Any:
    original_fsync = manager.os.fsync
    calls = 0

    def failing_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            manager.os.fsync = original_fsync
            raise OSError("injected fsync failure")
        original_fsync(fd)

    manager.os.fsync = failing_fsync
    return original_fsync


def validate_unpublished_lock_creation_rollback_regression(manager: Any) -> None:
    original_resolver = manager.fixed_system_temp_root
    with tempfile.TemporaryDirectory(prefix=".tmp-kimicode-lock-rollback-") as temp:
        system_root = Path(temp) / "system-root"
        system_root.mkdir(mode=0o777)
        system_root.chmod(0o1777)
        manager.fixed_system_temp_root = lambda: system_root
        try:
            product_root = system_root / manager.EXTERNAL_LOCK_ROOT_NAME
            before_system = pin_directory_metadata(system_root, 10)
            original_fsync = patch_fsync_to_fail_second_call(manager)
            try:
                expect_operation_failed(
                    manager.ensure_external_lock_root,
                    "product lock root rollback smoke",
                )
            finally:
                manager.os.fsync = original_fsync
            if manager.path_exists_no_follow(product_root):
                raise ValueError("failed product lock root publication left an unpublished root")
            if directory_metadata_snapshot(system_root) != before_system:
                raise ValueError("failed product lock root publication changed parent metadata")

            before_system = pin_directory_metadata(system_root, 15)
            original_stage_writer = manager.write_lock_stage_file

            def failing_product_stage(path: Path, payload: bytes, label: str) -> None:
                if label == "external product lifecycle lock staged binding":
                    raise OSError("injected product anchor publication failure")
                original_stage_writer(path, payload, label)

            manager.write_lock_stage_file = failing_product_stage
            try:
                expect_operation_failed(
                    lambda: manager.acquire_product_lock(create=True, exclusive=True),
                    "product anchor rollback smoke",
                )
            finally:
                manager.write_lock_stage_file = original_stage_writer
            if manager.path_exists_no_follow(product_root):
                raise ValueError("failed product anchor publication left a newly-created product root")
            if directory_metadata_snapshot(system_root) != before_system:
                raise ValueError("failed product anchor publication changed parent metadata")

            before_system_restorable = directory_restorable_metadata_snapshot(system_root)
            product = manager.acquire_product_lock(create=True, exclusive=True)
            if product is None:
                raise ValueError("product lock was not created for target-root rollback smoke")
            if directory_restorable_metadata_snapshot(system_root) != before_system_restorable:
                raise ValueError("successful product anchor publication did not restore parent metadata")
            try:
                target_root = manager.target_lock_root_path(product.root)
                before_product = pin_directory_metadata(product.root, 20)
                original_fsync = patch_fsync_to_fail_second_call(manager)
                try:
                    expect_operation_failed(
                        lambda: manager.ensure_external_target_lock_root(product.root),
                        "target lock root rollback smoke",
                    )
                finally:
                    manager.os.fsync = original_fsync
                if manager.path_exists_no_follow(target_root):
                    raise ValueError("failed target lock root publication left an unpublished root")
                if directory_metadata_snapshot(product.root) != before_product:
                    raise ValueError("failed target lock root publication changed parent metadata")

                canonical_target = str(Path(temp) / "target-anchor-failure")
                before_product = pin_directory_metadata(product.root, 25)
                original_stage_writer = manager.write_lock_stage_file

                def failing_target_stage(path: Path, payload: bytes, label: str) -> None:
                    if label == "external target lifecycle lock staged binding":
                        raise OSError("injected target anchor publication failure")
                    original_stage_writer(path, payload, label)

                manager.write_lock_stage_file = failing_target_stage
                try:
                    expect_operation_failed(
                        lambda: manager.acquire_external_target_lock(
                            product.root,
                            canonical_target,
                            create=True,
                            exclusive=True,
                        ),
                        "target anchor rollback smoke",
                    )
                finally:
                    manager.write_lock_stage_file = original_stage_writer
                if manager.path_exists_no_follow(target_root):
                    raise ValueError("failed target anchor publication left a newly-created targets root")
                if directory_metadata_snapshot(product.root) != before_product:
                    raise ValueError("failed target anchor publication changed parent metadata")

                before_product_restorable = directory_restorable_metadata_snapshot(product.root)
                external = manager.acquire_external_target_lock(
                    product.root,
                    canonical_target,
                    create=True,
                    exclusive=True,
                )
                if external is None:
                    raise ValueError("external target lock was not created after target-anchor rollback smoke")
                try:
                    if directory_restorable_metadata_snapshot(product.root) != before_product_restorable:
                        raise ValueError("successful target anchor publication did not restore parent metadata")
                finally:
                    manager.release_external_target_lock(external)
            finally:
                manager.release_product_lock(product)
        finally:
            manager.fixed_system_temp_root = original_resolver

    with tempfile.TemporaryDirectory(prefix=".tmp-kimicode-stage-rollback-") as temp:
        parent = Path(temp) / "stage-parent"
        parent.mkdir(mode=0o700)
        parent.chmod(0o700)
        stage = parent / ".anchor.nddev.tmp.1.1"
        before_parent = pin_directory_metadata(parent, 30)
        original_write_all = manager.write_all

        def failing_write_all(fd: int, data: bytes) -> None:
            original_write_all(fd, data[:1])
            raise OSError("injected write failure")

        manager.write_all = failing_write_all
        try:
            expect_operation_failed(
                lambda: manager.write_lock_stage_file(stage, b'{"complete": true}\n', "stage rollback smoke"),
                "stage rollback smoke",
            )
        finally:
            manager.write_all = original_write_all
        if manager.path_exists_no_follow(stage):
            raise ValueError("failed staged binding creation left an unpublished stage")
        if directory_metadata_snapshot(parent) != before_parent:
            raise ValueError("failed staged binding creation changed parent metadata")


def validate_lock_stage_publication_recovery_regression(manager: Any) -> None:
    def run_killed_publication_case(case_label: str, target: Path, setup: dict[str, Any], profile: dict[str, Any], kill_label: str) -> None:
        marker = Path(temp.name) / "stage-marker"
        child_error = Path(temp.name) / "child-error"
        with contextlib.suppress(FileNotFoundError):
            marker.unlink()
        with contextlib.suppress(FileNotFoundError):
            child_error.unlink()
        pid = os.fork()
        if pid == 0:
            try:
                def kill_after_stage_fsync(source: Path, destination: Path, label: str) -> bool:
                    if label == kill_label:
                        marker.write_text(json.dumps({"source": str(source), "destination": str(destination)}), encoding="utf-8")
                        os.kill(os.getpid(), signal.SIGKILL)
                        raise AssertionError("SIGKILL did not terminate the staged publisher")
                    return original_rename(source, destination, label)

                original_rename = manager.rename_no_replace
                manager.rename_no_replace = kill_after_stage_fsync
                manager.write_setup(target, setup, profile)
                os._exit(23)
            except BaseException as exc:
                child_error.write_text(repr(exc), encoding="utf-8")
                os._exit(24)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if marker.exists():
                break
            if child_error.exists():
                raise ValueError(f"publisher child failed before marker: {child_error.read_text(encoding='utf-8')}")
            waited, status = os.waitpid(pid, os.WNOHANG)
            if waited == pid:
                raise ValueError(f"publisher child exited before marker with status {status}")
            time.sleep(0.05)
        else:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, 0)
            raise ValueError("timed out waiting for post-stage-fsync marker")
        fork_wait_signal(pid, "post-stage-fsync publisher", signal.SIGKILL)
        if child_error.exists():
            raise ValueError(f"publisher child failed before SIGKILL: {child_error.read_text(encoding='utf-8')}")
        payload = json.loads(marker.read_text(encoding="utf-8"))
        stage = Path(payload["source"])
        lock_path = Path(payload["destination"])
        if lock_path.exists():
            raise ValueError(f"{case_label} final anchor was published before the SIGKILL boundary")
        if not stage.is_file():
            raise ValueError(f"{case_label} post-stage-fsync SIGKILL did not leave the staged alias")
        before_read = bootstrap_tree_snapshot(manager, system_root=manager.fixed_system_temp_root())
        readers = (
            ("status", lambda: manager.status_payload(target)),
            ("plan", lambda: manager.plan_payload(target, setup, profile)),
            ("software-status", lambda: manager.software_status_payload(target)),
        )
        for reader_label, reader in readers:
            try:
                reader()
            except manager.KimicodeSetupError as exc:
                message = str(exc)
                if "incomplete staged publication" not in message and "must be empty without product anchor" not in message:
                    raise ValueError(f"{reader_label} returned unstable staged-publication error: {exc}") from exc
            else:
                raise ValueError(f"{reader_label} unexpectedly repaired or ignored the staged publication")
            after_read = bootstrap_tree_snapshot(manager, system_root=manager.fixed_system_temp_root())
            if after_read != before_read:
                raise ValueError(f"{reader_label} mutated the staged lock namespace")

        manager.write_setup(target, setup, profile)
        if not lock_path.is_file():
            raise ValueError(f"exclusive mutator did not publish the recovered {case_label} final anchor")
        if stage.exists():
            raise ValueError(f"exclusive mutator did not drain the recovered {case_label} staged alias")
        first_info = lock_path.lstat()
        manager.write_setup(target, setup, profile, require_existing=True)
        second_info = lock_path.lstat()
        if (first_info.st_dev, first_info.st_ino, first_info.st_nlink) != (
            second_info.st_dev,
            second_info.st_ino,
            second_info.st_nlink,
        ):
            raise ValueError(f"recovered {case_label} final anchor identity changed on the next mutator")

    temp, target = make_isolated_target("lock-stage-recovery-")
    try:
        setup = manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP)
        profile = manager.load_profile(manager.DEFAULT_PROFILE)
        run_killed_publication_case("product", target, setup, profile, "external product lifecycle lock")
        target_two = target.parent / "target-two"
        run_killed_publication_case("target", target_two, setup, profile, "external target lifecycle lock")
    finally:
        temp.cleanup()


def validate_lock_stage_adversarial_regression(manager: Any) -> None:
    cases = ("malformed-name", "partial", "wrong-target", "symlink", "hardlink", "excessive")
    for label in cases:
        temp, target = make_isolated_target(f"lock-stage-{label}-")
        try:
            setup = manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP)
            profile = manager.load_profile(manager.DEFAULT_PROFILE)
            canonical_target = manager.lock_canonical_target(target)
            product = manager.acquire_product_lock(create=True, exclusive=True)
            if product is None:
                raise ValueError("product lock was not created for adversarial target stage")
            try:
                manager.ensure_external_target_lock_root(product.root)
                lock_path = manager.bootstrap_lock_path_for_root(product.root, canonical_target)
            finally:
                manager.release_product_lock(product)
            parent = lock_path.parent
            if label == "malformed-name":
                stage = lock_path.with_name(f"{manager.lock_stage_prefix(lock_path)}not-a-pid.1")
                stage.write_text("not json\n", encoding="utf-8")
                stage.chmod(0o600)
                expected = "staged binding alias is malformed"
            elif label == "partial":
                stage = lock_path.with_name(f"{manager.lock_stage_prefix(lock_path)}101.1")
                stage.write_text("{", encoding="utf-8")
                stage.chmod(0o600)
                expected = "staged binding is malformed"
            elif label == "wrong-target":
                stage = write_lock_stage_alias(
                    manager,
                    lock_path,
                    canonical_target=str(target.parent / "wrong-target"),
                    kind="external-bootstrap",
                    pid=102,
                    nonce=1,
                )
                expected = "different canonical target"
            elif label == "symlink":
                stage = lock_path.with_name(f"{manager.lock_stage_prefix(lock_path)}103.1")
                outside = Path(temp.name) / "outside-stage"
                outside.write_text("outside\n", encoding="utf-8")
                stage.symlink_to(outside)
                expected = "must not be a symlink"
            elif label == "hardlink":
                stage = write_lock_stage_alias(
                    manager,
                    lock_path,
                    canonical_target=canonical_target,
                    kind="external-bootstrap",
                    pid=104,
                    nonce=1,
                )
                hardlink = lock_path.with_name(f"{manager.lock_stage_prefix(lock_path)}104.2")
                os.link(stage, hardlink)
                expected = "must not be a hardlink"
            else:
                stage = write_lock_stage_alias(
                    manager,
                    lock_path,
                    canonical_target=canonical_target,
                    kind="external-bootstrap",
                    pid=105,
                    nonce=0,
                )
                for index in range(1, manager.LOCK_STAGE_ALIAS_MAX + 2):
                    write_lock_stage_alias(
                        manager,
                        lock_path,
                        canonical_target=canonical_target,
                        kind="external-bootstrap",
                        pid=105,
                        nonce=index,
                    )
                expected = "too many staged binding aliases"
            before = bootstrap_tree_snapshot(manager, system_root=manager.fixed_system_temp_root())
            expect_lock_operation_rejected(
                manager,
                lambda: manager.write_setup(target, setup, profile),
                expected,
            )
            after = bootstrap_tree_snapshot(manager, system_root=manager.fixed_system_temp_root())
            if after != before:
                raise ValueError(f"{label} staged alias rejection mutated the lock namespace")
            if not stage.exists() and not stage.is_symlink():
                raise ValueError(f"{label} staged alias was removed on rejection")
            if lock_path.exists():
                raise ValueError(f"{label} staged alias rejection published a final anchor")
        finally:
            temp.cleanup()


def fork_wait(pid: int, label: str, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    status_value: int | None = None
    while time.monotonic() < deadline:
        waited, status_value = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            break
        if waited != 0:
            raise ValueError(f"{label} waitpid returned the wrong child")
        time.sleep(0.05)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, 9)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)
        raise ValueError(f"{label} did not exit within {timeout_seconds:.1f}s")
    if status_value is None:
        raise ValueError(f"{label} waitpid did not return a status")
    if os.WIFSIGNALED(status_value):
        raise ValueError(f"{label} died from signal {os.WTERMSIG(status_value)}")
    if not os.WIFEXITED(status_value) or os.WEXITSTATUS(status_value) != 0:
        raise ValueError(f"{label} exited with status {status_value}")


def fork_wait_signal(pid: int, label: str, expected_signal: int, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    status_value: int | None = None
    while time.monotonic() < deadline:
        waited, status_value = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            break
        if waited != 0:
            raise ValueError(f"{label} waitpid returned the wrong child")
        time.sleep(0.05)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)
        raise ValueError(f"{label} did not exit within {timeout_seconds:.1f}s")
    if status_value is None:
        raise ValueError(f"{label} waitpid did not return a status")
    if not os.WIFSIGNALED(status_value) or os.WTERMSIG(status_value) != expected_signal:
        raise ValueError(f"{label} exited with unexpected status {status_value}")


def wait_for_file(path: Path, label: str, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise ValueError(f"timed out waiting for {label}")


def wait_for_file_or_error(path: Path, label: str, *error_paths: Path, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        for error_path in error_paths:
            if error_path.exists():
                raise ValueError(f"{label} child error: {error_path.read_text(encoding='utf-8')}")
        time.sleep(0.05)
    raise ValueError(f"timed out waiting for {label}")


def validate_external_lock_persistent_inode_handover_regression(manager: Any) -> None:
    temp, target = make_isolated_target("external-lock-handover-")
    children: list[tuple[int, str]] = []
    parent_fd: int | None = None
    lock_path: Path | None = None
    b_release: Path | None = None
    try:
        setup = manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP)
        manager.write_setup(target, setup, manager.load_profile(manager.DEFAULT_PROFILE))
        canonical_target = manager.lock_canonical_target(target)
        product = manager.acquire_product_lock(create=True, exclusive=True)
        if product is None:
            raise ValueError("product lock was not created for external handover")
        external = manager.acquire_external_target_lock(
            product.root,
            canonical_target,
            create=True,
            exclusive=True,
        )
        if external is None:
            raise ValueError("external target lock was not created for handover")
        manager.release_product_lock(product)
        lock_path = external.path
        parent_fd = external.fd
        initial_info = os.fstat(parent_fd)
        control = target.parent / "handover-control"
        control.mkdir(mode=0o700)
        control.chmod(0o700)
        b_acquired = control / "b-acquired"
        b_release = control / "b-release"
        c_acquired = control / "c-acquired"
        c_error = control / "c-error"
        b_error = control / "b-error"

        def fork_lock_holder(name: str, acquired: Path, release: Path | None, wait_for: Path | None, error_path: Path) -> int:
            pid = os.fork()
            if pid != 0:
                children.append((pid, name))
                return pid
            try:
                if parent_fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(parent_fd)
                if wait_for is not None:
                    wait_for_file(wait_for, f"{name} predecessor")
                deadline = time.monotonic() + 5.0
                child_fd: int | None = None
                while time.monotonic() < deadline:
                    product_handle = None
                    try:
                        product_handle = manager.acquire_product_lock(create=False, exclusive=False)
                        if product_handle is None:
                            raise ValueError("product lock disappeared during external handover")
                        child_external = manager.acquire_external_target_lock(
                            product_handle.root,
                            canonical_target,
                            create=False,
                            exclusive=True,
                        )
                        if child_external is None:
                            raise ValueError("external target lock disappeared during handover")
                        child_fd = child_external.fd
                        break
                    except manager.KimicodeSetupError as exc:
                        if "target is locked" not in str(exc):
                            raise
                        time.sleep(0.05)
                    finally:
                        manager.release_product_lock(product_handle)
                if child_fd is None:
                    raise ValueError(f"{name} did not acquire persistent external lock")
                info = os.fstat(child_fd)
                acquired.write_text(f"{info.st_dev}:{info.st_ino}\n", encoding="utf-8")
                if release is not None:
                    wait_for_file(release, f"{name} release")
                manager.release_external_target_lock(
                    manager.ExternalTargetLockHandle(fd=child_fd, path=lock_path, canonical_target=canonical_target)
                )
                os._exit(0)
            except BaseException as exc:
                with contextlib.suppress(BaseException):
                    error_path.write_text(str(exc), encoding="utf-8")
                os._exit(1)

        fork_lock_holder("handover-b", b_acquired, b_release, None, b_error)
        fork_lock_holder("handover-c", c_acquired, None, b_acquired, c_error)
        time.sleep(0.2)
        manager.release_external_target_lock(
            manager.ExternalTargetLockHandle(fd=parent_fd, path=lock_path, canonical_target=canonical_target)
        )
        parent_fd = None
        wait_for_file_or_error(b_acquired, "handover B acquire", b_error, c_error)
        if not lock_path.is_file():
            raise ValueError("external bootstrap lock disappeared during B handover")
        if b_acquired.read_text(encoding="utf-8") != f"{initial_info.st_dev}:{initial_info.st_ino}\n":
            raise ValueError("handover B acquired a different external lock inode")
        b_release.write_text("release\n", encoding="utf-8")
        wait_for_file_or_error(c_acquired, "handover C acquire", b_error, c_error)
        if c_acquired.read_text(encoding="utf-8") != f"{initial_info.st_dev}:{initial_info.st_ino}\n":
            raise ValueError("handover C acquired a different external lock inode")
        wait_errors: list[str] = []
        for pid, label in children:
            try:
                fork_wait(pid, label)
            except ValueError as exc:
                wait_errors.append(str(exc))
        children.clear()
        child_errors = "".join(
            path.read_text(encoding="utf-8")
            for path in (b_error, c_error)
            if path.exists()
        )
        if child_errors or wait_errors:
            raise ValueError(f"external lock handover child error: {child_errors}{'; '.join(wait_errors)}")
        final_info = lock_path.lstat()
        if (final_info.st_dev, final_info.st_ino) != (initial_info.st_dev, initial_info.st_ino):
            raise ValueError("external bootstrap lock inode changed after 3-process handover")
    finally:
        if parent_fd is not None and lock_path is not None:
            manager.release_external_target_lock(
                manager.ExternalTargetLockHandle(fd=parent_fd, path=lock_path, canonical_target=canonical_target)
            )
        if b_release is not None:
            with contextlib.suppress(BaseException):
                b_release.write_text("release\n", encoding="utf-8")
        for pid, label in children:
            with contextlib.suppress(ChildProcessError, ValueError):
                fork_wait(pid, label)
        temp.cleanup()


def acquire_external_target_for_validator(manager: Any, target: Path, *, create: bool = True) -> Any:
    canonical_target = manager.lock_canonical_target(target)
    product = manager.acquire_product_lock(create=create, exclusive=True)
    if product is None:
        raise ValueError("product lock was not available for validator target acquire")
    try:
        external = manager.acquire_external_target_lock(
            product.root,
            canonical_target,
            create=create,
            exclusive=True,
        )
        if external is None:
            raise ValueError("external target lock was not available for validator target acquire")
        return external
    finally:
        manager.release_product_lock(product)


def validate_external_lock_different_target_overlap_regression(manager: Any) -> None:
    temp, target_a = make_isolated_target("external-different-target-")
    target_b = target_a.parent / "target-b"
    child_error = target_a.parent / "different-target-error"
    child_acquired = target_a.parent / "different-target-acquired"
    try:
        target_a.mkdir(mode=0o700)
        target_a.chmod(0o700)
        target_b.mkdir(mode=0o700)
        target_b.chmod(0o700)
        held = acquire_external_target_for_validator(manager, target_a, create=True)
        pid = os.fork()
        if pid == 0:
            try:
                child_lock = acquire_external_target_for_validator(manager, target_b, create=True)
                info = os.fstat(child_lock.fd)
                child_acquired.write_text(f"{info.st_dev}:{info.st_ino}\n", encoding="utf-8")
                manager.release_external_target_lock(child_lock)
                os._exit(0)
            except BaseException as exc:
                with contextlib.suppress(BaseException):
                    child_error.write_text(str(exc), encoding="utf-8")
                os._exit(1)
        wait_for_file_or_error(child_acquired, "different-target external lock acquire", child_error)
        fork_wait(pid, "different-target child")
        if child_error.exists():
            raise ValueError(f"different-target child error: {child_error.read_text(encoding='utf-8')}")
        if not child_acquired.read_text(encoding="utf-8").strip():
            raise ValueError("different-target child did not record its external lock inode")
        manager.release_external_target_lock(held)
        held = None
    finally:
        if "held" in locals() and held is not None:
            manager.release_external_target_lock(held)
        temp.cleanup()


def validate_internal_lock_persistent_inode_handover_regression(manager: Any) -> None:
    temp, target = make_isolated_target("internal-lock-handover-")
    children: list[tuple[int, str]] = []
    parent_fd: int | None = None
    lock_path: Path | None = None
    protected_parent: Any | None = None
    b_release: Path | None = None
    try:
        setup = manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP)
        manager.write_setup(target, setup, manager.load_profile(manager.DEFAULT_PROFILE))
        canonical_target = manager.lock_canonical_target(target)
        lock_path = manager.lock_path(target)
        parent_fd = manager.acquire_lock_file(
            lock_path,
            "target lifecycle lock",
            canonical_target=canonical_target,
            kind="target-internal",
            create=True,
            exclusive=True,
        )
        initial_info = os.fstat(parent_fd)
        protected_parent = manager.protect_internal_lock_parent(lock_path.parent)
        if (lock_path.parent.stat().st_mode & 0o777) != 0o500:
            raise ValueError("target lifecycle lock parent was not protected while held")
        control = target.parent / "internal-handover-control"
        control.mkdir(mode=0o700)
        control.chmod(0o700)
        b_acquired = control / "b-acquired"
        b_release = control / "b-release"
        c_acquired = control / "c-acquired"
        b_error = control / "b-error"
        c_error = control / "c-error"

        def fork_internal_lock_holder(name: str, acquired: Path, release: Path | None, wait_for: Path | None, error_path: Path) -> None:
            pid = os.fork()
            if pid != 0:
                children.append((pid, name))
                return
            try:
                if parent_fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(parent_fd)
                if protected_parent is not None:
                    with contextlib.suppress(OSError):
                        os.close(protected_parent.fd)
                if wait_for is not None:
                    wait_for_file(wait_for, f"{name} predecessor")
                deadline = time.monotonic() + 5.0
                child_fd: int | None = None
                while time.monotonic() < deadline:
                    try:
                        child_fd = manager.acquire_lock_file(
                            lock_path,
                            "target lifecycle lock",
                            canonical_target=canonical_target,
                            kind="target-internal",
                            create=True,
                            exclusive=True,
                        )
                        break
                    except manager.KimicodeSetupError as exc:
                        if "target is locked" not in str(exc):
                            raise
                        time.sleep(0.05)
                if child_fd is None:
                    raise ValueError(f"{name} did not acquire persistent target lock")
                info = os.fstat(child_fd)
                acquired.write_text(f"{info.st_dev}:{info.st_ino}\n", encoding="utf-8")
                if release is not None:
                    wait_for_file(release, f"{name} release")
                manager.release_lock_file(child_fd, lock_path, remove_file=False)
                os._exit(0)
            except BaseException as exc:
                with contextlib.suppress(BaseException):
                    error_path.write_text(str(exc), encoding="utf-8")
                os._exit(1)

        fork_internal_lock_holder("internal-handover-b", b_acquired, b_release, None, b_error)
        fork_internal_lock_holder("internal-handover-c", c_acquired, None, b_acquired, c_error)
        time.sleep(0.2)
        manager.release_lock_file(parent_fd, lock_path, remove_file=False)
        parent_fd = None
        wait_for_file(b_acquired, "internal handover B acquire")
        if b_acquired.read_text(encoding="utf-8") != f"{initial_info.st_dev}:{initial_info.st_ino}\n":
            raise ValueError("handover B acquired a different target lifecycle lock inode")
        b_release.write_text("release\n", encoding="utf-8")
        wait_for_file(c_acquired, "internal handover C acquire")
        if c_acquired.read_text(encoding="utf-8") != f"{initial_info.st_dev}:{initial_info.st_ino}\n":
            raise ValueError("handover C acquired a different target lifecycle lock inode")
        for pid, label in children:
            fork_wait(pid, label)
        children.clear()
        child_errors = "".join(
            path.read_text(encoding="utf-8")
            for path in (b_error, c_error)
            if path.exists()
        )
        if child_errors:
            raise ValueError(f"target lifecycle lock handover child error: {child_errors}")
        final_info = lock_path.lstat()
        if (final_info.st_dev, final_info.st_ino) != (initial_info.st_dev, initial_info.st_ino):
            raise ValueError("target lifecycle lock inode changed after 3-process handover")
    finally:
        if parent_fd is not None and lock_path is not None:
            manager.release_lock_file(parent_fd, lock_path, remove_file=False)
        if b_release is not None:
            with contextlib.suppress(BaseException):
                b_release.write_text("release\n", encoding="utf-8")
        for pid, label in children:
            with contextlib.suppress(ChildProcessError):
                fork_wait(pid, label)
        if protected_parent is not None:
            protected_parent.restore()
        temp.cleanup()


def validate_runtime_regressions() -> None:
    manager = load_manager()
    manager_text = (ROOT / "cli-tools" / "nddev_kimicode.py").read_text(encoding="utf-8")
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
        "fcntl.flock(fd, lock_mode | fcntl.LOCK_NB)",
        "acquire_product_lock(create=True, exclusive=True)",
        "acquire_external_target_lock(",
        "release_product_lock(releasing_product)",
        "read_lifecycle_payload",
        "read_lifecycle_coordination",
        "kind=\"external-bootstrap\"",
        "kind=\"external-product\"",
        "kind=\"target-internal\"",
        "EXTERNAL_LOCK_NAMESPACE",
        "ensure_external_lock_root()",
        "protect_internal_lock_parent(lock_parent)",
        "validate_lock_binding",
        "binding is malformed",
        "current.st_dev != info.st_dev or current.st_ino != info.st_ino",
        "bootstrap_lock_path_for_root(product_root, canonical_target)",
        "release_external_target_lock(releasing_external)",
        "release_lock_file(releasing_internal_fd, internal_path, remove_file=False)",
        "os.fchmod(fd, 0o500)",
        "lock_path(target).parent",
        "with protected_launch_path(invocation.target):",
        "resolve_launch_workspace",
        "cwd=str(invocation.workspace)",
        "launch_parser.add_argument(\"--workspace\")",
        "expected_digest=invocation.expected_entrypoint_digest",
        "is_current_owner(opened)",
        "opened.st_dev != info.st_dev or opened.st_ino != info.st_ino",
        "target-owned Kimi Code entrypoint digest does not match pinned binary",
    ):
        if required not in manager_text:
            raise ValueError(f"manager is missing launch hardening fragment: {required}")
    protected_start = manager_text.index("def protected_launch_path")
    protected_end = manager_text.index("def revalidate_launch_executable")
    protected_source = manager_text[protected_start:protected_end]
    if "        target,\n" in protected_source:
        raise ValueError("launch protection must not chmod the managed target root")
    lock_source = manager_text[manager_text.index("def open_lock_file") : manager_text.index("def release_lock_file")]
    if "os.ftruncate" in lock_source:
        raise ValueError("lifecycle lock final anchors must not be truncated or rebound")
    if "O_CREAT | os.O_EXCL" in lock_source:
        raise ValueError("lifecycle lock final anchors must not be created empty")
    for required in (
        "def rename_no_replace",
        "RENAME_EXCL_DARWIN",
        "RENAME_NOREPLACE_LINUX",
        "publish_missing_lock_file",
        "write_lock_stage_file",
        "lock_stage_aliases",
        "promote_lock_stage_alias",
        "drain_lock_stage_aliases_after_lock",
        "bounded_directory_entries",
        "rollback_unpublished_path",
        "restore_directory_metadata_fd(parent_fd",
        "fsync_directory(parent)",
    ):
        if required not in manager_text:
            raise ValueError(f"manager is missing atomic lock publication fragment: {required}")

    def run_isolated_runtime_regressions() -> None:
        validate_unpublished_lock_creation_rollback_regression(manager)
        validate_lock_stage_publication_recovery_regression(manager)
        validate_status_launch_allowed_regression(manager)
        validate_corrupt_backup_regression(manager)
        validate_external_lock_binding_regression(manager)
        validate_external_lock_persistent_inode_handover_regression(manager)
        validate_external_lock_different_target_overlap_regression(manager)
        validate_internal_lock_persistent_inode_handover_regression(manager)
        validate_launch_lock_concurrency_regression(manager)
        validate_launch_external_lock_survives_internal_parent_rename_regression(manager)
        validate_launch_pre_handoff_swap_regression(manager)
        validate_launch_protected_verified_path_regression(manager)
        validate_launch_executable_error_regression(manager)
        validate_launch_boundary_regression(manager)
        validate_launch_workspace_scope_regression(manager)
        validate_lock_stage_adversarial_regression(manager)

    run_with_injected_bootstrap_root(manager, run_isolated_runtime_regressions)


def validate_launch_lock_concurrency_regression(manager: Any) -> None:
    temp, target = make_isolated_target("launch-lock-")
    try:
        manager.write_setup(
            target,
            manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
            manager.load_profile(manager.DEFAULT_PROFILE),
        )
        original_platforms = manager.KIMI_BINARY_PLATFORMS
        original_run = manager.subprocess.run
        try:
            write_stub_software(manager, target)
            lock = manager.lock_path(target)

            workspace = target.parent / "workspace"
            workspace.mkdir(mode=0o700)

            def fake_run(command: list[str], *, env: dict[str, str], cwd: str, check: bool) -> SimpleNamespace:
                if not lock.is_file():
                    raise ValueError("launch lifecycle lock was not held during child execution")
                if command[0] != str(target / "bin" / manager.KIMI_COMMAND):
                    raise ValueError("launch did not hand off to the target-owned executable")
                if cwd != str(workspace.resolve()):
                    raise ValueError("launch did not hand off the explicit workspace as child cwd")
                if env.get("KIMI_CODE_HOME") != str(target.resolve()):
                    raise ValueError("launch child environment is not target-scoped")
                if (target.stat().st_mode & 0o777) != 0o700:
                    raise ValueError("launch must not protect the managed target root")
                if (lock.parent.stat().st_mode & 0o777) != 0o500:
                    raise ValueError("launch did not protect the dedicated lifecycle lock parent")
                writable_probe = target / "launch-runtime-state"
                writable_probe.write_text("target-writable\n", encoding="utf-8")
                Path(env["HOME"], "home-state").write_text("home-writable\n", encoding="utf-8")
                Path(env["TMPDIR"], "tmp-state").write_text("tmp-writable\n", encoding="utf-8")
                try:
                    lock.unlink()
                except PermissionError:
                    pass
                else:
                    raise ValueError("launch lifecycle lock was removable by the child")
                replacement = target.parent / "replacement-kimi"
                replacement.write_bytes(b"#!/bin/sh\nexit 99\n")
                replacement.chmod(0o700)
                try:
                    os.replace(replacement, target / "bin" / manager.KIMI_COMMAND)
                except PermissionError:
                    pass
                else:
                    raise ValueError("launch protected path allowed ordinary os.replace")
                finally:
                    if replacement.exists():
                        try:
                            replacement.unlink()
                        except OSError:
                            pass
                probe = original_run(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import errno, fcntl, os, sys\n"
                            "fd = os.open(sys.argv[1], os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))\n"
                            "try:\n"
                            "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                            "except OSError as exc:\n"
                            "    if exc.errno in {errno.EACCES, errno.EAGAIN}:\n"
                            "        print('locked')\n"
                            "        raise SystemExit(0)\n"
                            "    raise\n"
                            "raise SystemExit('flock unexpectedly acquired')\n"
                        ),
                        str(lock),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if probe.returncode != 0 or probe.stdout.strip() != "locked":
                    raise ValueError(f"target lifecycle flock was not held by the launcher: {probe.stderr.strip()}")
                try:
                    manager.write_setup(
                        target,
                        manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
                        manager.load_profile("safe"),
                        require_existing=True,
                    )
                except manager.KimicodeSetupError as exc:
                    if "target is locked" not in str(exc) and "target must be private" not in str(exc):
                        raise ValueError(f"concurrent lifecycle mutation returned unstable error: {exc}") from exc
                else:
                    raise ValueError("lifecycle mutation succeeded while launch child was running")
                return SimpleNamespace(returncode=23)

            manager.subprocess.run = fake_run
            exit_code = manager.launch(target, ["--version"], workspace=str(workspace))
            if exit_code != 23:
                raise ValueError("launch did not forward child exit code under lifecycle lock")
            if not lock.is_file():
                raise ValueError("launch lifecycle lock was not persistent after child completion")
            if (lock.stat().st_mode & 0o777) != 0o600:
                raise ValueError("launch lifecycle lock mode changed after child completion")
            if (lock.parent.stat().st_mode & 0o777) != 0o700:
                raise ValueError("launch lifecycle lock parent was not restored after child completion")
        finally:
            manager.subprocess.run = original_run
            manager.KIMI_BINARY_PLATFORMS = original_platforms
    finally:
        temp.cleanup()


def validate_launch_external_lock_survives_internal_parent_rename_regression(manager: Any) -> None:
    temp, target = make_isolated_target("launch-external-lock-")
    result: dict[str, Any] = {}
    thread: threading.Thread | None = None
    release: Path | None = None
    try:
        manager.write_setup(
            target,
            manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
            manager.load_profile(manager.DEFAULT_PROFILE),
        )
        original_platforms = manager.KIMI_BINARY_PLATFORMS
        try:
            stub = (
                b"#!/bin/sh\n"
                b"if mv \"$KIMI_CODE_HOME/.nddev-kimicode-lock\" \"$KIMI_CODE_HOME/.nddev-kimicode-lock.renamed\" 2>/dev/null; then\n"
                b"  printf 'renamed\\n' > \"$1\"\n"
                b"else\n"
                b"  printf 'rename-failed\\n' > \"$1\"\n"
                b"fi\n"
                b"while [ ! -f \"$2\" ]; do sleep 0.05; done\n"
                b"exit 37\n"
            )
            write_stub_software(manager, target, stub)
            runtime_tmp = target / ".nddev-kimicode-runtime" / "tmp"
            marker = runtime_tmp / "internal-lock-renamed"
            release = runtime_tmp / "release-child"

            def run_launch() -> None:
                try:
                    result["exit_code"] = manager.launch(target, [str(marker), str(release)])
                except BaseException as exc:
                    result["error"] = exc

            thread = threading.Thread(target=run_launch)
            thread.start()
            wait_for_file(marker, "internal lock parent rename")
            if marker.read_text(encoding="utf-8") != "renamed\n":
                raise ValueError("launch child did not rename the internal lock parent")
            if (target.stat().st_mode & 0o777) != 0o700:
                raise ValueError("launch must keep managed target root writable during internal lock parent rename")

            mutation_cases = (
                (
                    "switch-profile",
                    lambda: manager.write_setup(
                        target,
                        manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
                        manager.load_profile("safe"),
                        require_existing=True,
                    ),
                ),
                ("remove", lambda: manager.remove_setup(target)),
                (
                    "install",
                    lambda: manager.write_setup(
                        target,
                        manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
                        manager.load_profile(manager.DEFAULT_PROFILE),
                        require_existing=False,
                    ),
                ),
            )
            for label, operation in mutation_cases:
                try:
                    operation()
                except manager.KimicodeSetupError as exc:
                    if "target is locked" not in str(exc):
                        raise ValueError(f"{label} returned unstable error under external lock: {exc}") from exc
                else:
                    raise ValueError(f"{label} succeeded after child renamed the internal lock parent")
            release.write_text("release\n", encoding="utf-8")
            thread.join(timeout=5)
            if thread.is_alive():
                raise ValueError("launch child did not exit after release marker")
            if "error" in result:
                raise ValueError(f"launch failed after internal lock parent rename: {result['error']}")
            if result.get("exit_code") != 37:
                raise ValueError("launch did not forward child exit code after internal lock parent rename")
            renamed_lock_parent = target / ".nddev-kimicode-lock.renamed"
            if not renamed_lock_parent.is_dir() or (renamed_lock_parent.stat().st_mode & 0o777) != 0o700:
                raise ValueError("renamed internal lock parent was not restored for cleanup")
        finally:
            if release is not None:
                with contextlib.suppress(BaseException):
                    release.write_text("release\n", encoding="utf-8")
            if thread is not None and thread.is_alive():
                thread.join(timeout=5)
            manager.KIMI_BINARY_PLATFORMS = original_platforms
    finally:
        temp.cleanup()


def validate_launch_pre_handoff_swap_regression(manager: Any) -> None:
    temp, target = make_isolated_target("launch-swap-")
    try:
        manager.write_setup(
            target,
            manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
            manager.load_profile(manager.DEFAULT_PROFILE),
        )
        original_platforms = manager.KIMI_BINARY_PLATFORMS
        original_prepare = manager.prepare_launch_invocation_locked
        original_run = manager.subprocess.run
        try:
            write_stub_software(manager, target)
            entrypoint = target / "bin" / manager.KIMI_COMMAND
            swapped = False

            def wrapped_prepare(status_target: Path, child_args: list[str], workspace: Path) -> Any:
                nonlocal swapped
                result = original_prepare(status_target, child_args, workspace)
                entrypoint.write_bytes(b"#!/bin/sh\nprintf 'swapped\\n'\n")
                entrypoint.chmod(0o700)
                swapped = True
                return result

            def fake_run(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
                raise ValueError("launch spawned a swapped target-owned executable")

            manager.prepare_launch_invocation_locked = wrapped_prepare
            manager.subprocess.run = fake_run
            try:
                manager.launch(target, ["--version"])
            except manager.KimicodeSetupError as exc:
                if "pinned binary" not in str(exc):
                    raise ValueError(f"swapped executable returned unstable error: {exc}") from exc
            else:
                raise ValueError("swapped executable launch unexpectedly succeeded")
            if not swapped:
                raise ValueError("pre-handoff executable swap regression was not exercised")
        finally:
            manager.subprocess.run = original_run
            manager.prepare_launch_invocation_locked = original_prepare
            manager.KIMI_BINARY_PLATFORMS = original_platforms
    finally:
        temp.cleanup()


def validate_launch_protected_verified_path_regression(manager: Any) -> None:
    temp, target = make_isolated_target("launch-protected-")
    try:
        manager.write_setup(
            target,
            manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
            manager.load_profile(manager.DEFAULT_PROFILE),
        )
        original_platforms = manager.KIMI_BINARY_PLATFORMS
        try:
            stub = (
                b"#!/bin/sh\n"
                b"if printf 'target-state\\n' > \"$KIMI_CODE_HOME/session-state\"; then\n"
                b"  printf 'target-write-ok\\n' >> \"$2\"\n"
                b"else\n"
                b"  printf 'target-write-failed\\n' >> \"$2\"\n"
                b"fi\n"
                b"if printf 'home-state\\n' > \"$HOME/home-state\"; then\n"
                b"  printf 'home-write-ok\\n' >> \"$2\"\n"
                b"else\n"
                b"  printf 'home-write-failed\\n' >> \"$2\"\n"
                b"fi\n"
                b"if printf 'tmp-state\\n' > \"$TMPDIR/tmp-state\"; then\n"
                b"  printf 'tmp-write-ok\\n' >> \"$2\"\n"
                b"else\n"
                b"  printf 'tmp-write-failed\\n' >> \"$2\"\n"
                b"fi\n"
                b"if rm -f \"$KIMI_CODE_HOME/bin/kimi\" 2>/dev/null; then\n"
                b"  printf 'executable-unlink-allowed\\n' >> \"$2\"\n"
                b"else\n"
                b"  printf 'executable-unlink-denied\\n' >> \"$2\"\n"
                b"fi\n"
                b"if mv \"$KIMI_CODE_HOME/bin/kimi\" \"$KIMI_CODE_HOME/bin/kimi.swapped\" 2>/dev/null; then\n"
                b"  printf 'executable-rename-allowed\\n' >> \"$2\"\n"
                b"else\n"
                b"  printf 'executable-rename-denied\\n' >> \"$2\"\n"
                b"fi\n"
                b"if rm -f \"$KIMI_CODE_HOME/.nddev-kimicode-lock/lifecycle.lock\" 2>/dev/null; then\n"
                b"  printf 'lock-unlink-allowed\\n' >> \"$2\"\n"
                b"else\n"
                b"  printf 'lock-unlink-denied\\n' >> \"$2\"\n"
                b"fi\n"
                b"printf 'replacement-lock\\n' > \"$KIMI_CODE_HOME/replacement-lock\"\n"
                b"if mv \"$KIMI_CODE_HOME/replacement-lock\" \"$KIMI_CODE_HOME/.nddev-kimicode-lock/lifecycle.lock\" 2>/dev/null; then\n"
                b"  printf 'lock-replace-allowed\\n' >> \"$2\"\n"
                b"else\n"
                b"  printf 'lock-replace-denied\\n' >> \"$2\"\n"
                b"  rm -f \"$KIMI_CODE_HOME/replacement-lock\"\n"
                b"fi\n"
                b"printf 'verified-bytes\\n' > \"$1\"\n"
                b"exit 31\n"
            )
            write_stub_software(manager, target, stub)
            marker = target / ".nddev-kimicode-runtime" / "tmp" / "verified-marker"
            report = target / ".nddev-kimicode-runtime" / "tmp" / "swap-report"
            exit_code = manager.launch(target, [str(marker), str(report)])
            if exit_code != 31:
                raise ValueError("protected launch did not forward real child exit code")
            if marker.read_text(encoding="utf-8") != "verified-bytes\n":
                raise ValueError("protected launch did not execute the verified stub bytes")
            report_lines = set(report.read_text(encoding="utf-8").splitlines())
            expected_denials = {
                "executable-unlink-denied",
                "executable-rename-denied",
                "lock-unlink-denied",
                "lock-replace-denied",
            }
            expected_writes = {
                "target-write-ok",
                "home-write-ok",
                "tmp-write-ok",
            }
            if not expected_denials <= report_lines:
                raise ValueError(f"protected launch did not deny ordinary swaps: {sorted(report_lines)}")
            if not expected_writes <= report_lines:
                raise ValueError(f"protected launch blocked expected runtime writes: {sorted(report_lines)}")
            if (target / "session-state").read_text(encoding="utf-8") != "target-state\n":
                raise ValueError("protected launch did not preserve KIMI_CODE_HOME write access")
            if (target / ".nddev-kimicode-runtime" / "home" / "home-state").read_text(encoding="utf-8") != "home-state\n":
                raise ValueError("protected launch did not preserve HOME write access")
            if (target / ".nddev-kimicode-runtime" / "tmp" / "tmp-state").read_text(encoding="utf-8") != "tmp-state\n":
                raise ValueError("protected launch did not preserve TMPDIR write access")
            entrypoint = target / "bin" / manager.KIMI_COMMAND
            if not entrypoint.is_file() or manager.file_sha256(entrypoint, label="post-launch stub") != manager.sha256_bytes(stub):
                raise ValueError("protected launch did not preserve the verified executable path")
            if (target.stat().st_mode & 0o777) != 0o700:
                raise ValueError("protected launch did not restore target mode")
            if not manager.lock_path(target).is_file():
                raise ValueError("protected launch did not preserve target lifecycle lock")
            if (manager.lock_path(target).parent.stat().st_mode & 0o777) != 0o700:
                raise ValueError("protected launch did not restore target lifecycle lock parent")
        finally:
            manager.KIMI_BINARY_PLATFORMS = original_platforms
    finally:
        temp.cleanup()


def expect_revalidation_rejected(manager: Any, target: Path, expected: str) -> None:
    try:
        executable = manager.revalidate_launch_executable(target)
    except manager.KimicodeSetupError as exc:
        if expected not in str(exc):
            raise ValueError(f"launch executable revalidation returned unstable error: {exc}") from exc
        return
    else:
        executable.close()
    raise ValueError(f"launch executable revalidation unexpectedly allowed {expected}")


def validate_launch_executable_error_regression(manager: Any) -> None:
    cases = (
        ("mode", lambda path: path.chmod(0o600), "mode must be 0700"),
        (
            "digest",
            lambda path: (path.write_bytes(b"#!/bin/sh\nprintf 'wrong\\n'\n"), path.chmod(0o700)),
            "digest does not match pinned binary",
        ),
        ("symlink", None, "must not be a symlink"),
    )
    for label, mutation, expected in cases:
        temp, target = make_isolated_target(f"launch-{label}-")
        try:
            manager.write_setup(
                target,
                manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
                manager.load_profile(manager.DEFAULT_PROFILE),
            )
            original_platforms = manager.KIMI_BINARY_PLATFORMS
            try:
                write_stub_software(manager, target)
                entrypoint = target / "bin" / manager.KIMI_COMMAND
                if label == "symlink":
                    replacement = target.parent / f"{target.name}-outside-kimi"
                    replacement.write_bytes(b"#!/bin/sh\nprintf 'outside\\n'\n")
                    replacement.chmod(0o700)
                    entrypoint.unlink()
                    entrypoint.symlink_to(replacement)
                elif mutation is not None:
                    mutation(entrypoint)
                expect_revalidation_rejected(manager, target, expected)
            finally:
                manager.KIMI_BINARY_PLATFORMS = original_platforms
        finally:
            temp.cleanup()


def expect_launch_rejected(manager: Any, argv: list[str], expected: str) -> None:
    try:
        manager.reject_managed_launch_overrides(argv)
    except manager.KimicodeSetupError as exc:
        if str(exc) != expected:
            raise ValueError(f"launch boundary error changed for {argv}: {exc}") from exc
        return
    raise ValueError(f"launch boundary allowed managed parser case: {argv}")


def validate_launch_boundary_regression(manager: Any) -> None:
    for flag in ("--config", "--profile", "--settings", "-C"):
        if flag in manager.FORBIDDEN_LAUNCH_FLAGS or flag in manager.FORBIDDEN_LAUNCH_VALUE_FLAGS:
            raise ValueError(f"launch boundary must not invent unsupported upstream flag: {flag}")
        manager.reject_managed_launch_overrides([flag])
    manager.reject_managed_launch_overrides(["-Cexample"])
    if manager.FORBIDDEN_LAUNCH_SHORT_VALUE_FLAGS != {"-S", "-m", "-p", "-r"}:
        raise ValueError("launch boundary native short value flags are out of sync")
    for command in (
        "__plugin_run_node",
        "acp",
        "doctor",
        "export",
        "login",
        "migrate",
        "provider",
        "update",
        "upgrade",
        "vis",
        "web",
    ):
        expect_launch_rejected(manager, [command], f"launch argument is managed by nddev-kimicode-app: {command}")
    expect_launch_rejected(manager, ["--add-dir", "/tmp/project"], "launch flag is managed by nddev-kimicode-app: --add-dir")
    expect_launch_rejected(manager, ["--add-dir=/tmp/project"], "launch flag is managed by nddev-kimicode-app: --add-dir")
    expect_launch_rejected(manager, ["--session=01HZ"], "launch flag is managed by nddev-kimicode-app: --session")
    expect_launch_rejected(manager, ["--resume=01HZ"], "launch flag is managed by nddev-kimicode-app: --resume")
    expect_launch_rejected(manager, ["-S01HZ"], "launch flag is managed by nddev-kimicode-app: -S")
    expect_launch_rejected(manager, ["-mmoonshot"], "launch flag is managed by nddev-kimicode-app: -m")
    expect_launch_rejected(manager, ["-phello"], "launch flag is managed by nddev-kimicode-app: -p")
    expect_launch_rejected(manager, ["-r01HZ"], "launch flag is managed by nddev-kimicode-app: -r")
    expect_launch_rejected(manager, ["-c"], "launch flag is managed by nddev-kimicode-app: -c")
    expect_launch_rejected(manager, ["-y"], "launch flag is managed by nddev-kimicode-app: -y")
    manager.reject_managed_launch_overrides(["-cnot-an-upstream-attached-value"])
    manager.reject_managed_launch_overrides(["-ynot-an-upstream-attached-value"])
    expect_launch_rejected(
        manager,
        ["--version", "--add-dir", "/tmp/project"],
        "launch flag is managed by nddev-kimicode-app: --add-dir",
    )


def validate_launch_workspace_scope_regression(manager: Any) -> None:
    temp, target = make_isolated_target("launch-workspace-")
    original_cwd = Path.cwd()
    try:
        manager.write_setup(
            target,
            manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
            manager.load_profile(manager.DEFAULT_PROFILE),
        )
        original_platforms = manager.KIMI_BINARY_PLATFORMS
        original_run = manager.subprocess.run
        try:
            write_stub_software(manager, target)
            explicit_workspace = Path(temp.name) / "explicit-workspace"
            default_workspace = Path(temp.name) / "default-workspace"
            explicit_workspace.mkdir(mode=0o700)
            default_workspace.mkdir(mode=0o700)
            seen_cwds: list[str] = []

            def fake_run(command: list[str], *, env: dict[str, str], cwd: str, check: bool) -> SimpleNamespace:
                if command[0] != str(target / "bin" / manager.KIMI_COMMAND):
                    raise ValueError("launch workspace regression did not hand off to target-owned executable")
                if env.get("KIMI_CODE_HOME") != str(target.resolve()):
                    raise ValueError("launch workspace regression lost target-scoped environment")
                seen_cwds.append(cwd)
                return SimpleNamespace(returncode=19)

            manager.subprocess.run = fake_run
            if manager.launch(target, ["--version"], workspace=str(explicit_workspace)) != 19:
                raise ValueError("explicit workspace launch did not forward child exit code")
            os.chdir(default_workspace)
            try:
                if manager.launch(target, ["--version"]) != 19:
                    raise ValueError("default workspace launch did not forward child exit code")
            finally:
                os.chdir(original_cwd)
            expected_cwds = [str(explicit_workspace.resolve()), str(default_workspace.resolve())]
            if seen_cwds != expected_cwds:
                raise ValueError(f"launch workspace cwd handoff changed: {seen_cwds}")

            relative = "relative-workspace"
            missing = Path(temp.name) / "missing-workspace"
            file_workspace = Path(temp.name) / "not-a-directory"
            file_workspace.write_text("not a directory\n", encoding="utf-8")
            symlink_workspace = Path(temp.name) / "workspace-link"
            symlink_workspace.symlink_to(explicit_workspace)
            invalid_cases = (
                (relative, "must be an absolute path"),
                (str(missing), "is missing"),
                (str(file_workspace), "must be a directory"),
                (str(symlink_workspace), "must not be a symlink"),
            )
            for raw_workspace, expected in invalid_cases:
                try:
                    manager.resolve_launch_workspace(raw_workspace)
                except manager.KimicodeSetupError as exc:
                    if expected not in str(exc):
                        raise ValueError(f"launch workspace error changed for {raw_workspace}: {exc}") from exc
                else:
                    raise ValueError(f"launch workspace unexpectedly accepted {raw_workspace}")
        finally:
            manager.subprocess.run = original_run
            manager.KIMI_BINARY_PLATFORMS = original_platforms
            os.chdir(original_cwd)
    finally:
        temp.cleanup()


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    validate_catalog()
    validate_metadata()
    validate_builder_toolkit()
    validate_runtime_regressions()
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
