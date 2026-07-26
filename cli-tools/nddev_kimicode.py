#!/usr/bin/env python3
"""Transactional setup manager for an explicit Kimi Code CLI target."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-kimicode-app"
SETUP_ROOT = ROOT / "setups"
BUILDER_ROOT = ROOT / "builder" / "nddev-builder"
SETUP_ORDER = ("safe", "balanced", "full-auto")
STAMP_NAME = "NDDEV-KIMICODE-SETUP.json"
BACKUP_NAME = "NDDEV-KIMICODE-BACKUP.json"
MANAGED_BEGIN = "# BEGIN NDDEV-KIMICODE MANAGED"
MANAGED_END = "# END NDDEV-KIMICODE MANAGED"
MD_MANAGED_BEGIN = "<!-- BEGIN NDDEV-KIMICODE MANAGED -->"
MD_MANAGED_END = "<!-- END NDDEV-KIMICODE MANAGED -->"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
MANAGED_MAX_BYTES = 8 * 1024 * 1024
METADATA_MAX_BYTES = 256 * 1024
CONTENT_MANAGED_PATHS = (
    "config.toml",
    "tui.toml",
    "AGENTS.md",
    "mcp.json",
    "skills/nddev-builder/SKILL.md",
    "agents/nddev-builder.md",
    "hooks/nddev-builder-pretooluse.mjs",
    "plugins/managed/nddev-builder/kimi.plugin.json",
)
MERGED_MARKER_PATHS = {"config.toml", "tui.toml", "AGENTS.md"}
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PROVIDER_SECRET_NAMES = {
    "KIMI_API_KEY",
    "KIMI_MODEL_API_KEY",
    "MOONSHOT_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GROK_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
}
PACKAGE_MANAGER_SECRET_NAMES = {
    "NODE_AUTH_TOKEN",
    "NPM_TOKEN",
    "BUN_AUTH_TOKEN",
    "npm_config_userconfig",
    "npm_config_prefix",
}
KIMI_PACKAGE_NAME = "@moonshot-ai/kimi-code"
KIMI_PACKAGE_VERSION = "0.29.1"
KIMI_COMMAND = "kimi"
KIMI_PACKAGE_BIN = "dist/main.mjs"
KIMI_POSTINSTALL_SCRIPT = "node scripts/postinstall.mjs"
KIMI_NODE_MIN_VERSION = (22, 19, 0)
KIMI_NPM_INTEGRITY = "sha512-c4/Ltsbc9ljEXdUB9EqCWka1raBg+PE0m/mfzcGrONcYghW7lSpG4N+ggfC1fAePwDexy9Dknnm/j3yxMuFtdw=="
KIMI_NPM_SHASUM = "11857306f80af8f46ff80ac1ad573570022bfc94"
KIMI_NPM_UNPACKED_SIZE = 36622517
KIMI_NPM_FILE_COUNT = 519
BUN_INSTALL_ARGV = [
    "add",
    "--global",
    "--exact",
    "--trust",
    f"{KIMI_PACKAGE_NAME}@{KIMI_PACKAGE_VERSION}",
]
SOFTWARE_STAMP_NAME = "NDDEV-KIMICODE-SOFTWARE.json"
SOFTWARE_DIR_NAME = ".nddev-kimicode-software"
SOFTWARE_CURRENT_NAME = "current"
SOFTWARE_STAGE_FRAGMENT = ".nddev-kimicode-software-stage"
SOFTWARE_MAX_BYTES = 128 * 1024 * 1024
SOFTWARE_MAX_PATHS = 20000
PROCESS_OUTPUT_MAX_BYTES = 64 * 1024
PROCESS_TIMEOUT_SECONDS = 120
KIMI_MAIN_RELATIVE = "install/global/node_modules/@moonshot-ai/kimi-code/dist/main.mjs"
SOFTWARE_STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "canonical_target",
    "package",
    "version",
    "npm_integrity",
    "npm_shasum",
    "npm_unpacked_size",
    "npm_file_count",
    "command",
    "package_bin",
    "entrypoint",
    "entrypoint_kind",
    "entrypoint_main",
    "installed_tree",
    "manager",
    "entrypoint_sha256",
    "package_main_sha256",
    "installed_tree_sha256",
    "node",
    "version_probe",
    "official_package_scripts",
    "installer",
}
SOFTWARE_STAMP_NODE_KEYS = {
    "path",
    "version",
    "version_stdout_sha256",
    "sha256",
    "min_version",
    "argv",
}
SOFTWARE_STAMP_PROBE_KEYS = {"argv", "environment", "stdout_stderr_sha256"}
SOFTWARE_STAMP_SCRIPT_KEYS = {"postinstall"}
SOFTWARE_STAMP_INSTALLER_KEYS = {"tool", "argv", "trust_reason", "env"}
SOFTWARE_STAMP_INSTALLER_ENV_KEYS = {
    "BUN_INSTALL_GLOBAL_DIR",
    "BUN_INSTALL_BIN",
    "BUN_INSTALL_CACHE_DIR",
    "HOME",
    "XDG_CONFIG_HOME",
    "TMPDIR",
}
FORBIDDEN_LAUNCH_FLAGS = {
    "--auto",
    "--auto-approve",
    "--plan",
    "--yolo",
    "--yes",
    "-p",
    "-y",
}
FORBIDDEN_LAUNCH_VALUE_FLAGS = {
    "--add-dir",
    "--agent",
    "--agent-file",
    "--model",
    "--output-format",
    "--prompt",
    "--skills-dir",
    "-m",
}
FORBIDDEN_LAUNCH_SUBCOMMANDS = {"upgrade"}


class KimicodeSetupError(Exception):
    """Safe user-facing lifecycle failure."""


@dataclass
class DirectoryTransaction:
    created: list[Path]

    def cleanup(self) -> None:
        for path in reversed(self.created):
            with contextlib.suppress(OSError):
                path.rmdir()


def fail(message: str) -> NoReturn:
    raise KimicodeSetupError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def toml_string(value: str) -> str:
    return json.dumps(value)


def toml_bool(value: bool) -> str:
    return "true" if value else "false"


def toml_array(values: list[str]) -> str:
    return "[" + ", ".join(toml_string(value) for value in values) + "]"


def require_absolute_target(raw: str) -> Path:
    target = Path(raw)
    if not target.is_absolute():
        fail("target must be an absolute path")
    if target.name in ("", ".", ".."):
        fail("target must name a directory")
    return target


def path_exists_no_follow(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def reject_symlink_ancestors(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode):
            fail(f"target path must not contain symlink ancestors: {current}")
        if not stat.S_ISDIR(info.st_mode):
            fail(f"target path ancestor must be a directory: {current}")


def is_current_owner(info: os.stat_result) -> bool:
    return not hasattr(os, "getuid") or info.st_uid == os.getuid()


def is_owner_private_directory(info: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(info.st_mode)
        and is_current_owner(info)
        and stat.S_IMODE(info.st_mode) == OWNER_DIRECTORY_MODE
    )


def stat_existing(path: Path, label: str) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        fail(f"{label} must not be a symlink")
    return info


def require_real_directory(path: Path, label: str) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    return info


def require_owner_private_directory(path: Path, label: str) -> os.stat_result:
    info = require_real_directory(path, label)
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must be private with mode 0700")
    return info


def ensure_directory_chain(path: Path, transaction: DirectoryTransaction, label: str) -> None:
    missing: list[Path] = []
    current = path
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            missing.append(current)
            parent = current.parent
            if parent == current:
                fail(f"{label} parent is missing")
            current = parent
            continue
        if stat.S_ISLNK(info.st_mode):
            fail(f"{label} must not contain symlink ancestors: {current}")
        if not stat.S_ISDIR(info.st_mode):
            fail(f"{label} must be a real directory: {current}")
        break
    for directory in reversed(missing):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE)
        directory.chmod(OWNER_DIRECTORY_MODE)
        transaction.created.append(directory)


def validate_target(
    target: Path,
    *,
    create: bool = False,
    transaction: DirectoryTransaction | None = None,
) -> Path:
    reject_symlink_ancestors(target)
    parent = target.parent
    info = stat_existing(target, "target")
    if info is None:
        canonical = target.resolve(strict=False)
        reject_symlink_ancestors(canonical)
        if not create:
            return canonical
        local_transaction = transaction or DirectoryTransaction([])
        try:
            ensure_directory_chain(parent, local_transaction, "target parent")
            require_owner_private_directory(parent, "target parent")
            target.mkdir(mode=OWNER_DIRECTORY_MODE)
            target.chmod(OWNER_DIRECTORY_MODE)
            local_transaction.created.append(target)
            canonical = target.resolve(strict=True)
            reject_symlink_ancestors(canonical)
            return canonical
        except BaseException:
            if transaction is None:
                local_transaction.cleanup()
            raise
    if not stat.S_ISDIR(info.st_mode):
        fail("target must be a real directory")
    require_owner_private_directory(target, "target")
    canonical = target.resolve(strict=True)
    reject_symlink_ancestors(canonical)
    return canonical


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-kimicode-backups"


def lock_path(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-kimicode.lock"


@contextlib.contextmanager
def target_lock(target: Path, *, create_parent: bool = False):
    transaction = DirectoryTransaction([])
    reject_symlink_ancestors(target)
    if create_parent:
        ensure_directory_chain(target.parent, transaction, "target parent")
    try:
        require_owner_private_directory(target.parent, "target parent")
    except BaseException:
        transaction.cleanup()
        raise
    path = lock_path(target)
    owner = path / "owner.json"
    try:
        path.mkdir(mode=OWNER_DIRECTORY_MODE)
        path.chmod(OWNER_DIRECTORY_MODE)
        owner.write_bytes(
            canonical_json({"schema_version": 1, "pid": os.getpid(), "target": str(target)})
        )
        owner.chmod(OWNER_FILE_MODE)
    except FileExistsError:
        transaction.cleanup()
        fail(f"target is locked: {path}")
    except BaseException:
        with contextlib.suppress(OSError):
            if path_exists_no_follow(owner) and not owner.is_symlink():
                owner.unlink()
            path.rmdir()
        transaction.cleanup()
        raise
    failed = False
    try:
        yield transaction
    except BaseException:
        failed = True
        raise
    finally:
        try:
            if path_exists_no_follow(owner) and not owner.is_symlink():
                owner.unlink()
            path.rmdir()
        except OSError as exc:
            raise KimicodeSetupError(f"target lock cleanup failed: {path}") from exc
        if failed:
            transaction.cleanup()


def safe_target_path(target: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        fail(f"invalid managed path: {relative}")
    return target / candidate


def ensure_real_parent(path: Path, target: Path) -> None:
    relative_parent = path.relative_to(target).parent
    current = target
    for part in relative_parent.parts:
        current = current / part
        info = stat_existing(current, f"managed directory {current}")
        if info is None:
            current.mkdir(mode=OWNER_DIRECTORY_MODE)
            continue
        if not stat.S_ISDIR(info.st_mode):
            fail(f"managed parent is not a directory: {current}")
        if not is_owner_private_directory(info):
            fail(f"managed parent must be private and owned by the current user: {current}")


def require_existing_managed_file(
    path: Path, label: str, *, max_bytes: int
) -> os.stat_result | None:
    info = stat_existing(path, label)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if info.st_size > max_bytes:
        fail(f"{label} is too large")
    return info


def open_regular_readonly(path: Path, label: str, *, max_bytes: int) -> tuple[int, os.stat_result]:
    info = require_existing_managed_file(path, label, max_bytes=max_bytes)
    if info is None:
        fail(f"{label} is missing")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} could not be opened safely: {exc}")
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            fail(f"{label} must be a regular file")
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            fail(f"{label} changed while opening")
        if opened.st_nlink != 1:
            fail(f"{label} must not be a hardlink")
        if opened.st_size > max_bytes:
            fail(f"{label} is too large")
    except BaseException:
        os.close(fd)
        raise
    return fd, opened


def read_existing_file(path: Path, *, max_bytes: int, label: str) -> bytes | None:
    if stat_existing(path, label) is None:
        return None
    fd, _ = open_regular_readonly(path, label, max_bytes=max_bytes)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        fail(f"{label} is too large")
    return data


def atomic_write(path: Path, data: bytes, target: Path) -> None:
    ensure_real_parent(path, target)
    require_existing_managed_file(path, str(path), max_bytes=MANAGED_MAX_BYTES)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
        path.chmod(OWNER_FILE_MODE)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def read_json_file(path: Path, *, max_bytes: int, label: str) -> dict[str, Any]:
    data = read_existing_file(path, max_bytes=max_bytes, label=label)
    if data is None:
        fail(f"{label} is missing")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"{label} is invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def canonical_target_readonly(target: Path) -> str:
    reject_symlink_ancestors(target)
    info = stat_existing(target, "target")
    if info is not None and not stat.S_ISDIR(info.st_mode):
        fail("target must be a real directory")
    if info is not None:
        require_owner_private_directory(target, "target")
    canonical = target.resolve(strict=False)
    reject_symlink_ancestors(canonical)
    return str(canonical)


def software_root(target: Path) -> Path:
    return target / SOFTWARE_DIR_NAME


def software_current(target: Path) -> Path:
    return software_root(target) / SOFTWARE_CURRENT_NAME


def software_stamp_path(target: Path) -> Path:
    return target / SOFTWARE_STAMP_NAME


def software_entrypoint(target: Path) -> Path:
    return target / "bin" / KIMI_COMMAND


def existing_path_label(path: Path, label: str) -> str | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    return label


def software_presence(target: Path) -> list[str]:
    labels = (
        (software_stamp_path(target), SOFTWARE_STAMP_NAME),
        (software_root(target), SOFTWARE_DIR_NAME),
        (software_current(target), f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}"),
        (software_entrypoint(target), "bin/kimi"),
    )
    present = [label for path, label in labels if existing_path_label(path, label) is not None]
    return sorted(present)


def package_manifest_path(root: Path) -> Path:
    return root / "install" / "global" / "node_modules" / "@moonshot-ai" / "kimi-code" / "package.json"


def validate_software_file(path: Path, label: str) -> os.stat_result:
    info = require_existing_managed_file(path, label, max_bytes=SOFTWARE_MAX_BYTES)
    if info is None:
        fail(f"{label} is missing")
    return info


def ensure_private_directory(
    path: Path,
    label: str,
    *,
    transaction: DirectoryTransaction | None = None,
) -> None:
    info = stat_existing(path, label)
    if info is None:
        require_owner_private_directory(path.parent, f"{label} parent")
        path.mkdir(mode=OWNER_DIRECTORY_MODE)
        path.chmod(OWNER_DIRECTORY_MODE)
        if transaction is not None:
            transaction.created.append(path)
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must be private with mode 0700")


def require_safe_partial_directory(path: Path, label: str) -> None:
    info = stat_existing(path, label)
    if info is None:
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must be private with mode 0700")


def require_safe_partial_file(path: Path, label: str, *, max_bytes: int) -> None:
    info = stat_existing(path, label)
    if info is None:
        return
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if info.st_size > max_bytes:
        fail(f"{label} is too large")


def validate_safe_partial_software_presence(target: Path) -> None:
    require_safe_partial_directory(software_entrypoint(target).parent, "bin")
    require_safe_partial_directory(software_root(target), "software root")
    require_safe_partial_directory(software_current(target), "current software tree")
    require_safe_partial_file(software_entrypoint(target), "Kimi Code wrapper", max_bytes=SOFTWARE_MAX_BYTES)
    require_safe_partial_file(software_stamp_path(target), SOFTWARE_STAMP_NAME, max_bytes=METADATA_MAX_BYTES)


def validate_pre_network_software_target(target: Path) -> None:
    require_safe_partial_directory(target, "target")
    validate_safe_partial_software_presence(target)


def exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    keys = set(value)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("extra " + ", ".join(extra))
        fail(f"{label} schema mismatch: {'; '.join(detail)}")
    return value


def file_sha256(path: Path, *, label: str) -> str:
    digest = hashlib.sha256()
    total = 0
    fd, _ = open_regular_readonly(path, label, max_bytes=SOFTWARE_MAX_BYTES)
    with os.fdopen(fd, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > SOFTWARE_MAX_BYTES:
                fail(f"{label} is too large")
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    info = stat_existing(root, "software tree")
    if info is None:
        fail("software tree is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail("software tree must be a directory")
    digest = hashlib.sha256()
    total = 0
    paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    if len(paths) > SOFTWARE_MAX_PATHS:
        fail("software tree has too many paths")
    for path in paths:
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            fail(f"software tree entry must not be a symlink: {relative}")
        if stat.S_ISDIR(info.st_mode):
            digest.update(f"D {relative} {stat.S_IMODE(info.st_mode):04o}\n".encode("utf-8"))
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"software tree entry must be a regular file: {relative}")
        if info.st_nlink != 1:
            fail(f"software tree entry must not be a hardlink: {relative}")
        if info.st_size > SOFTWARE_MAX_BYTES:
            fail(f"software tree entry is too large: {relative}")
        total += info.st_size
        if total > SOFTWARE_MAX_BYTES:
            fail("software tree is too large")
        digest.update(f"F {relative} {stat.S_IMODE(info.st_mode):04o} {info.st_size}\n".encode("utf-8"))
        fd, opened = open_regular_readonly(path, relative, max_bytes=SOFTWARE_MAX_BYTES)
        if opened.st_size != info.st_size:
            fail(f"software tree entry changed while hashing: {relative}")
        with os.fdopen(fd, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        digest.update(b"\n")
    return digest.hexdigest()


def load_package_manifest(root: Path) -> dict[str, Any]:
    manifest = read_json_file(
        package_manifest_path(root),
        max_bytes=METADATA_MAX_BYTES,
        label="Kimi Code package manifest",
    )
    if manifest.get("name") != KIMI_PACKAGE_NAME:
        fail("staged package name does not match Kimi Code")
    if manifest.get("version") != KIMI_PACKAGE_VERSION:
        fail("staged package version does not match the pinned Kimi Code release")
    package_bin = manifest.get("bin")
    if not isinstance(package_bin, dict) or package_bin.get(KIMI_COMMAND) != KIMI_PACKAGE_BIN:
        fail("staged package bin entry does not match the pinned Kimi Code release")
    scripts = manifest.get("scripts")
    if not isinstance(scripts, dict) or scripts.get("postinstall") != KIMI_POSTINSTALL_SCRIPT:
        fail("staged package postinstall script does not match the pinned Kimi Code release")
    return manifest


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def private_mode_for_source(info: os.stat_result) -> int:
    return 0o700 if stat.S_IMODE(info.st_mode) & 0o100 else OWNER_FILE_MODE


def copy_file_private(source: Path, destination: Path, label: str) -> None:
    fd, info = open_regular_readonly(source, label, max_bytes=SOFTWARE_MAX_BYTES)
    destination.parent.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    with os.fdopen(fd, "rb") as source_handle, destination.open("xb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
    destination.chmod(private_mode_for_source(info))


def materialized_source(path: Path, allowed_roots: tuple[Path, ...], label: str) -> Path:
    info = path.lstat()
    if not stat.S_ISLNK(info.st_mode):
        return path
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        fail(f"staged software symlink is broken: {label}")
    if not any(is_relative_to(resolved, root) for root in allowed_roots):
        fail(f"staged software symlink escapes persisted tree: {label}")
    resolved_info = resolved.lstat()
    if stat.S_ISLNK(resolved_info.st_mode):
        resolved = resolved.resolve(strict=True)
        resolved_info = resolved.lstat()
    if not stat.S_ISREG(resolved_info.st_mode):
        fail(f"staged software symlink must resolve to a regular file: {label}")
    return resolved


def copy_tree_sanitized(source: Path, destination: Path, allowed_roots: tuple[Path, ...]) -> None:
    source_info = stat_existing(source, "staged software tree")
    if source_info is None:
        fail("staged software tree is missing")
    if not stat.S_ISDIR(source_info.st_mode):
        fail("staged software tree must be a directory")
    paths = sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix())
    if len(paths) > SOFTWARE_MAX_PATHS:
        fail("staged software tree has too many paths")
    destination.mkdir(mode=OWNER_DIRECTORY_MODE)
    total = 0
    for path in paths:
        relative = path.relative_to(source)
        target_path = destination / relative
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            target_path.mkdir(mode=OWNER_DIRECTORY_MODE, exist_ok=True)
            continue
        if stat.S_ISLNK(info.st_mode):
            source_file = materialized_source(path, allowed_roots, relative.as_posix())
            source_info = validate_software_file(source_file, relative.as_posix())
            total += source_info.st_size
            if total > SOFTWARE_MAX_BYTES:
                fail("staged software tree is too large")
            copy_file_private(source_file, target_path, relative.as_posix())
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"staged software entry must be a regular file: {relative.as_posix()}")
        if info.st_nlink != 1:
            fail(f"staged software entry must not be a hardlink: {relative.as_posix()}")
        total += info.st_size
        if total > SOFTWARE_MAX_BYTES:
            fail("staged software tree is too large")
        copy_file_private(path, target_path, relative.as_posix())


def materialize_persisted_install(stage_workspace: Path, stage_current: Path) -> None:
    allowed_roots = (
        (stage_workspace / "install" / "global").resolve(strict=False),
        (stage_workspace / "bin").resolve(strict=False),
    )
    stage_current.mkdir(mode=OWNER_DIRECTORY_MODE)
    (stage_current / "install").mkdir(mode=OWNER_DIRECTORY_MODE)
    copy_tree_sanitized(
        stage_workspace / "install" / "global",
        stage_current / "install" / "global",
        allowed_roots,
    )
    copy_tree_sanitized(stage_workspace / "bin", stage_current / "bin", allowed_roots)


def parse_node_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def resolve_node_runtime(stage_workspace: Path) -> dict[str, str]:
    node = shutil.which("node", path=os.environ.get("PATH", "/usr/bin:/bin"))
    if node is None:
        fail("node >=22.19.0 is required to run Kimi Code CLI")
    node_path = str(Path(node).resolve(strict=False))
    home = stage_workspace / "node-probe-home"
    tmp = stage_workspace / "node-probe-tmp"
    home.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    tmp.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(tmp),
    }
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                [node_path, "--version"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                timeout=20,
            )
        except FileNotFoundError:
            fail("node executable was not found")
        except subprocess.TimeoutExpired:
            fail("node version probe timed out")
        stdout_text = read_process_output(stdout, "stdout").strip()
        stderr_text = read_process_output(stderr, "stderr").strip()
        if completed.returncode != 0:
            fail(f"node version probe failed with exit code {completed.returncode}: {stderr_text or stdout_text}")
        parsed = parse_node_version(stdout_text or stderr_text)
        if parsed is None or parsed < KIMI_NODE_MIN_VERSION:
            fail("node >=22.19.0 is required to run Kimi Code CLI")
    return {
        "path": node_path,
        "version": stdout_text or stderr_text,
        "version_stdout_sha256": sha256_bytes((stdout_text or stderr_text).encode("utf-8")),
        "sha256": file_sha256(Path(node_path), label="node runtime"),
        "min_version": ".".join(str(part) for part in KIMI_NODE_MIN_VERSION),
        "argv": [node_path, "--version"],
    }


def sh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def wrapper_bytes(*, node_path: str, main_path: Path) -> bytes:
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        f"exec {sh_single_quote(node_path)} {sh_single_quote(str(main_path))} \"$@\"\n"
    ).encode("utf-8")


def write_wrapper(path: Path, *, node_path: str, main_path: Path, target: Path) -> str:
    ensure_real_parent(path, target)
    require_existing_managed_file(path, "Kimi Code wrapper", max_bytes=METADATA_MAX_BYTES)
    data = wrapper_bytes(node_path=node_path, main_path=main_path)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    with temporary.open("xb") as handle:
        handle.write(data)
    temporary.chmod(0o700)
    os.replace(temporary, path)
    return file_sha256(path, label="Kimi Code wrapper")


def safe_process_env(stage_workspace: Path) -> dict[str, str]:
    home = stage_workspace / "home"
    xdg_config = stage_workspace / "xdg-config"
    cache = stage_workspace / "cache"
    tmp = stage_workspace / "tmp"
    for directory in (home, xdg_config, cache, tmp, stage_workspace / "install" / "global", stage_workspace / "bin"):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    env: dict[str, str] = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(xdg_config),
        "TMPDIR": str(tmp),
        "BUN_INSTALL_GLOBAL_DIR": str(stage_workspace / "install" / "global"),
        "BUN_INSTALL_BIN": str(stage_workspace / "bin"),
        "BUN_INSTALL_CACHE_DIR": str(cache),
    }
    return env


def read_process_output(handle: Any, label: str) -> str:
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(0)
    data = handle.read(PROCESS_OUTPUT_MAX_BYTES + 1)
    if isinstance(data, str):
        text = data
    else:
        text = data.decode("utf-8", errors="replace")
    if size > PROCESS_OUTPUT_MAX_BYTES:
        return text[:PROCESS_OUTPUT_MAX_BYTES] + f"\n[{label} truncated]\n"
    return text


def run_bun_install(stage_current: Path) -> None:
    command = ["bun", *BUN_INSTALL_ARGV]
    env = safe_process_env(stage_current)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                timeout=PROCESS_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            fail("bun command was not found on PATH")
        except subprocess.TimeoutExpired:
            fail("bun install timed out")
        if completed.returncode != 0:
            stderr_text = read_process_output(stderr, "stderr")
            stdout_text = read_process_output(stdout, "stdout")
            detail = (stderr_text or stdout_text).strip()
            fail(f"bun install failed with exit code {completed.returncode}: {detail}")


def run_stage_version_probe(
    stage_current: Path, stage_workspace: Path, node_runtime: dict[str, str]
) -> str:
    home = stage_workspace / "smoke-home"
    kimi_home = stage_workspace / "smoke-kimi-home"
    tmp = stage_workspace / "smoke-tmp"
    for directory in (home, kimi_home, tmp):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        "KIMI_CODE_HOME": str(kimi_home),
        "KIMI_DISABLE_TELEMETRY": "1",
        "KIMI_CODE_NO_AUTO_UPDATE": "1",
        "KIMI_DISABLE_CRON": "1",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(tmp),
    }
    wrapper = stage_workspace / "stage-wrapper" / KIMI_COMMAND
    wrapper.parent.mkdir(mode=OWNER_DIRECTORY_MODE)
    wrapper.write_bytes(
        wrapper_bytes(
            node_path=node_runtime["path"],
            main_path=stage_current / KIMI_MAIN_RELATIVE,
        )
    )
    wrapper.chmod(0o700)
    command = [str(wrapper), "--version"]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                command,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
                timeout=PROCESS_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            fail("staged kimi wrapper is missing")
        except subprocess.TimeoutExpired:
            fail("staged kimi version probe timed out")
        stdout_text = read_process_output(stdout, "stdout")
        stderr_text = read_process_output(stderr, "stderr")
        if completed.returncode != 0:
            detail = (stderr_text or stdout_text).strip()
            fail(f"staged kimi version probe failed with exit code {completed.returncode}: {detail}")
        output = (stdout_text + stderr_text).strip()
        if KIMI_PACKAGE_VERSION not in output:
            fail("staged kimi version probe did not report the pinned release")
        return sha256_bytes(output.encode("utf-8"))


def test_override_enabled(name: str) -> bool:
    return (
        os.environ.get("NDDEV_KIMICODE_ENABLE_TEST_OVERRIDES") == "1"
        and os.environ.get(name) == "1"
    )


def software_stamp(
    target: Path,
    *,
    entrypoint_digest: str,
    installed_tree_digest: str,
    package_main_digest: str,
    version_probe_digest: str,
    node_runtime: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(validate_target(target, create=False)),
        "package": KIMI_PACKAGE_NAME,
        "version": KIMI_PACKAGE_VERSION,
        "npm_integrity": KIMI_NPM_INTEGRITY,
        "npm_shasum": KIMI_NPM_SHASUM,
        "npm_unpacked_size": KIMI_NPM_UNPACKED_SIZE,
        "npm_file_count": KIMI_NPM_FILE_COUNT,
        "command": KIMI_COMMAND,
        "package_bin": KIMI_PACKAGE_BIN,
        "entrypoint": "bin/kimi",
        "entrypoint_kind": "node-wrapper",
        "entrypoint_main": f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}/{KIMI_MAIN_RELATIVE}",
        "installed_tree": f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}",
        "manager": "cli-tools/nddev_kimicode.py",
        "entrypoint_sha256": entrypoint_digest,
        "package_main_sha256": package_main_digest,
        "installed_tree_sha256": installed_tree_digest,
        "node": {
            "path": node_runtime["path"],
            "version": node_runtime["version"],
            "version_stdout_sha256": node_runtime["version_stdout_sha256"],
            "sha256": node_runtime["sha256"],
            "min_version": node_runtime["min_version"],
            "argv": node_runtime["argv"],
        },
        "version_probe": {
            "argv": ["bin/kimi", "--version"],
            "environment": {
                "HOME": "<stage>/smoke-home",
                "KIMI_CODE_HOME": "<stage>/smoke-kimi-home",
                "PATH": "/usr/bin:/bin",
                "TMPDIR": "<stage>/smoke-tmp",
            },
            "stdout_stderr_sha256": version_probe_digest,
        },
        "official_package_scripts": {
            "postinstall": KIMI_POSTINSTALL_SCRIPT,
        },
        "installer": {
            "tool": "bun",
            "argv": BUN_INSTALL_ARGV,
            "trust_reason": "official package @moonshot-ai/kimi-code@0.29.1 declares postinstall=node scripts/postinstall.mjs",
            "env": {
                "BUN_INSTALL_GLOBAL_DIR": "<stage>/install/global",
                "BUN_INSTALL_BIN": "<stage>/bin",
                "BUN_INSTALL_CACHE_DIR": "<stage>/cache",
                "HOME": "<stage>/home",
                "XDG_CONFIG_HOME": "<stage>/xdg-config",
                "TMPDIR": "<stage>/tmp",
            },
        },
    }


def read_software_stamp(target: Path) -> dict[str, Any] | None:
    path = software_stamp_path(target)
    info = stat_existing(path, SOFTWARE_STAMP_NAME)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode):
        fail("software stamp must be a regular file")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail("software stamp mode must be 0600")
    stamp = read_json_file(path, max_bytes=METADATA_MAX_BYTES, label=SOFTWARE_STAMP_NAME)
    exact_keys(stamp, SOFTWARE_STAMP_KEYS, SOFTWARE_STAMP_NAME)
    exact_keys(stamp["node"], SOFTWARE_STAMP_NODE_KEYS, "software stamp node")
    exact_keys(stamp["version_probe"], SOFTWARE_STAMP_PROBE_KEYS, "software stamp version_probe")
    exact_keys(
        stamp["official_package_scripts"],
        SOFTWARE_STAMP_SCRIPT_KEYS,
        "software stamp official_package_scripts",
    )
    installer = exact_keys(stamp["installer"], SOFTWARE_STAMP_INSTALLER_KEYS, "software stamp installer")
    exact_keys(installer["env"], SOFTWARE_STAMP_INSTALLER_ENV_KEYS, "software stamp installer env")
    if stamp.get("product_name") != PRODUCT_NAME:
        fail("software stamp belongs to another product")
    if stamp.get("canonical_target") != canonical_target_readonly(target):
        fail("software stamp is bound to a different canonical target")
    return stamp


def software_status_payload(target: Path) -> dict[str, Any]:
    canonical = canonical_target_readonly(target)
    payload: dict[str, Any] = {
        "installed": False,
        "current": False,
        "package": KIMI_PACKAGE_NAME,
        "version": None,
        "expected_version": KIMI_PACKAGE_VERSION,
        "command": KIMI_COMMAND,
        "executable": str(software_entrypoint(target)),
        "installed_tree": str(software_current(target)),
        "drift": [],
        "present": False,
        "presence": [],
        "canonical_target": canonical,
    }
    target_info = stat_existing(target, "target")
    if target_info is None:
        return payload
    if not stat.S_ISDIR(target_info.st_mode):
        fail("target must be a real directory")
    require_owner_private_directory(target, "target")
    presence = software_presence(target)
    payload["present"] = bool(presence)
    payload["presence"] = presence
    stamp = read_software_stamp(target)
    if stamp is None:
        return payload
    payload["installed"] = True
    payload["version"] = stamp.get("version")
    drift: list[str] = []
    try:
        root_info = stat_existing(software_root(target), "software root")
        if root_info is None:
            drift.append(SOFTWARE_DIR_NAME)
        elif not stat.S_ISDIR(root_info.st_mode):
            drift.append(SOFTWARE_DIR_NAME)
        elif stat.S_IMODE(root_info.st_mode) != OWNER_DIRECTORY_MODE:
            drift.append("software_root_mode")
        current_info = stat_existing(software_current(target), "current software tree")
        if current_info is None:
            drift.append(SOFTWARE_CURRENT_NAME)
        elif not stat.S_ISDIR(current_info.st_mode):
            drift.append(SOFTWARE_CURRENT_NAME)
        elif stat.S_IMODE(current_info.st_mode) != OWNER_DIRECTORY_MODE:
            drift.append("software_current_mode")
        entrypoint_info = validate_software_file(software_entrypoint(target), "Kimi Code wrapper")
        if stat.S_IMODE(entrypoint_info.st_mode) != 0o700:
            drift.append("entrypoint_mode")
        if stamp.get("schema_version") != 1:
            drift.append("schema_version")
        if stamp.get("product_name") != PRODUCT_NAME:
            drift.append("product_name")
        if stamp.get("build_version") != VERSION:
            drift.append("build_version")
        if stamp.get("canonical_target") != canonical:
            drift.append("canonical_target")
        load_package_manifest(software_current(target))
        entrypoint_digest = file_sha256(software_entrypoint(target), label="Kimi Code wrapper")
        package_main = software_current(target) / KIMI_MAIN_RELATIVE
        package_main_digest = file_sha256(package_main, label="Kimi Code package main")
        installed_tree_digest = tree_sha256(software_current(target))
        if stamp.get("package") != KIMI_PACKAGE_NAME:
            drift.append("package")
        if stamp.get("version") != KIMI_PACKAGE_VERSION:
            drift.append("version")
        if stamp.get("npm_integrity") != KIMI_NPM_INTEGRITY:
            drift.append("npm_integrity")
        if stamp.get("npm_shasum") != KIMI_NPM_SHASUM:
            drift.append("npm_shasum")
        if stamp.get("npm_unpacked_size") != KIMI_NPM_UNPACKED_SIZE:
            drift.append("npm_unpacked_size")
        if stamp.get("npm_file_count") != KIMI_NPM_FILE_COUNT:
            drift.append("npm_file_count")
        if stamp.get("command") != KIMI_COMMAND:
            drift.append("command")
        if stamp.get("package_bin") != KIMI_PACKAGE_BIN:
            drift.append("package_bin")
        if stamp.get("entrypoint") != "bin/kimi":
            drift.append("entrypoint")
        if stamp.get("entrypoint_kind") != "node-wrapper":
            drift.append("entrypoint_kind")
        if stamp.get("entrypoint_main") != f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}/{KIMI_MAIN_RELATIVE}":
            drift.append("entrypoint_main")
        if stamp.get("installed_tree") != f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}":
            drift.append("installed_tree")
        if stamp.get("manager") != "cli-tools/nddev_kimicode.py":
            drift.append("manager")
        if stamp.get("entrypoint_sha256") != entrypoint_digest:
            drift.append("entrypoint_sha256")
        if stamp.get("package_main_sha256") != package_main_digest:
            drift.append("package_main_sha256")
        if stamp.get("installed_tree_sha256") != installed_tree_digest:
            drift.append("installed_tree_sha256")
        installer = stamp.get("installer")
        expected_env = {
            "BUN_INSTALL_GLOBAL_DIR": "<stage>/install/global",
            "BUN_INSTALL_BIN": "<stage>/bin",
            "BUN_INSTALL_CACHE_DIR": "<stage>/cache",
            "HOME": "<stage>/home",
            "XDG_CONFIG_HOME": "<stage>/xdg-config",
            "TMPDIR": "<stage>/tmp",
        }
        if (
            not isinstance(installer, dict)
            or installer.get("tool") != "bun"
            or installer.get("argv") != BUN_INSTALL_ARGV
            or installer.get("env") != expected_env
            or installer.get("trust_reason")
            != "official package @moonshot-ai/kimi-code@0.29.1 declares postinstall=node scripts/postinstall.mjs"
        ):
            drift.append("installer")
        scripts = stamp.get("official_package_scripts")
        if not isinstance(scripts, dict) or scripts.get("postinstall") != KIMI_POSTINSTALL_SCRIPT:
            drift.append("official_package_scripts")
        probe = stamp.get("version_probe")
        expected_probe_env = {
            "HOME": "<stage>/smoke-home",
            "KIMI_CODE_HOME": "<stage>/smoke-kimi-home",
            "PATH": "/usr/bin:/bin",
            "TMPDIR": "<stage>/smoke-tmp",
        }
        if (
            not isinstance(probe, dict)
            or probe.get("argv") != ["bin/kimi", "--version"]
            or probe.get("environment") != expected_probe_env
            or not isinstance(probe.get("stdout_stderr_sha256"), str)
        ):
            drift.append("version_probe")
        node = stamp.get("node")
        if not isinstance(node, dict):
            drift.append("node")
        else:
            parsed = parse_node_version(str(node.get("version", "")))
            path = node.get("path")
            if (
                not isinstance(path, str)
                or not Path(path).is_absolute()
                or parsed is None
                or parsed < KIMI_NODE_MIN_VERSION
                or node.get("min_version") != "22.19.0"
                or node.get("argv") != [path, "--version"]
                or not isinstance(node.get("version_stdout_sha256"), str)
                or not isinstance(node.get("sha256"), str)
            ):
                drift.append("node")
            else:
                try:
                    node_digest = file_sha256(Path(path), label="node runtime")
                except KimicodeSetupError:
                    node_digest = ""
                if node_digest != node.get("sha256"):
                    drift.append("node_sha256")
                expected_wrapper = sha256_bytes(
                    wrapper_bytes(node_path=path, main_path=package_main)
                )
                if expected_wrapper != entrypoint_digest:
                    drift.append("entrypoint_wrapper")
    except KimicodeSetupError as exc:
        drift.append(str(exc))
    payload["drift"] = drift
    payload["current"] = not drift and stamp.get("version") == KIMI_PACKAGE_VERSION
    return payload


def software_precondition_state(target: Path) -> dict[str, Any]:
    validate_pre_network_software_target(target)
    try:
        payload = software_status_payload(target)
        if payload["present"] and not payload["current"]:
            validate_safe_partial_software_presence(target)
        return payload
    except KimicodeSetupError as exc:
        info = stat_existing(target, "target")
        if info is None or not stat.S_ISDIR(info.st_mode):
            raise
        presence = software_presence(target)
        if not presence:
            raise
        validate_pre_network_software_target(target)
        return {
            "installed": False,
            "current": False,
            "present": True,
            "presence": presence,
            "drift": [str(exc)],
            "package": KIMI_PACKAGE_NAME,
            "version": None,
            "expected_version": KIMI_PACKAGE_VERSION,
            "command": KIMI_COMMAND,
            "executable": str(software_entrypoint(target)),
            "installed_tree": str(software_current(target)),
            "canonical_target": canonical_target_readonly(target),
        }


def snapshot_software_entrypoint(target: Path) -> tuple[bytes | None, int | None]:
    path = software_entrypoint(target)
    info = require_existing_managed_file(path, "Kimi Code entrypoint", max_bytes=SOFTWARE_MAX_BYTES)
    if info is None:
        return None, None
    fd, opened = open_regular_readonly(path, "Kimi Code entrypoint", max_bytes=SOFTWARE_MAX_BYTES)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(SOFTWARE_MAX_BYTES + 1)
    if len(data) > SOFTWARE_MAX_BYTES:
        fail("Kimi Code entrypoint is too large")
    return data, private_mode_for_source(opened)


def restore_software_entrypoint(
    target: Path, data: bytes | None, mode: int | None, *, remove_empty_parent: bool
) -> None:
    path = software_entrypoint(target)
    if data is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        if remove_empty_parent:
            with contextlib.suppress(OSError):
                path.parent.rmdir()
        return
    ensure_real_parent(path, target)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    with temporary.open("xb") as handle:
        handle.write(data)
    temporary.chmod(mode or 0o700)
    os.replace(temporary, path)


def snapshot_software_stamp(target: Path) -> tuple[bytes | None, int | None]:
    path = software_stamp_path(target)
    info = require_existing_managed_file(path, SOFTWARE_STAMP_NAME, max_bytes=METADATA_MAX_BYTES)
    if info is None:
        return None, None
    fd, opened = open_regular_readonly(path, SOFTWARE_STAMP_NAME, max_bytes=METADATA_MAX_BYTES)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(METADATA_MAX_BYTES + 1)
    if len(data) > METADATA_MAX_BYTES:
        fail(f"{SOFTWARE_STAMP_NAME} is too large")
    return data, stat.S_IMODE(opened.st_mode)


def restore_software_stamp(target: Path, data: bytes | None, mode: int | None) -> None:
    path = software_stamp_path(target)
    if data is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    ensure_real_parent(path, target)
    require_existing_managed_file(path, SOFTWARE_STAMP_NAME, max_bytes=METADATA_MAX_BYTES)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    restore_mode = mode if mode is not None else OWNER_FILE_MODE
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, restore_mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
        path.chmod(restore_mode)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def atomic_copy_executable(source: Path, destination: Path, target: Path) -> str:
    info = validate_software_file(source, "staged Kimi Code entrypoint")
    require_existing_managed_file(destination, "Kimi Code entrypoint", max_bytes=SOFTWARE_MAX_BYTES)
    ensure_real_parent(destination, target)
    temporary = destination.with_name(f".{destination.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    fd, _ = open_regular_readonly(source, "staged Kimi Code entrypoint", max_bytes=SOFTWARE_MAX_BYTES)
    with os.fdopen(fd, "rb") as source_handle, temporary.open("xb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
    temporary.chmod(private_mode_for_source(info))
    os.replace(temporary, destination)
    return file_sha256(destination, label="Kimi Code entrypoint")


def install_or_update_software(target: Path, *, update: bool) -> dict[str, Any]:
    preflight = software_precondition_state(target)
    if preflight["current"]:
        return {
            "changed": False,
            "package": KIMI_PACKAGE_NAME,
            "version": KIMI_PACKAGE_VERSION,
            "command": KIMI_COMMAND,
            "executable": str(software_entrypoint(target)),
            "installed_tree": str(software_current(target)),
            "target": canonical_target_readonly(target),
        }
    if update and not preflight["present"]:
        fail("update-cli requires existing target-owned Kimi Code software presence")
    if not update and preflight["present"]:
        fail("install-cli found partial or non-current target-owned Kimi Code software; use update-cli")

    with target_lock(target, create_parent=not update) as transaction:
        validate_target(target, create=not update, transaction=transaction)
        status = software_precondition_state(target)
        if status["current"]:
            return {
                "changed": False,
                "package": KIMI_PACKAGE_NAME,
                "version": KIMI_PACKAGE_VERSION,
                "command": KIMI_COMMAND,
                "executable": str(software_entrypoint(target)),
                "installed_tree": str(software_current(target)),
                "target": str(validate_target(target, create=False)),
            }
        if update and not status["present"]:
            fail("update-cli requires existing target-owned Kimi Code software presence")
        if not update and status["present"]:
            fail("install-cli found partial or non-current target-owned Kimi Code software; use update-cli")

        parent = target.parent
        with tempfile.TemporaryDirectory(
            prefix=f".{target.name}{SOFTWARE_STAGE_FRAGMENT}.", dir=str(parent)
        ) as stage_raw, tempfile.TemporaryDirectory(
            prefix=f".{target.name}.nddev-kimicode-software-rollback.", dir=str(parent)
        ) as rollback_raw:
            stage_root = Path(stage_raw)
            rollback_root = Path(rollback_raw)
            stage_install = stage_root / "install-output"
            stage_current = stage_root / SOFTWARE_CURRENT_NAME
            run_bun_install(stage_install)
            load_package_manifest(stage_install)
            materialize_persisted_install(stage_install, stage_current)
            staged_entrypoint = stage_current / "bin" / KIMI_COMMAND
            validate_software_file(staged_entrypoint, "staged Kimi Code entrypoint")
            package_main = stage_current / KIMI_MAIN_RELATIVE
            validate_software_file(package_main, "staged Kimi Code package main")
            node_runtime = resolve_node_runtime(stage_root)
            version_probe_digest = run_stage_version_probe(stage_current, stage_root, node_runtime)
            package_main_digest = file_sha256(package_main, label="staged Kimi Code package main")
            installed_tree_digest = tree_sha256(stage_current)

            software_root_was_present = existing_path_label(software_root(target), SOFTWARE_DIR_NAME) is not None
            entrypoint_parent_was_present = (
                existing_path_label(software_entrypoint(target).parent, "bin") is not None
            )
            ensure_private_directory(software_root(target), "software root")
            current = software_current(target)
            rollback_current = rollback_root / SOFTWARE_CURRENT_NAME
            previous_entrypoint, previous_entrypoint_mode = snapshot_software_entrypoint(target)
            previous_stamp, previous_stamp_mode = snapshot_software_stamp(target)
            current_moved = False
            new_current_installed = False
            snapshot = {
                "entrypoint": previous_entrypoint,
                "entrypoint_mode": previous_entrypoint_mode,
                "stamp": previous_stamp,
                "stamp_mode": previous_stamp_mode,
            }
            try:
                current_info = stat_existing(current, "current software tree")
                if current_info is not None:
                    if not stat.S_ISDIR(current_info.st_mode):
                        fail("current software tree must be a directory")
                    current.rename(rollback_current)
                    current_moved = True
                stage_current.rename(current)
                new_current_installed = True
                entrypoint_digest = write_wrapper(
                    software_entrypoint(target),
                    node_path=node_runtime["path"],
                    main_path=current / KIMI_MAIN_RELATIVE,
                    target=target,
                )
                if test_override_enabled("NDDEV_KIMICODE_TEST_FAIL_AFTER_ENTRYPOINT"):
                    fail("injected software swap failure after entrypoint")
                stamp = software_stamp(
                    target,
                    entrypoint_digest=entrypoint_digest,
                    installed_tree_digest=installed_tree_digest,
                    package_main_digest=package_main_digest,
                    version_probe_digest=version_probe_digest,
                    node_runtime=node_runtime,
                )
                atomic_write(software_stamp_path(target), canonical_json(stamp), target)
                verified = software_status_payload(target)
                if not verified["current"]:
                    fail(f"installed software failed status verification: {', '.join(verified['drift'])}")
            except BaseException:
                if new_current_installed:
                    shutil.rmtree(current, ignore_errors=True)
                if current_moved:
                    rollback_current.rename(current)
                restore_software_entrypoint(
                    target,
                    snapshot["entrypoint"],
                    snapshot["entrypoint_mode"],
                    remove_empty_parent=not entrypoint_parent_was_present,
                )
                restore_software_stamp(target, snapshot["stamp"], snapshot["stamp_mode"])
                if not software_root_was_present:
                    with contextlib.suppress(OSError):
                        software_root(target).rmdir()
                raise
            return {
                "changed": True,
                "package": KIMI_PACKAGE_NAME,
                "version": KIMI_PACKAGE_VERSION,
                "command": KIMI_COMMAND,
                "executable": str(software_entrypoint(target)),
                "installed_tree": str(software_current(target)),
                "target": str(validate_target(target, create=False)),
            }


def load_setup(setup_id: str) -> dict[str, Any]:
    if not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id}")
    path = SETUP_ROOT / setup_id / "setup.json"
    if not path.is_file():
        fail(f"unknown setup: {setup_id}")
    setup = read_json_file(path, max_bytes=METADATA_MAX_BYTES, label=f"setup {setup_id}")
    if setup.get("id") != setup_id:
        fail(f"setup id mismatch in {path}")
    return setup


def list_setups() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for setup_id in SETUP_ORDER:
        setup = load_setup(setup_id)
        items.append(
            {
                "id": setup["id"],
                "display_name": setup["display_name"],
                "description": setup["description"],
                "permission_mode": setup["permission_mode"],
                "plan_mode": setup["plan_mode"],
                "nddev_builder_default": setup["nddev_builder_default"],
            }
        )
    return items


def marker_pair(relative: str) -> tuple[str, str]:
    if relative == "AGENTS.md":
        return MD_MANAGED_BEGIN, MD_MANAGED_END
    return MANAGED_BEGIN, MANAGED_END


def extract_managed_block(relative: str, text: str) -> str | None:
    begin_marker, end_marker = marker_pair(relative)
    begin = text.find(begin_marker)
    if begin < 0:
        return None
    end = text.find(end_marker, begin)
    if end < 0:
        return None
    end += len(end_marker)
    if end < len(text) and text[end : end + 1] == "\n":
        end += 1
    return text[begin:end]


def merge_managed_block(relative: str, existing: bytes | None, block: str) -> bytes:
    text = existing.decode("utf-8") if existing else ""
    current = extract_managed_block(relative, text)
    if current is None:
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix:
            prefix += "\n"
        return (prefix + block).encode("utf-8")
    return text.replace(current, block).encode("utf-8")


def render_config(target: Path, setup: dict[str, Any]) -> str:
    canonical = validate_target(target, create=False)
    skill_dir = str((canonical / "skills").resolve())
    agent_dir = str((canonical / "agents").resolve())
    mcp_config = str((canonical / "mcp.json").resolve())
    hook_command = "node " + str((canonical / "hooks" / "nddev-builder-pretooluse.mjs").resolve())
    return (
        f"{MANAGED_BEGIN}\n"
        "# Managed by nddev-kimicode-app. Edit outside this block to preserve local state.\n"
        f"default_permission_mode = {toml_string(str(setup['permission_mode']))}\n"
        f"default_plan_mode = {toml_bool(bool(setup['plan_mode']))}\n"
        f"max_steps_per_turn = {int(setup['max_steps_per_turn'])}\n"
        f"max_running_tasks = {int(setup['max_running_tasks'])}\n"
        f"mcp_config_file = {toml_string(mcp_config)}\n"
        f"extra_skill_dirs = {toml_array([skill_dir])}\n"
        f"extra_agent_dirs = {toml_array([agent_dir])}\n"
        "\n"
        "[permissions]\n"
        f"allow = {toml_array(list(setup['permission_allow']))}\n"
        f"deny = {toml_array(list(setup['permission_deny']))}\n"
        "\n"
        "[plugins]\n"
        'enabled = ["nddev-builder"]\n'
        "\n"
        "[[hooks]]\n"
        'event = "PreToolUse"\n'
        'matcher = "Bash"\n'
        f"command = {toml_string(hook_command)}\n"
        "timeout = 5\n"
        f"{MANAGED_END}\n"
    )


def render_tui(setup: dict[str, Any]) -> str:
    return (
        f"{MANAGED_BEGIN}\n"
        "# Managed by nddev-kimicode-app.\n"
        f"default_permission_mode = {toml_string(str(setup['permission_mode']))}\n"
        f"default_plan_mode = {toml_bool(bool(setup['plan_mode']))}\n"
        f"{MANAGED_END}\n"
    )


def render_agents_block(setup: dict[str, Any]) -> str:
    return (
        f"{MD_MANAGED_BEGIN}\n"
        "\n"
        "# NDDev Kimi Code Setup\n"
        "\n"
        f"This Kimi Code home is managed as the `{setup['id']}` setup by nddev-kimicode-app.\n"
        "Use the managed nddev-builder skill and agent for setup artifact changes. Use only\n"
        "current Kimi Code CLI surfaces confirmed in the public baseline: AGENTS.md, skills,\n"
        "agents, hooks, MCP config, and plugin manifests.\n"
        "\n"
        f"{MD_MANAGED_END}\n"
    )


def builder_source(relative: str) -> bytes:
    path = BUILDER_ROOT / relative
    if not path.is_file():
        fail(f"builder source missing: {relative}")
    data = path.read_bytes()
    if len(data) > MANAGED_MAX_BYTES:
        fail(f"builder source too large: {relative}")
    return data


def desired_files(target: Path, setup: dict[str, Any]) -> dict[str, bytes]:
    existing_config = read_existing_file(
        target / "config.toml", max_bytes=MANAGED_MAX_BYTES, label="config.toml"
    )
    existing_tui = read_existing_file(
        target / "tui.toml", max_bytes=MANAGED_MAX_BYTES, label="tui.toml"
    )
    existing_agents = read_existing_file(
        target / "AGENTS.md", max_bytes=MANAGED_MAX_BYTES, label="AGENTS.md"
    )
    return {
        "config.toml": merge_managed_block(
            "config.toml", existing_config, render_config(target, setup)
        ),
        "tui.toml": merge_managed_block("tui.toml", existing_tui, render_tui(setup)),
        "AGENTS.md": merge_managed_block("AGENTS.md", existing_agents, render_agents_block(setup)),
        "mcp.json": canonical_json({"mcpServers": {}}),
        "skills/nddev-builder/SKILL.md": builder_source("skills/nddev-builder/SKILL.md"),
        "agents/nddev-builder.md": builder_source("agents/nddev-builder.md"),
        "hooks/nddev-builder-pretooluse.mjs": builder_source("hooks/nddev-builder-pretooluse.mjs"),
        "plugins/managed/nddev-builder/kimi.plugin.json": builder_source("kimi.plugin.json"),
    }


def managed_digest_for_bytes(relative: str, data: bytes) -> str:
    if relative in MERGED_MARKER_PATHS:
        block = extract_managed_block(relative, data.decode("utf-8"))
        if block is None:
            return ""
        return sha256_bytes(block.encode("utf-8"))
    return sha256_bytes(data)


def current_managed_digest(target: Path, relative: str) -> str | None:
    data = read_existing_file(
        safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
    )
    if data is None:
        return None
    digest = managed_digest_for_bytes(relative, data)
    return digest or None


def stamp_path(target: Path) -> Path:
    return target / STAMP_NAME


def read_stamp(target: Path) -> dict[str, Any] | None:
    path = stamp_path(target)
    info = stat_existing(path, STAMP_NAME)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode):
        fail("stamp must be a regular file")
    if info.st_nlink != 1:
        fail("stamp must not be a hardlink")
    stamp = read_json_file(path, max_bytes=METADATA_MAX_BYTES, label=STAMP_NAME)
    if stamp.get("product_name") != PRODUCT_NAME:
        fail("stamp belongs to another product")
    canonical = str(validate_target(target, create=False))
    if stamp.get("canonical_target") != canonical:
        fail("stamp is bound to a different canonical target")
    return stamp


def drift_for_stamp(target: Path, stamp: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    managed = stamp.get("managed_files")
    if not isinstance(managed, dict):
        fail("stamp managed_files is invalid")
    for relative, expected in managed.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            fail("stamp managed file digest is invalid")
        current = current_managed_digest(target, relative)
        if current != expected:
            drift.append(relative)
    return drift


def status_payload(target: Path) -> dict[str, Any]:
    canonical = validate_target(target, create=False)
    if stat_existing(target, "target") is None:
        return {
            "state": "absent",
            "managed": False,
            "canonical_target": str(canonical),
            "setup_id": None,
            "drift": [],
        }
    require_owner_private_directory(target, "target")
    stamp = read_stamp(target)
    if stamp is None:
        return {
            "state": "unmanaged",
            "managed": False,
            "canonical_target": str(canonical),
            "setup_id": None,
            "drift": [],
        }
    return {
        "state": "managed",
        "managed": True,
        "canonical_target": str(canonical),
        "setup_id": stamp["setup_id"],
        "build_version": stamp["build_version"],
        "drift": drift_for_stamp(target, stamp),
        "managed_files": sorted(stamp["managed_files"]),
    }


def snapshot_files(target: Path) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    for relative in (*CONTENT_MANAGED_PATHS, STAMP_NAME):
        snapshot[relative] = read_existing_file(
            safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
        )
    return snapshot


def restore_snapshot(target: Path, snapshot: dict[str, bytes | None]) -> None:
    for relative, data in snapshot.items():
        path = safe_target_path(target, relative)
        if data is None:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            continue
        atomic_write(path, data, target)
    prune_empty_managed_dirs(target)


def choose_backup_slot(pool: Path) -> int:
    ensure_private_directory(pool, "backup pool")
    for slot in range(10):
        if not path_exists_no_follow(pool / str(slot)):
            return slot
    return min(range(10), key=lambda item: (pool / str(item)).lstat().st_mtime_ns)


def create_backup(target: Path, stamp: dict[str, Any]) -> int:
    pool = backup_pool(target)
    slot = choose_backup_slot(pool)
    slot_dir = pool / str(slot)
    slot_info = stat_existing(slot_dir, f"backup slot {slot}")
    if slot_info is not None:
        if not stat.S_ISDIR(slot_info.st_mode):
            fail(f"backup slot {slot} must be a directory")
        shutil.rmtree(slot_dir)
    slot_dir.mkdir(mode=OWNER_DIRECTORY_MODE)
    files: dict[str, Any] = {}
    for relative in (*CONTENT_MANAGED_PATHS, STAMP_NAME):
        data = read_existing_file(
            safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
        )
        files[relative] = None if data is None else base64.b64encode(data).decode("ascii")
    envelope = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(validate_target(target, create=False)),
        "source_setup_id": stamp["setup_id"],
        "created_at": int(time.time()),
        "files": files,
    }
    atomic_write(slot_dir / BACKUP_NAME, canonical_json(envelope), slot_dir)
    return slot


def build_stamp(target: Path, setup_id: str, files: dict[str, bytes]) -> dict[str, Any]:
    managed = {
        relative: managed_digest_for_bytes(relative, data) for relative, data in files.items()
    }
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "canonical_target": str(validate_target(target, create=False)),
        "managed_files": managed,
    }


def write_setup(
    target: Path, setup: dict[str, Any], *, require_existing: bool = False
) -> dict[str, Any]:
    with target_lock(target, create_parent=not require_existing) as transaction:
        validate_target(target, create=not require_existing, transaction=transaction)
        current = read_stamp(target)
        if require_existing and current is None:
            fail("switch requires an already managed target")
        if current is not None:
            drift = drift_for_stamp(target, current)
            if drift:
                fail(f"managed target has drift: {', '.join(drift)}")
        files = desired_files(target, setup)
        desired_stamp = build_stamp(target, setup["id"], files)
        changed = [
            relative
            for relative, data in files.items()
            if current_managed_digest(target, relative) != managed_digest_for_bytes(relative, data)
        ]
        backup_slot = None
        if current is not None and current["setup_id"] != setup["id"]:
            backup_slot = create_backup(target, current)
        snapshot = snapshot_files(target)
        try:
            for relative, data in files.items():
                atomic_write(safe_target_path(target, relative), data, target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        return {
            "setup_id": setup["id"],
            "changed": changed,
            "backup_slot": backup_slot,
            "target": str(validate_target(target, create=False)),
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    if slot < 0 or slot > 9:
        fail("backup slot must be between 0 and 9")
    with target_lock(target, create_parent=True) as transaction:
        validate_target(target, create=True, transaction=transaction)
        envelope_path = backup_pool(target) / str(slot) / BACKUP_NAME
        envelope = read_json_file(envelope_path, max_bytes=METADATA_MAX_BYTES, label=BACKUP_NAME)
        if envelope.get("product_name") != PRODUCT_NAME:
            fail("backup belongs to another product")
        if envelope.get("canonical_target") != str(validate_target(target, create=False)):
            fail("backup is bound to a different canonical target")
        files = envelope.get("files")
        if not isinstance(files, dict):
            fail("backup files are invalid")
        snapshot = snapshot_files(target)
        try:
            for relative in (*CONTENT_MANAGED_PATHS, STAMP_NAME):
                encoded = files.get(relative)
                path = safe_target_path(target, relative)
                if encoded is None:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
                    continue
                if not isinstance(encoded, str):
                    fail("backup file payload is invalid")
                atomic_write(path, base64.b64decode(encoded.encode("ascii")), target)
            prune_empty_managed_dirs(target)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        restored_stamp = read_stamp(target)
        return {
            "setup_id": None if restored_stamp is None else restored_stamp["setup_id"],
            "backup_slot": slot,
            "target": str(validate_target(target, create=False)),
        }


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target):
        validate_target(target, create=False)
        stamp = read_stamp(target)
        if stamp is None:
            return {"removed_setup_id": None, "target": str(validate_target(target, create=False))}
        drift = drift_for_stamp(target, stamp)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        removed_setup_id = stamp["setup_id"]
        snapshot = snapshot_files(target)
        try:
            for relative in CONTENT_MANAGED_PATHS:
                path = safe_target_path(target, relative)
                if relative in MERGED_MARKER_PATHS:
                    remove_managed_block_from_target(target, relative)
                else:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
            with contextlib.suppress(FileNotFoundError):
                stamp_path(target).unlink()
            prune_empty_managed_dirs(target)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        return {
            "removed_setup_id": removed_setup_id,
            "target": str(validate_target(target, create=False)),
        }


def remove_managed_block_from_target(target: Path, relative: str) -> None:
    path = safe_target_path(target, relative)
    data = read_existing_file(path, max_bytes=MANAGED_MAX_BYTES, label=relative)
    if data is None:
        return
    text = data.decode("utf-8")
    block = extract_managed_block(relative, text)
    if block is None:
        return
    updated = text.replace(block, "")
    if updated.strip():
        atomic_write(path, updated.encode("utf-8"), target)
    else:
        path.unlink()


def prune_empty_managed_dirs(target: Path) -> None:
    candidates: set[Path] = set()
    for relative in CONTENT_MANAGED_PATHS:
        directory = safe_target_path(target, relative).parent
        while directory != target and target in directory.parents:
            candidates.add(directory)
            directory = directory.parent
    directories = sorted(candidates, key=lambda item: len(item.parts), reverse=True)
    for directory in directories:
        with contextlib.suppress(OSError):
            directory.rmdir()


def plan_payload(target: Path, setup: dict[str, Any]) -> dict[str, Any]:
    status = status_payload(target)
    operation = "install"
    backup_required = False
    if status["managed"]:
        operation = "update" if status["setup_id"] == setup["id"] else "switch"
        backup_required = status["setup_id"] != setup["id"]
    return {
        "operation": operation,
        "setup_id": setup["id"],
        "target": str(validate_target(target, create=False)),
        "current_setup_id": status["setup_id"],
        "drift": status["drift"],
        "backup_required": backup_required,
        "mutates": False,
    }


def reject_managed_launch_overrides(child_args: list[str]) -> None:
    index = 0
    while index < len(child_args):
        arg = child_args[index]
        if index == 0 and arg in FORBIDDEN_LAUNCH_SUBCOMMANDS:
            fail(f"launch argument is managed by nddev-kimicode-app: {arg}")
        if arg in FORBIDDEN_LAUNCH_FLAGS:
            fail(f"launch flag is managed by nddev-kimicode-app: {arg}")
        if arg in FORBIDDEN_LAUNCH_VALUE_FLAGS:
            fail(f"launch flag is managed by nddev-kimicode-app: {arg}")
        for flag in FORBIDDEN_LAUNCH_VALUE_FLAGS:
            if flag.startswith("--") and arg.startswith(flag + "="):
                fail(f"launch flag is managed by nddev-kimicode-app: {flag}")
        if arg.startswith("-m") and arg != "-m":
            fail("launch flag is managed by nddev-kimicode-app: -m")
        index += 1


def prepare_launch_invocation(target: Path, child_args: list[str]) -> tuple[list[str], dict[str, str]]:
    reject_managed_launch_overrides(child_args)
    with target_lock(target):
        status = status_payload(target)
        if not status["managed"]:
            fail("launch requires a managed target")
        if status["drift"]:
            fail(f"managed target has drift: {', '.join(status['drift'])}")
        software = software_status_payload(target)
        if not software["current"]:
            drift = software.get("drift") or ["target-owned Kimi Code package is not installed"]
            fail(f"launch requires current target-owned Kimi Code package: {', '.join(drift)}")
        canonical = validate_target(target, create=False)
        runtime = canonical / ".nddev-kimicode-runtime"
        home = runtime / "home"
        ensure_private_directory(runtime, "runtime root")
        ensure_private_directory(home, "runtime home")
        executable = software_entrypoint(canonical)
        child_env: dict[str, str] = {
            "HOME": str(home),
            "KIMI_CODE_HOME": str(canonical),
            "KIMI_DISABLE_TELEMETRY": "1",
            "KIMI_CODE_NO_AUTO_UPDATE": "1",
            "KIMI_DISABLE_CRON": "1",
            "PATH": "/usr/bin:/bin",
        }
        return [str(executable), *child_args], child_env


def launch(target: Path, child_args: list[str]) -> int:
    command, child_env = prepare_launch_invocation(target, child_args)
    try:
        completed = subprocess.run(command, env=child_env, check=False)
    except FileNotFoundError:
        fail("target-owned kimi executable is missing")
    return int(completed.returncode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")
    for name in ("status", "remove"):
        command = subparsers.add_parser(name)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")
    software_status = subparsers.add_parser("software-status")
    software_status.add_argument("--target", required=True)
    software_status.add_argument("--json", action="store_true")
    for name in ("install-cli", "update-cli"):
        command = subparsers.add_parser(name)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")
    for name in ("plan", "install", "switch"):
        command = subparsers.add_parser(name)
        command.add_argument("--setup", required=True)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True, type=int)
    restore.add_argument("--target", required=True)
    restore.add_argument("--json", action="store_true")
    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--target", required=True)
    launch_parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "list":
        items = list_setups()
        emit({"setups": [item["id"] for item in items], "items": items}, as_json=args.json)
        return 0
    if args.command == "status":
        emit(status_payload(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "software-status":
        emit(software_status_payload(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "install-cli":
        emit(
            install_or_update_software(require_absolute_target(args.target), update=False),
            as_json=args.json,
        )
        return 0
    if args.command == "update-cli":
        emit(
            install_or_update_software(require_absolute_target(args.target), update=True),
            as_json=args.json,
        )
        return 0
    if args.command == "plan":
        target = require_absolute_target(args.target)
        emit(plan_payload(target, load_setup(args.setup)), as_json=args.json)
        return 0
    if args.command == "install":
        target = require_absolute_target(args.target)
        emit(write_setup(target, load_setup(args.setup)), as_json=args.json)
        return 0
    if args.command == "switch":
        target = require_absolute_target(args.target)
        emit(write_setup(target, load_setup(args.setup), require_existing=True), as_json=args.json)
        return 0
    if args.command == "restore":
        target = require_absolute_target(args.target)
        emit(restore_backup(target, args.backup), as_json=args.json)
        return 0
    if args.command == "remove":
        target = require_absolute_target(args.target)
        emit(remove_setup(target), as_json=args.json)
        return 0
    if args.command == "launch":
        child_args = list(args.child_args)
        if child_args[:1] == ["--"]:
            child_args = child_args[1:]
        return launch(require_absolute_target(args.target), child_args)
    fail(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return dispatch(args)
    except KimicodeSetupError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
