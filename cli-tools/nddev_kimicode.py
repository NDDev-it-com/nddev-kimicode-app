#!/usr/bin/env python3
"""Transactional setup manager for an explicit Kimi Code CLI target."""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-kimicode-app"

SETUP_ROOT = ROOT / "setups"
PROFILE_ROOT = ROOT / "profiles"
BUILDER_ROOT = ROOT / "builder" / "nddev-builder"
CONTENT_SETUP_ORDER = ("nddev-builder",)
PROFILE_ORDER = ("safe", "full-auto")
DEFAULT_CONTENT_SETUP = "nddev-builder"
DEFAULT_PROFILE = "full-auto"

STAMP_NAME = "NDDEV-KIMICODE-SETUP.json"
BACKUP_NAME = "NDDEV-KIMICODE-BACKUP.json"
LOCK_DIR_NAME = ".nddev-kimicode-lock"
LOCK_NAME = "lifecycle.lock"
EXTERNAL_LOCK_ROOT_NAME = f"{PRODUCT_NAME}.{os.getuid() if hasattr(os, 'getuid') else 'nouid'}.locks"
EXTERNAL_LOCK_NAMESPACE = f"{PRODUCT_NAME}:external-bootstrap:v1"
EXTERNAL_LOCK_SUFFIX = "external.lock"
PRODUCT_LOCK_NAME = "product.lock"
TARGET_LOCK_ROOT_NAME = "targets"
LOCK_STAGE_ALIAS_MAX = 4
LOCK_PARENT_ENTRY_MAX = 256
READ_LIFECYCLE_MAX_ATTEMPTS = 2
AT_FDCWD_BY_SYSTEM = {"darwin": -2, "linux": -100}
RENAME_EXCL_DARWIN = 0x00000004
RENAME_NOREPLACE_LINUX = 1
RENAMEAT2_SYSCALL_BY_MACHINE = {
    "amd64": 316,
    "x86_64": 316,
    "aarch64": 276,
    "arm64": 276,
}
CURRENT_SETUP_SCHEMA = 2
LEGACY_SETUP_SCHEMA = 1
MANAGED_BEGIN = "# BEGIN NDDEV-KIMICODE MANAGED"
MANAGED_END = "# END NDDEV-KIMICODE MANAGED"
MD_MANAGED_BEGIN = "<!-- BEGIN NDDEV-KIMICODE MANAGED -->"
MD_MANAGED_END = "<!-- END NDDEV-KIMICODE MANAGED -->"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
MANAGED_MAX_BYTES = 8 * 1024 * 1024
METADATA_MAX_BYTES = 256 * 1024
CONTENT_MANAGED_BASE_PATHS = (
    "config.toml",
    "tui.toml",
    "AGENTS.md",
    "mcp.json",
    "agents/nddev-builder.md",
    "hooks/nddev-builder-pretooluse.py",
)
MERGED_MARKER_PATHS = {"config.toml", "tui.toml", "AGENTS.md"}
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")

KIMI_PACKAGE_NAME = "@moonshot-ai/kimi-code"
KIMI_PACKAGE_VERSION = "0.29.2"
KIMI_COMMAND = "kimi"
KIMI_GITHUB_RELEASE_URL = (
    "https://github.com/MoonshotAI/kimi-code/releases/tag/%40moonshot-ai/kimi-code%400.29.2"
)
KIMI_GITHUB_RELEASE_ID = 360239506
KIMI_GIT_TAG = "@moonshot-ai/kimi-code@0.29.2"
KIMI_GIT_TAG_OBJECT = "57503c7c4d854f2c66ea32e10cba28b2c5715e9c"
KIMI_GIT_COMMIT = "8a45f10eddbb35c317047e82e567cdb59a220b4f"
KIMI_NPM_INTEGRITY = "sha512-NmID/2+rCbZXvnQIBZxZlLzeUjETjb1BPzfkUoVs6AhQv9xuGKLzQvcUJB+yksRZnWE+ikLMWyIn75rVfMMP4w=="
KIMI_NPM_SHASUM = "9e8da7ca4e822048a28d1e12ff46c8ea5ecb23ac"
KIMI_NPM_METADATA_SHA256 = "38afbc3a2ddc0c5d0e4b4a3067c3ad82f1a749ad917ec7adcaea1129cd0e036f"
KIMI_NPM_UNPACKED_SIZE = 38348444
KIMI_NPM_FILE_COUNT = 519
KIMI_INSTALL_SCRIPT_URL = "https://code.kimi.com/kimi-code/install.sh"
KIMI_INSTALL_SCRIPT_SHA256 = "638927825e96825edbb563de5e0cb06f8a0551c53e026ade8b717b0f25cb83d2"
KIMI_LATEST_URL = "https://code.kimi.com/kimi-code/latest"
KIMI_BINARY_BASE = "https://code.kimi.com/kimi-code/binaries"
KIMI_BINARY_MANIFEST_URL = f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/manifest.json"
KIMI_BINARY_MANIFEST_SHA256 = "6057703f6430964741198c81617737bcec917082d1ce4aadd7a1b8c29787ae9b"
KIMI_BINARY_PLATFORMS = {
    "darwin-arm64": {
        "filename": "kimi-code-darwin-arm64",
        "checksum": "25dc8b14f8bb5ef98470577265b1e9c95892c168f34e9639c5f63b48d4ece6fb",
    },
    "darwin-x64": {
        "filename": "kimi-code-darwin-x64",
        "checksum": "fe59f14cab74971768377e586bf3be30c1ca04079c058d4b492827ca4dfd6b16",
    },
    "linux-arm64": {
        "filename": "kimi-code-linux-arm64",
        "checksum": "5fb64e74eeec0b3900732cfbc3679cc505beb51aa323f486154fd79b0e20b26a",
    },
    "linux-x64": {
        "filename": "kimi-code-linux-x64",
        "checksum": "f9977d259ed36019793cadf04b1f0343f12aaebfa76f90fa26cd3b02be671231",
    },
}

SOFTWARE_STAMP_NAME = "NDDEV-KIMICODE-SOFTWARE.json"
SOFTWARE_DIR_NAME = ".nddev-kimicode-software"
SOFTWARE_CURRENT_NAME = "current"
SOFTWARE_STAGE_FRAGMENT = ".nddev-kimicode-software-stage"
SOFTWARE_ROLLBACK_FRAGMENT = ".nddev-kimicode-software-rollback"
CURRENT_SOFTWARE_SCHEMA = 2
LEGACY_SOFTWARE_SCHEMA = 1
SOFTWARE_MAX_BYTES = 160 * 1024 * 1024
SOFTWARE_MAX_PATHS = 128
DOWNLOAD_MAX_BYTES = 96 * 1024 * 1024
PROCESS_OUTPUT_MAX_BYTES = 64 * 1024
PROCESS_TIMEOUT_SECONDS = 120
SOFTWARE_STAMP_KEYS_V2 = {
    "schema_version",
    "product_name",
    "build_version",
    "canonical_target",
    "version",
    "command",
    "entrypoint",
    "entrypoint_kind",
    "installed_tree",
    "manager",
    "platform",
    "binary",
    "source",
    "entrypoint_sha256",
    "installed_tree_sha256",
    "version_probe",
}
CLEANUP_PARENT_FRAGMENT = ".nddev-kimicode-cleanup"
CLEANUP_PREPARE_NAME = "prepare.json"
CLEANUP_JOURNAL_NAME = "NDDEV-KIMICODE-CLEANUP.json"
CLEANUP_SCHEMA = 1
CLEANUP_MAX_ENTRIES = 8
CLEANUP_MAX_OBJECTS = 512
CLEANUP_MAX_BYTES = 256 * 1024 * 1024
CLEANUP_JOURNAL_MAX_BYTES = 1024 * 1024
CLEANUP_NAME_PATTERN = re.compile(r"[0-7]-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
FORBIDDEN_LAUNCH_FLAGS = {
    "--auto",
    "--auto-approve",
    "--continue",
    "--plan",
    "--resume",
    "--session",
    "--yolo",
    "--yes",
    "-S",
    "-c",
    "-p",
    "-r",
    "-y",
}
FORBIDDEN_LAUNCH_VALUE_FLAGS = {
    "--add-dir",
    "--agent",
    "--agent-file",
    "--model",
    "--output-format",
    "--prompt",
    "--resume",
    "--session",
    "--skills-dir",
    "-m",
    "-p",
    "-r",
    "-S",
}
FORBIDDEN_LAUNCH_SHORT_VALUE_FLAGS = {"-S", "-m", "-p", "-r"}
FORBIDDEN_LAUNCH_SUBCOMMANDS = {
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
}


class KimicodeSetupError(Exception):
    """Safe user-facing lifecycle failure."""


class ReadLifecycleRetry(Exception):
    """Internal signal that an uncoordinated read observed lifecycle namespace churn."""


class CleanupPendingState(Exception):
    """Valid cleanup state is durable and must be completed by a later mutator."""


@dataclass
class DirectoryTransaction:
    created: list[Path]

    def cleanup(self) -> None:
        for path in reversed(self.created):
            with contextlib.suppress(OSError):
                path.rmdir()


@dataclass
class VerifiedLaunchExecutable:
    path: Path
    fd: int
    digest: str
    st_dev: int
    st_ino: int

    def close(self) -> None:
        os.close(self.fd)


@dataclass
class LaunchInvocation:
    target: Path
    workspace: Path
    command: list[str]
    child_env: dict[str, str]
    expected_entrypoint_digest: str
    stamp_entrypoint_digest: str


@dataclass(frozen=True)
class CleanupPromotionResult:
    payload: dict[str, Any]
    publication_pending: bool


@dataclass
class ProductLockHandle:
    fd: int
    path: Path
    root: Path


@dataclass
class ExternalTargetLockHandle:
    fd: int
    path: Path
    canonical_target: str


@dataclass
class ProtectedDirectory:
    path: Path
    fd: int
    original_mode: int

    def restore(self) -> None:
        try:
            os.fchmod(self.fd, self.original_mode)
        finally:
            os.close(self.fd)


@dataclass(frozen=True)
class ManagedFileState:
    relative: str
    exists: bool
    st_dev: int | None = None
    st_ino: int | None = None
    st_mode: int | None = None
    st_uid: int | None = None
    st_gid: int | None = None
    st_nlink: int | None = None
    st_size: int | None = None
    st_mtime_ns: int | None = None
    digest: str | None = None


@dataclass(frozen=True)
class ManagedDirectoryState:
    path: Path
    st_dev: int
    st_ino: int
    st_uid: int
    st_gid: int
    mode: int
    st_nlink: int
    st_size: int
    atime_ns: int
    mtime_ns: int


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


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-kimicode-backups"


def cleanup_parent(target: Path) -> Path:
    return target.parent / f".{target.name}{CLEANUP_PARENT_FRAGMENT}"


def cleanup_prepare_path(target: Path) -> Path:
    return cleanup_parent(target) / CLEANUP_PREPARE_NAME


def cleanup_journal_path(target: Path) -> Path:
    return cleanup_parent(target) / CLEANUP_JOURNAL_NAME


def cleanup_tombstone_path(target: Path, relative_name: str) -> Path:
    if not isinstance(relative_name, str) or CLEANUP_NAME_PATTERN.fullmatch(relative_name) is None:
        fail("cleanup tombstone name is invalid")
    return cleanup_parent(target) / relative_name


def lock_parent_path(target: Path) -> Path:
    return target / LOCK_DIR_NAME


def lock_path(target: Path) -> Path:
    return lock_parent_path(target) / LOCK_NAME


def lock_canonical_target(target: Path) -> str:
    reject_symlink_ancestors(target)
    parent = target.parent
    reject_symlink_ancestors(parent)
    require_owner_private_directory(parent, "target parent")
    canonical_parent = parent.resolve(strict=True)
    reject_symlink_ancestors(canonical_parent)
    return str(canonical_parent / target.name)


def fixed_system_temp_root() -> Path:
    system = platform.system().lower()
    if system == "darwin":
        root = Path("/private/tmp")
    elif system == "linux":
        root = Path("/tmp")
    else:
        fail("external lifecycle lock is unsupported on this platform")
    resolved = root.resolve(strict=True)
    info = stat_existing(resolved, "system bootstrap root")
    if info is None:
        fail("system bootstrap root is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail("system bootstrap root must be a real directory")
    if not info.st_mode & stat.S_ISVTX:
        fail("system bootstrap root must be sticky")
    return resolved


def remove_unpublished_path(path: Path, created_info: os.stat_result, label: str) -> None:
    current = stat_existing(path, label)
    if current is None:
        return
    if current.st_dev != created_info.st_dev or current.st_ino != created_info.st_ino:
        fail(f"{label} changed before rollback")
    if stat.S_ISDIR(created_info.st_mode):
        if not stat.S_ISDIR(current.st_mode):
            fail(f"{label} changed kind before rollback")
        path.rmdir()
        return
    if stat.S_ISREG(created_info.st_mode):
        if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
            fail(f"{label} changed kind before rollback")
        path.unlink()
        return
    fail(f"{label} has unsupported rollback kind")


def rollback_unpublished_path(
    path: Path,
    created_info: os.stat_result | None,
    parent_fd: int,
    parent_info: os.stat_result,
    label: str,
) -> None:
    if created_info is not None:
        remove_unpublished_path(path, created_info, label)
        os.fsync(parent_fd)
    restore_directory_metadata_fd(parent_fd, parent_info, f"{label} parent")
    os.fsync(parent_fd)


def rollback_unpublished_path_after_open(
    path: Path,
    created_info: os.stat_result | None,
    parent_fd: int,
    parent_info: os.stat_result,
    label: str,
) -> None:
    try:
        rollback_unpublished_path(path, created_info, parent_fd, parent_info, label)
    finally:
        os.close(parent_fd)


@dataclass
class DirectoryCreationSpan:
    path: Path
    created_info: os.stat_result
    parent_fd: int
    parent_info: os.stat_result
    label: str
    closed: bool = False

    def rollback(self) -> None:
        if self.closed:
            return
        try:
            rollback_unpublished_path(
                self.path,
                self.created_info,
                self.parent_fd,
                self.parent_info,
                self.label,
            )
        finally:
            os.close(self.parent_fd)
            self.closed = True

    def commit_parent_metadata(self) -> None:
        if self.closed:
            return
        try:
            restore_directory_metadata_fd(self.parent_fd, self.parent_info, f"{self.label} parent")
            os.fsync(self.parent_fd)
        finally:
            os.close(self.parent_fd)
            self.closed = True


def validate_external_lock_root(root: Path, info: os.stat_result | None) -> None:
    if info is None:
        fail("external lifecycle lock root is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail("external lifecycle lock root must be a real directory")
    if not is_current_owner(info):
        fail("external lifecycle lock root must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("external lifecycle lock root mode must be 0700")


def ensure_external_lock_root_with_span() -> tuple[Path, DirectoryCreationSpan | None]:
    root = fixed_system_temp_root() / EXTERNAL_LOCK_ROOT_NAME
    info = stat_existing(root, "external lifecycle lock root")
    if info is None:
        parent_fd = open_directory_fd(root.parent, "external lifecycle lock root parent")
        parent_info = os.fstat(parent_fd)
        created_info: os.stat_result | None = None
        try:
            os.fsync(parent_fd)
            try:
                root.mkdir(mode=OWNER_DIRECTORY_MODE)
            except FileExistsError:
                pass
            else:
                created_info = require_real_directory(root, "external lifecycle lock root")
                root.chmod(OWNER_DIRECTORY_MODE)
            os.fsync(parent_fd)
            info = stat_existing(root, "external lifecycle lock root")
            validate_external_lock_root(root, info)
        except BaseException:
            rollback_unpublished_path_after_open(
                root,
                created_info,
                parent_fd,
                parent_info,
                "external lifecycle lock root",
            )
            raise
        if created_info is None:
            os.close(parent_fd)
            return root, None
        return root, DirectoryCreationSpan(
            path=root,
            created_info=created_info,
            parent_fd=parent_fd,
            parent_info=parent_info,
            label="external lifecycle lock root",
        )
    validate_external_lock_root(root, info)
    return root, None


def ensure_external_lock_root() -> Path:
    root, span = ensure_external_lock_root_with_span()
    if span is not None:
        span.commit_parent_metadata()
    return root


def bootstrap_lock_path(target: Path, canonical_target: str | None = None) -> Path:
    canonical = canonical_target if canonical_target is not None else lock_canonical_target(target)
    return bootstrap_lock_path_for_root(ensure_external_lock_root(), canonical)


def product_lock_path(root: Path) -> Path:
    return root / PRODUCT_LOCK_NAME


def target_lock_root_path(root: Path) -> Path:
    return root / TARGET_LOCK_ROOT_NAME


def bootstrap_lock_path_for_root(root: Path, canonical_target: str) -> Path:
    digest = sha256_bytes(f"{EXTERNAL_LOCK_NAMESPACE}\0{canonical_target}".encode("utf-8"))
    return target_lock_root_path(root) / f"{digest}.{EXTERNAL_LOCK_SUFFIX}"


def external_lock_root_no_create() -> Path | None:
    root = fixed_system_temp_root() / EXTERNAL_LOCK_ROOT_NAME
    info = stat_existing(root, "external lifecycle lock root")
    if info is None:
        return None
    if not stat.S_ISDIR(info.st_mode):
        fail("external lifecycle lock root must be a real directory")
    if not is_current_owner(info):
        fail("external lifecycle lock root must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("external lifecycle lock root mode must be 0700")
    return root


def bootstrap_lock_path_no_create(canonical_target: str) -> Path | None:
    root = external_lock_root_no_create()
    if root is None:
        return None
    target_root = target_lock_root_path(root)
    if stat_existing(target_root, "external target lock root") is None:
        return None
    return bootstrap_lock_path_for_root(root, canonical_target)


def bounded_directory_entries(path: Path, label: str) -> list[Path]:
    entries: list[Path] = []
    try:
        iterator = path.iterdir()
        for entry in iterator:
            entries.append(entry)
            if len(entries) > LOCK_PARENT_ENTRY_MAX:
                fail(f"{label} has too many entries")
    except OSError as exc:
        fail(f"{label} could not be inspected: {exc}")
    return sorted(entries, key=lambda item: item.name)


def validate_external_target_lock_root(info: os.stat_result | None) -> None:
    if info is None:
        fail("external target lock root is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail("external target lock root must be a directory")
    if not is_current_owner(info):
        fail("external target lock root must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("external target lock root mode must be 0700")


def ensure_external_target_lock_root_with_span(root: Path) -> tuple[Path, DirectoryCreationSpan | None]:
    target_root = target_lock_root_path(root)
    info = stat_existing(target_root, "external target lock root")
    if info is None:
        parent_fd = open_directory_fd(root, "external target lock root parent")
        parent_info = os.fstat(parent_fd)
        created_info: os.stat_result | None = None
        try:
            os.fsync(parent_fd)
            try:
                target_root.mkdir(mode=OWNER_DIRECTORY_MODE)
            except FileExistsError:
                pass
            else:
                created_info = require_real_directory(target_root, "external target lock root")
                target_root.chmod(OWNER_DIRECTORY_MODE)
            os.fsync(parent_fd)
            info = stat_existing(target_root, "external target lock root")
            validate_external_target_lock_root(info)
        except BaseException:
            rollback_unpublished_path_after_open(
                target_root,
                created_info,
                parent_fd,
                parent_info,
                "external target lock root",
            )
            raise
        if created_info is None:
            os.close(parent_fd)
            return target_root, None
        return target_root, DirectoryCreationSpan(
            path=target_root,
            created_info=created_info,
            parent_fd=parent_fd,
            parent_info=parent_info,
            label="external target lock root",
        )
    validate_external_target_lock_root(info)
    return target_root, None


def ensure_external_target_lock_root(root: Path) -> Path:
    target_root, span = ensure_external_target_lock_root_with_span(root)
    if span is not None:
        span.commit_parent_metadata()
    return target_root


def ensure_lock_parent(target: Path) -> Path:
    path = lock_parent_path(target)
    info = stat_existing(path, "target lifecycle lock directory")
    if info is None:
        path.mkdir(mode=OWNER_DIRECTORY_MODE)
        path.chmod(OWNER_DIRECTORY_MODE)
        return path
    if not stat.S_ISDIR(info.st_mode):
        fail("target lifecycle lock directory must be a directory")
    if not is_current_owner(info):
        fail("target lifecycle lock directory must be owned by the current user")
    mode = stat.S_IMODE(info.st_mode)
    if mode not in {OWNER_DIRECTORY_MODE, 0o500}:
        fail("target lifecycle lock directory mode must be 0700 or protected 0500")
    return path


def validate_lock_info(info: os.stat_result, label: str) -> None:
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file")
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    if info.st_nlink != 1:
        fail(f"{label} must not be a hardlink")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail(f"{label} mode must be 0600")


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        fail(f"directory could not be opened for fsync: {path}: {exc}")
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def write_lock_stage_file(path: Path, payload: bytes, label: str) -> None:
    parent_fd = open_directory_fd(path.parent, f"{label} parent")
    parent_info = os.fstat(parent_fd)
    fd: int | None = None
    created_info: os.stat_result | None = None
    try:
        os.fsync(parent_fd)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, OWNER_FILE_MODE)
        created_info = os.fstat(fd)
        write_all(fd, payload)
        os.fchmod(fd, OWNER_FILE_MODE)
        os.fsync(fd)
        os.close(fd)
        fd = None
        info = stat_existing(path, label)
        if info is None:
            fail(f"{label} staged file is missing")
        validate_lock_info(info, label)
        if read_existing_file(path, max_bytes=METADATA_MAX_BYTES, label=label) != payload:
            fail(f"{label} staged binding postcondition failed")
    except BaseException:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        rollback_unpublished_path(
            path,
            created_info,
            parent_fd,
            parent_info,
            label,
        )
        raise
    finally:
        os.close(parent_fd)


def lock_stage_prefix(path: Path) -> str:
    return f".{path.name}.nddev.tmp."


def lock_stage_aliases(path: Path, label: str) -> list[Path]:
    parent = path.parent
    parent_info = stat_existing(parent, f"{label} parent")
    if parent_info is None:
        return []
    if not stat.S_ISDIR(parent_info.st_mode):
        fail(f"{label} parent must be a directory")
    if not is_current_owner(parent_info):
        fail(f"{label} parent must be owned by the current user")
    parent_mode = stat.S_IMODE(parent_info.st_mode)
    if parent_mode not in {OWNER_DIRECTORY_MODE, 0o500}:
        fail(f"{label} parent mode must be 0700 or protected 0500")
    prefix = lock_stage_prefix(path)
    aliases: list[Path] = []
    for child in bounded_directory_entries(parent, f"{label} parent"):
        if not child.name.startswith(prefix):
            continue
        suffix = child.name[len(prefix) :]
        pieces = suffix.split(".")
        if (
            len(pieces) != 2
            or not pieces[0].isdecimal()
            or not pieces[1].isdecimal()
            or len(pieces[0]) > 20
            or len(pieces[1]) > 30
        ):
            fail(f"{label} staged binding alias is malformed")
        aliases.append(child)
        if len(aliases) > LOCK_STAGE_ALIAS_MAX:
            fail(f"{label} has too many staged binding aliases")
    return aliases


def read_valid_lock_stage_payload(
    stage: Path,
    path: Path,
    label: str,
    *,
    canonical_target: str,
    kind: str,
) -> os.stat_result:
    info = stat_existing(stage, f"{label} staged binding")
    if info is None:
        fail(f"{label} staged binding is missing")
    validate_lock_info(info, f"{label} staged binding")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(stage, flags)
    except OSError as exc:
        fail(f"{label} staged binding could not be opened safely: {exc}")
    try:
        opened = os.fstat(fd)
        validate_lock_info(opened, f"{label} staged binding")
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            fail(f"{label} staged binding changed while opening")
        if opened.st_size > METADATA_MAX_BYTES:
            fail(f"{label} staged binding is too large")
        data = os.read(fd, METADATA_MAX_BYTES + 1)
        if len(data) > METADATA_MAX_BYTES:
            fail(f"{label} staged binding is too large")
        after = os.fstat(fd)
        if after.st_dev != opened.st_dev or after.st_ino != opened.st_ino or after.st_size != opened.st_size:
            fail(f"{label} staged binding changed while reading")
    finally:
        os.close(fd)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"{label} staged binding is malformed")
    if not isinstance(payload, dict):
        fail(f"{label} staged binding is malformed")
    validate_lock_binding(
        payload,
        kind=kind,
        canonical_target=canonical_target,
        path=path,
        label=f"{label} staged binding",
    )
    if data != canonical_json(payload):
        fail(f"{label} staged binding is not canonical")
    current = stat_existing(stage, f"{label} staged binding")
    if current is None:
        fail(f"{label} staged binding disappeared")
    validate_lock_info(current, f"{label} staged binding")
    if (
        current.st_dev != after.st_dev
        or current.st_ino != after.st_ino
        or current.st_mode != after.st_mode
        or current.st_nlink != after.st_nlink
        or current.st_size != after.st_size
        or current.st_mtime_ns != after.st_mtime_ns
    ):
        fail(f"{label} staged binding changed after validation")
    return current


def revalidate_lock_stage_identity(stage: Path, expected: os.stat_result, label: str) -> None:
    current = stat_existing(stage, f"{label} staged binding")
    if current is None:
        fail(f"{label} staged binding disappeared")
    validate_lock_info(current, f"{label} staged binding")
    if (
        current.st_dev != expected.st_dev
        or current.st_ino != expected.st_ino
        or current.st_mode != expected.st_mode
        or current.st_nlink != expected.st_nlink
        or current.st_size != expected.st_size
        or current.st_mtime_ns != expected.st_mtime_ns
    ):
        fail(f"{label} staged binding changed before promotion")


def open_directory_fd(path: Path, label: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        fail(f"{label} open requires O_NOFOLLOW support")
    flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except OSError as exc:
        fail(f"{label} could not be opened safely: {exc}")


def restore_directory_metadata_fd(fd: int, info: os.stat_result, label: str) -> None:
    current = os.fstat(fd)
    if current.st_dev != info.st_dev or current.st_ino != info.st_ino:
        fail(f"{label} changed before metadata restore")
    if not stat.S_ISDIR(current.st_mode):
        fail(f"{label} must be a directory")
    if stat.S_IMODE(current.st_mode) != stat.S_IMODE(info.st_mode):
        os.fchmod(fd, stat.S_IMODE(info.st_mode))
    os.utime(fd, ns=(info.st_atime_ns, info.st_mtime_ns))


def restore_directory_metadata(path: Path, info: os.stat_result, label: str) -> None:
    fd = open_directory_fd(path, label)
    try:
        restore_directory_metadata_fd(fd, info, label)
        os.fsync(fd)
    finally:
        os.close(fd)


def cleanup_lock_stage_file(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    with contextlib.suppress(OSError):
        fsync_directory(path.parent)


def rename_no_replace(source: Path, destination: Path, label: str) -> bool:
    system = platform.system().lower()
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if system == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renameatx_np = libc.renameatx_np
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        result = renameatx_np(
            AT_FDCWD_BY_SYSTEM["darwin"],
            source_bytes,
            AT_FDCWD_BY_SYSTEM["darwin"],
            destination_bytes,
            RENAME_EXCL_DARWIN,
        )
    elif system == "linux":
        machine = platform.machine().lower()
        syscall_number = RENAMEAT2_SYSCALL_BY_MACHINE.get(machine)
        if syscall_number is None:
            fail(f"{label} no-replace publication is unsupported on this architecture")
        libc = ctypes.CDLL(None, use_errno=True)
        syscall = libc.syscall
        syscall.restype = ctypes.c_long
        result = syscall(
            ctypes.c_long(syscall_number),
            ctypes.c_int(AT_FDCWD_BY_SYSTEM["linux"]),
            ctypes.c_char_p(source_bytes),
            ctypes.c_int(AT_FDCWD_BY_SYSTEM["linux"]),
            ctypes.c_char_p(destination_bytes),
            ctypes.c_uint(RENAME_NOREPLACE_LINUX),
        )
    else:
        fail(f"{label} no-replace publication is unsupported on this platform")
    if result == 0:
        return True
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        return False
    if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
        fail(f"{label} no-replace publication primitive is unavailable")
    fail(f"{label} no-replace publication failed: {os.strerror(error)}")


def parent_metadata(path: Path, label: str) -> os.stat_result:
    info = require_real_directory(path, label)
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    return info


def cleanup_write_bound_file(path: Path, payload: bytes, label: str) -> os.stat_result:
    if len(payload) > CLEANUP_JOURNAL_MAX_BYTES:
        fail(f"{label} exceeds serialized size limit")
    parent_fd = open_directory_fd(path.parent, f"{label} parent")
    parent_info = os.fstat(parent_fd)
    fd: int | None = None
    created: os.stat_result | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, OWNER_FILE_MODE)
        created = os.fstat(fd)
        write_all(fd, payload)
        os.fchmod(fd, OWNER_FILE_MODE)
        os.fsync(fd)
        os.close(fd)
        fd = None
        current = stat_existing(path, label)
        if current is None:
            fail(f"{label} disappeared after write")
        if (
            current.st_dev != created.st_dev
            or current.st_ino != created.st_ino
            or not stat.S_ISREG(current.st_mode)
            or stat.S_IMODE(current.st_mode) != OWNER_FILE_MODE
            or current.st_nlink != 1
            or current.st_size != len(payload)
        ):
            fail(f"{label} write identity changed")
        if read_existing_file(path, max_bytes=CLEANUP_JOURNAL_MAX_BYTES, label=label) != payload:
            fail(f"{label} write content changed")
        os.fsync(parent_fd)
        restore_directory_metadata_fd(parent_fd, parent_info, f"{label} parent")
        os.fsync(parent_fd)
        return current
    except BaseException:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        rollback_unpublished_path(path, created, parent_fd, parent_info, label)
        raise
    finally:
        os.close(parent_fd)


def cleanup_temp_path(final: Path) -> Path:
    return final.with_name(f".{final.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")


def cleanup_temp_aliases(final: Path) -> list[Path]:
    parent = final.parent
    if not path_exists_no_follow(parent):
        return []
    prefix = f".{final.name}.nddev.tmp."
    aliases: list[Path] = []
    for child in bounded_directory_entries(parent, f"cleanup {final.name} parent"):
        if not child.name.startswith(prefix):
            continue
        suffix = child.name[len(prefix) :]
        parts = suffix.split(".")
        if len(parts) != 2 or not all(part.isdecimal() for part in parts):
            fail("cleanup publication alias is malformed")
        aliases.append(child)
        if len(aliases) > CLEANUP_MAX_ENTRIES:
            fail("cleanup publication alias bound exceeded")
    return aliases


def cleanup_publish_file_no_replace(final: Path, payload: bytes, label: str) -> bool:
    if path_exists_no_follow(final):
        fail(f"{label} already exists")
    stage = cleanup_temp_path(final)
    created = cleanup_write_bound_file(stage, payload, f"{label} publication alias")
    try:
        if not rename_no_replace(stage, final, label):
            fail(f"{label} already exists")
        fsync_directory(final.parent)
        current = stat_existing(final, label)
        if current is None or current.st_dev != created.st_dev or current.st_ino != created.st_ino:
            fail(f"{label} final identity mismatch")
        return False
    except BaseException:
        if path_exists_no_follow(final):
            return True
        with contextlib.suppress(BaseException):
            if path_exists_no_follow(stage):
                stage.unlink()
                fsync_directory(stage.parent)
        raise


def cleanup_recover_publication_alias(final: Path, label: str) -> None:
    aliases = cleanup_temp_aliases(final)
    if not aliases:
        return
    info = stat_existing(final, label)
    if info is None:
        fail(f"{label} final file is missing for alias recovery")
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail(f"{label} final file is invalid")
    same: list[Path] = []
    for alias in aliases:
        alias_info = stat_existing(alias, f"{label} alias")
        if alias_info is None:
            continue
        if (
            stat.S_ISREG(alias_info.st_mode)
            and stat.S_IMODE(alias_info.st_mode) == OWNER_FILE_MODE
            and alias_info.st_dev == info.st_dev
            and alias_info.st_ino == info.st_ino
        ):
            same.append(alias)
        else:
            fail(f"{label} has ambiguous publication alias")
    if info.st_nlink != len(same) + 1:
        fail(f"{label} hardlink alias set is ambiguous")
    for alias in same:
        alias.unlink()
    fsync_directory(final.parent)
    current = stat_existing(final, label)
    if current is None or current.st_dev != info.st_dev or current.st_ino != info.st_ino or current.st_nlink != 1:
        fail(f"{label} changed during alias recovery")


def cleanup_validate_relative(relative: str, label: str) -> None:
    if not isinstance(relative, str) or not relative:
        fail(f"{label} relative path is invalid")
    if relative == ".":
        return
    if relative.startswith("/") or relative.endswith("/") or "//" in relative or len(relative) > 512:
        fail(f"{label} relative path is invalid")
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        fail(f"{label} relative path escapes tombstone")


def cleanup_object_path(root: Path, relative: str) -> Path:
    cleanup_validate_relative(relative, "cleanup object")
    return root if relative == "." else root.joinpath(*relative.split("/"))


def cleanup_object_relative(root: Path, path: Path) -> str:
    if path == root:
        return "."
    relative = path.relative_to(root).as_posix()
    cleanup_validate_relative(relative, "cleanup object")
    return relative


def cleanup_source_category(target: Path, source: Path) -> str | None:
    target_parent_prefixes = {
        f".{target.name}.nddev-kimicode-backup-retired.": "backup-retired",
        f".{target.name}.nddev-kimicode-backup-stage.": "backup-stage",
        f".{target.name}{SOFTWARE_STAGE_FRAGMENT}.": "software-stage",
        f".{target.name}{SOFTWARE_ROLLBACK_FRAGMENT}.": "software-rollback",
    }
    if source.parent == target.parent:
        for prefix, category in target_parent_prefixes.items():
            if source.name.startswith(prefix):
                return category
    target_prefixes = {
        ".nddev-kimicode-runtime-stage.": "runtime-stage",
    }
    if source.parent == target:
        for prefix, category in target_prefixes.items():
            if source.name.startswith(prefix):
                return category
    return None


def cleanup_source_binding(target: Path, source: Path, category: str) -> dict[str, Any]:
    if not source.is_absolute():
        fail("cleanup source must be absolute")
    if cleanup_source_category(target, source) != category:
        fail("cleanup source category binding is invalid")
    anchors = {"target": target, "target-parent": target.parent}
    anchor_name: str | None = None
    relative: str | None = None
    for name, anchor in anchors.items():
        try:
            candidate = source.relative_to(anchor).as_posix()
        except ValueError:
            continue
        cleanup_validate_relative(candidate, "cleanup source")
        if candidate == "." or "/" in candidate:
            fail("cleanup source must be a bounded direct child of its anchor")
        anchor_name = name
        relative = candidate
        break
    if anchor_name is None or relative is None:
        fail("cleanup source is outside declared anchors")
    parent_info = parent_metadata(source.parent, "cleanup source parent")
    return {
        "anchor": anchor_name,
        "relative_path": relative,
        "parent": {
            "uid": parent_info.st_uid,
            "gid": parent_info.st_gid,
            "mode": stat.S_IMODE(parent_info.st_mode),
            "device": parent_info.st_dev,
            "inode": parent_info.st_ino,
            "nlink": parent_info.st_nlink,
            "size": parent_info.st_size,
            "mtime_ns": parent_info.st_mtime_ns,
        },
    }


def cleanup_source_from_binding(target: Path, entry: dict[str, Any], source: dict[str, Any]) -> Path:
    exact_keys(source, {"anchor", "relative_path", "parent"}, "cleanup prepare source")
    anchor = source["anchor"]
    relative = source["relative_path"]
    if anchor not in {"target", "target-parent"}:
        fail("cleanup prepare source anchor is invalid")
    if not isinstance(relative, str):
        fail("cleanup prepare source relative path is invalid")
    cleanup_validate_relative(relative, "cleanup prepare source")
    if relative == "." or "/" in relative:
        fail("cleanup prepare source must be a bounded direct child")
    root = target if anchor == "target" else target.parent
    path = root / relative
    if cleanup_source_category(target, path) != entry["category"]:
        fail("cleanup prepare source category changed")
    parent = source["parent"]
    exact_keys(parent, {"uid", "gid", "mode", "device", "inode", "nlink", "size", "mtime_ns"}, "cleanup prepare source parent")
    info = parent_metadata(path.parent, "cleanup prepare source parent")
    if (
        info.st_uid != parent["uid"]
        or info.st_gid != parent["gid"]
        or stat.S_IMODE(info.st_mode) != parent["mode"]
        or info.st_dev != parent["device"]
        or info.st_ino != parent["inode"]
    ):
        fail("cleanup prepare source parent identity changed")
    return path


def cleanup_object_record(root: Path, path: Path, counters: dict[str, int]) -> dict[str, Any]:
    counters["objects"] += 1
    if counters["objects"] > CLEANUP_MAX_OBJECTS:
        fail("cleanup object graph exceeds bounded count")
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        fail(f"cleanup object must not be a symlink: {path}")
    if not is_current_owner(info):
        fail(f"cleanup object must be owned by current user: {path}")
    common: dict[str, Any] = {
        "relative_path": cleanup_object_relative(root, path),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "nlink": info.st_nlink,
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }
    if stat.S_ISDIR(info.st_mode):
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail("cleanup directory must be private")
        return {**common, "kind": "directory", "sha256": None}
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:
            fail("cleanup file must not be a hardlink")
        if stat.S_IMODE(info.st_mode) not in {OWNER_FILE_MODE, 0o700}:
            fail("cleanup file mode is not owner-only")
        data = read_existing_file(path, max_bytes=SOFTWARE_MAX_BYTES, label=str(path))
        if data is None:
            fail("cleanup file disappeared while hashing")
        counters["bytes"] += len(data)
        if counters["bytes"] > CLEANUP_MAX_BYTES:
            fail("cleanup object graph exceeds bounded bytes")
        return {**common, "kind": "file", "sha256": sha256_bytes(data)}
    fail("cleanup object kind is unsupported")


def cleanup_object_graph(root: Path) -> list[dict[str, Any]]:
    require_owner_private_directory(root, "cleanup source")
    counters = {"objects": 0, "bytes": 0}
    records = [cleanup_object_record(root, root, counters)]
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        records.append(cleanup_object_record(root, path, counters))
    return records


def validate_cleanup_object_shape(raw: Any) -> dict[str, Any]:
    record = exact_keys(
        raw,
        {"relative_path", "kind", "uid", "gid", "mode", "nlink", "device", "inode", "size", "mtime_ns", "sha256"},
        "cleanup object",
    )
    cleanup_validate_relative(record["relative_path"], "cleanup object")
    if record["kind"] not in {"directory", "file"}:
        fail("cleanup object kind is invalid")
    for key in ("uid", "gid", "mode", "nlink", "device", "inode", "size", "mtime_ns"):
        if not isinstance(record[key], int) or record[key] < 0:
            fail(f"cleanup object {key} is invalid")
    if record["kind"] == "directory":
        if record["sha256"] is not None:
            fail("cleanup directory object must not carry a digest")
    elif not isinstance(record["sha256"], str) or SHA256_PATTERN.fullmatch(record["sha256"]) is None:
        fail("cleanup file digest is invalid")
    return record


def cleanup_entry_objects(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = entry.get("objects")
    if not isinstance(objects, list) or not objects or len(objects) > CLEANUP_MAX_OBJECTS:
        fail("cleanup entry object graph is invalid")
    result: dict[str, dict[str, Any]] = {}
    for raw in objects:
        record = validate_cleanup_object_shape(raw)
        relative = record["relative_path"]
        if relative in result:
            fail("cleanup object graph contains duplicate paths")
        result[relative] = record
    if "." not in result or result["."]["kind"] != "directory":
        fail("cleanup object graph must contain a directory root")
    for relative in result:
        if relative == ".":
            continue
        parent = relative.rsplit("/", 1)[0] if "/" in relative else "."
        if parent not in result or result[parent]["kind"] != "directory":
            fail("cleanup object graph is missing a parent")
    return result


def cleanup_tree_sha256(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item["relative_path"]):
        digest.update(canonical_json(record))
        digest.update(b"\0")
    return digest.hexdigest()


def cleanup_entry_for_source(target: Path, source: Path, index: int) -> dict[str, Any]:
    if index < 0 or index >= CLEANUP_MAX_ENTRIES:
        fail("cleanup entry count exceeds bound")
    category = cleanup_source_category(target, source)
    if category is None:
        fail(f"cleanup source is outside declared machine namespaces: {source}")
    records = cleanup_object_graph(source)
    root = records[0]
    relative_name = f"{index}-{category}"
    return {
        "relative_name": relative_name,
        "category": category,
        "source": cleanup_source_binding(target, source, category),
        "uid": root["uid"],
        "gid": root["gid"],
        "mode": root["mode"],
        "nlink": root["nlink"],
        "device": root["device"],
        "inode": root["inode"],
        "size": root["size"],
        "mtime_ns": root["mtime_ns"],
        "tree_sha256": cleanup_tree_sha256(records),
        "objects": records,
    }


def validate_cleanup_entry_shape(raw: Any) -> dict[str, Any]:
    entry = exact_keys(
        raw,
        {
            "relative_name",
            "category",
            "source",
            "uid",
            "gid",
            "mode",
            "nlink",
            "device",
            "inode",
            "size",
            "mtime_ns",
            "tree_sha256",
            "objects",
        },
        "cleanup entry",
    )
    cleanup_tombstone_path(Path("/tmp/target"), entry["relative_name"])
    if not isinstance(entry["category"], str) or entry["relative_name"].split("-", 1)[1] != entry["category"]:
        fail("cleanup entry category is invalid")
    for key in ("uid", "gid", "mode", "nlink", "device", "inode", "size", "mtime_ns"):
        if not isinstance(entry[key], int) or entry[key] < 0:
            fail(f"cleanup entry {key} is invalid")
    objects = cleanup_entry_objects(entry)
    root = objects["."]
    for key in ("uid", "gid", "mode", "nlink", "device", "inode", "size", "mtime_ns"):
        if entry[key] != root[key]:
            fail("cleanup entry root identity mismatch")
    if not isinstance(entry["tree_sha256"], str) or entry["tree_sha256"] != cleanup_tree_sha256(list(objects.values())):
        fail("cleanup entry digest is invalid")
    return entry


def cleanup_journal_payload(target: Path, entries: list[dict[str, Any]], phase: str = "journal") -> dict[str, Any]:
    if len(entries) > CLEANUP_MAX_ENTRIES:
        fail("cleanup entry count exceeds bound")
    payload = {
        "schema_version": CLEANUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(validate_target(target, create=False)),
        "cleanup_parent_anchor": "target-parent",
        "cleanup_parent_relative": cleanup_parent(target).name,
        "phase": phase,
        "prepare_file": CLEANUP_PREPARE_NAME,
        "journal_file": CLEANUP_JOURNAL_NAME,
        "entry_count": len(entries),
        "entries": entries,
        "digests_are_corruption_checks_only": True,
    }
    cleanup_journal_bytes(payload)
    return payload


def cleanup_journal_bytes(payload: dict[str, Any]) -> bytes:
    content = canonical_json(payload)
    if len(content) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal exceeds serialized size limit")
    return content


def validate_cleanup_payload(target: Path, payload: dict[str, Any], *, allow_prepare_phase: bool) -> dict[str, Any]:
    exact_keys(
        payload,
        {
            "schema_version",
            "product_name",
            "build_version",
            "canonical_target",
            "cleanup_parent_anchor",
            "cleanup_parent_relative",
            "phase",
            "prepare_file",
            "journal_file",
            "entry_count",
            "entries",
            "digests_are_corruption_checks_only",
        },
        "cleanup payload",
    )
    if (
        payload["schema_version"] != CLEANUP_SCHEMA
        or payload["product_name"] != PRODUCT_NAME
        or payload["build_version"] != VERSION
        or payload["canonical_target"] != str(validate_target(target, create=False))
        or payload["cleanup_parent_anchor"] != "target-parent"
        or payload["cleanup_parent_relative"] != cleanup_parent(target).name
        or payload["prepare_file"] != CLEANUP_PREPARE_NAME
        or payload["journal_file"] != CLEANUP_JOURNAL_NAME
        or payload["digests_are_corruption_checks_only"] is not True
    ):
        fail("cleanup payload binding is invalid")
    if payload["phase"] not in ({"prepare", "journal"} if allow_prepare_phase else {"journal"}):
        fail("cleanup payload phase is invalid")
    entries = payload["entries"]
    if not isinstance(entries, list) or payload["entry_count"] != len(entries) or len(entries) > CLEANUP_MAX_ENTRIES:
        fail("cleanup payload entry count is invalid")
    seen: set[str] = set()
    for raw in entries:
        entry = validate_cleanup_entry_shape(raw)
        if entry["relative_name"] in seen:
            fail("cleanup payload has duplicate tombstones")
        seen.add(entry["relative_name"])
        cleanup_source_from_binding(target, entry, entry["source"])
    return payload


def read_cleanup_payload(path: Path, label: str) -> dict[str, Any]:
    data = read_existing_file(path, max_bytes=CLEANUP_JOURNAL_MAX_BYTES, label=label)
    if data is None:
        fail(f"{label} is missing")
    return parse_json_object(data, label)


def cleanup_object_matches(path: Path, record: dict[str, Any], *, exact: bool) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        fail("cleanup object was replaced by symlink")
    if record["kind"] == "directory":
        if not stat.S_ISDIR(info.st_mode):
            fail("cleanup object kind changed")
    elif not stat.S_ISREG(info.st_mode):
        fail("cleanup object kind changed")
    if (
        info.st_uid != record["uid"]
        or info.st_gid != record["gid"]
        or stat.S_IMODE(info.st_mode) != record["mode"]
        or info.st_dev != record["device"]
        or info.st_ino != record["inode"]
    ):
        fail("cleanup object stable identity changed")
    if exact:
        if info.st_nlink != record["nlink"] or info.st_size != record["size"] or info.st_mtime_ns != record["mtime_ns"]:
            fail("cleanup object exact identity changed")
        if record["kind"] == "file":
            data = read_existing_file(path, max_bytes=SOFTWARE_MAX_BYTES, label=str(path))
            if data is None or sha256_bytes(data) != record["sha256"]:
                fail("cleanup file content changed")
    return True


def cleanup_tombstone_state(target: Path, entry: dict[str, Any], *, require_full: bool) -> tuple[Path, list[str], int]:
    tombstone = cleanup_tombstone_path(target, entry["relative_name"])
    objects = cleanup_entry_objects(entry)
    order = sorted(objects, key=lambda rel: (rel.count("/"), 1 if objects[rel]["kind"] == "directory" else 0, rel), reverse=True)
    present = {relative for relative in objects if path_exists_no_follow(cleanup_object_path(tombstone, relative))}
    if not present:
        return tombstone, order, len(order)
    if "." not in present:
        fail("cleanup partial tombstone is missing root")
    missing_prefix = 0
    for relative in order:
        if relative in present:
            break
        missing_prefix += 1
    if require_full and missing_prefix:
        fail("cleanup tombstone must be complete before first destructive step")
    for relative in order[missing_prefix:]:
        if relative not in present:
            fail("cleanup partial drain is not a deterministic prefix")
    remaining = set(order[missing_prefix:])
    for relative in remaining:
        path = cleanup_object_path(tombstone, relative)
        cleanup_object_matches(path, objects[relative], exact=missing_prefix == 0 or objects[relative]["kind"] == "file")
        if objects[relative]["kind"] == "directory":
            expected = {
                child.rsplit("/", 1)[-1]
                for child in remaining
                if child != "." and (child.rsplit("/", 1)[0] if "/" in child else ".") == relative
            }
            actual = {child.name for child in path.iterdir()}
            if actual != expected:
                fail("cleanup directory child set changed")
    return tombstone, order, missing_prefix


def validate_cleanup_parent(target: Path, *, allow_prepare: bool, recover_aliases: bool) -> dict[str, Any] | None:
    parent = cleanup_parent(target)
    if not path_exists_no_follow(parent):
        return None
    require_owner_private_directory(parent, "cleanup parent")
    journal = cleanup_journal_path(target)
    prepare = cleanup_prepare_path(target)
    if recover_aliases:
        if path_exists_no_follow(journal):
            cleanup_recover_publication_alias(journal, "cleanup journal")
        if path_exists_no_follow(prepare):
            cleanup_recover_publication_alias(prepare, "cleanup prepare")
    entries = {child.name for child in bounded_directory_entries(parent, "cleanup parent")}
    allowed_common = {CLEANUP_PREPARE_NAME, CLEANUP_JOURNAL_NAME}
    temp_prefixes = (f".{CLEANUP_PREPARE_NAME}.nddev.tmp.", f".{CLEANUP_JOURNAL_NAME}.nddev.tmp.")
    for name in entries:
        if name in allowed_common or CLEANUP_NAME_PATTERN.fullmatch(name) is not None:
            continue
        if any(name.startswith(prefix) for prefix in temp_prefixes):
            if recover_aliases:
                path = parent / name
                info = stat_existing(path, "cleanup unpublished alias")
                if info is not None and stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == OWNER_FILE_MODE and info.st_nlink == 1:
                    path.unlink()
                    fsync_directory(parent)
                    continue
            fail("cleanup parent contains unpublished alias")
        fail("cleanup parent contains unknown state")
    if path_exists_no_follow(journal):
        payload = read_cleanup_payload(journal, "cleanup journal")
        validate_cleanup_payload(target, payload, allow_prepare_phase=False)
    elif path_exists_no_follow(prepare):
        if not allow_prepare:
            fail("cleanup prepare is pending exclusive recovery")
        payload = read_cleanup_payload(prepare, "cleanup prepare")
        validate_cleanup_payload(target, payload, allow_prepare_phase=True)
    elif entries:
        fail("cleanup parent contains unjournaled tombstone state")
    else:
        return None
    active_payload = payload
    for entry in active_payload["entries"]:
        if path_exists_no_follow(journal):
            cleanup_tombstone_state(target, entry, require_full=False)
        else:
            source = cleanup_source_from_binding(target, entry, entry["source"])
            source_present = path_exists_no_follow(source)
            tombstone_present = path_exists_no_follow(cleanup_tombstone_path(target, entry["relative_name"]))
            if source_present and tombstone_present:
                fail("cleanup prepare source and tombstone are both present")
            if not source_present and not tombstone_present:
                fail("cleanup prepare source and tombstone are both absent")
    return active_payload


def recover_cleanup_prepare(target: Path) -> dict[str, Any] | None:
    payload = validate_cleanup_parent(target, allow_prepare=True, recover_aliases=True)
    if payload is None or payload["phase"] != "prepare":
        return payload
    parent = cleanup_parent(target)
    for entry in payload["entries"]:
        source = cleanup_source_from_binding(target, entry, entry["source"])
        tombstone = cleanup_tombstone_path(target, entry["relative_name"])
        if path_exists_no_follow(tombstone):
            cleanup_tombstone_state(target, entry, require_full=True)
            continue
        if not rename_no_replace(source, tombstone, "cleanup tombstone"):
            fail("cleanup tombstone destination already exists")
        fsync_directory(source.parent)
        fsync_directory(parent)
        cleanup_tombstone_state(target, entry, require_full=True)
    journal_payload = {**payload, "phase": "journal"}
    pending = cleanup_publish_file_no_replace(cleanup_journal_path(target), cleanup_journal_bytes(journal_payload), "cleanup journal")
    if pending:
        return journal_payload
    validate_cleanup_parent(target, allow_prepare=True, recover_aliases=True)
    prepare = cleanup_prepare_path(target)
    if path_exists_no_follow(prepare):
        prepare.unlink()
        fsync_directory(parent)
    return journal_payload


def cleanup_pending_state(target: Path) -> dict[str, Any]:
    payload = validate_cleanup_parent(target, allow_prepare=True, recover_aliases=False)
    if payload is None:
        return {"cleanup_pending": False, "cleanup_pending_entries": []}
    return {
        "cleanup_pending": True,
        "cleanup_pending_phase": payload["phase"],
        "cleanup_pending_entries": [
            {
                "index": index,
                "category": entry["category"],
                "kind": "directory",
                "object_count": len(entry["objects"]),
            }
            for index, entry in enumerate(payload["entries"])
        ],
    }


def cleanup_delete_entry(target: Path, entry: dict[str, Any], *, allow_pending: bool) -> bool:
    tombstone, order, missing_prefix = cleanup_tombstone_state(target, entry, require_full=False)
    if missing_prefix >= len(order):
        return False
    if missing_prefix == 0:
        cleanup_tombstone_state(target, entry, require_full=True)
    objects = cleanup_entry_objects(entry)
    for index, relative in enumerate(order):
        if index < missing_prefix:
            continue
        tombstone, _order, observed = cleanup_tombstone_state(target, entry, require_full=False)
        if observed > index:
            continue
        if observed != index:
            fail("cleanup partial drain cursor is inconsistent")
        path = cleanup_object_path(tombstone, relative)
        try:
            cleanup_object_matches(path, objects[relative], exact=True)
            if objects[relative]["kind"] == "directory":
                path.rmdir()
            else:
                path.unlink()
            fsync_directory(path.parent)
        except BaseException:
            if allow_pending:
                return True
            raise
    return False


def drain_cleanup_pending(target: Path, *, allow_pending: bool) -> tuple[bool, bool]:
    payload = recover_cleanup_prepare(target)
    if payload is None:
        parent = cleanup_parent(target)
        if path_exists_no_follow(parent) and not any(parent.iterdir()):
            parent.rmdir()
            fsync_directory(target.parent)
            return True, False
        return False, False
    if payload["phase"] == "prepare":
        payload = recover_cleanup_prepare(target)
        if payload is None:
            return True, False
    pending = False
    for entry in payload["entries"]:
        if cleanup_delete_entry(target, entry, allow_pending=allow_pending):
            pending = True
            break
    if pending:
        return True, True
    parent = cleanup_parent(target)
    try:
        if path_exists_no_follow(cleanup_prepare_path(target)):
            cleanup_prepare_path(target).unlink()
            fsync_directory(parent)
        if path_exists_no_follow(cleanup_journal_path(target)):
            cleanup_journal_path(target).unlink()
            fsync_directory(parent)
        if path_exists_no_follow(parent):
            parent.rmdir()
            fsync_directory(target.parent)
    except BaseException:
        if allow_pending:
            return True, True
        raise
    return True, False


def drain_cleanup_before_mutation(target: Path) -> bool:
    drained, pending = drain_cleanup_pending(target, allow_pending=False)
    if pending:
        fail("cleanup pending state could not be drained")
    return drained


def finish_postcommit_cleanup(target: Path, command: str, sources: list[Path]) -> bool:
    present = [source for source in sources if path_exists_no_follow(source)]
    if not present:
        return False
    if len(present) > CLEANUP_MAX_ENTRIES:
        fail("cleanup source count exceeds bound")
    if validate_cleanup_parent(target, allow_prepare=True, recover_aliases=True) is not None:
        fail("cleanup pending state must be drained before new cleanup work")
    parent = cleanup_parent(target)
    parent_existed = path_exists_no_follow(parent)
    if not parent_existed:
        parent_info = parent_metadata(parent.parent, "cleanup parent container")
        parent.mkdir(mode=OWNER_DIRECTORY_MODE)
        parent.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(parent.parent)
        restore_directory_metadata(parent.parent, parent_info, "cleanup parent container")
    require_owner_private_directory(parent, "cleanup parent")
    entries = [cleanup_entry_for_source(target, source, index) for index, source in enumerate(present)]
    prepare_payload = cleanup_journal_payload(target, entries, phase="prepare")
    try:
        pending = cleanup_publish_file_no_replace(cleanup_prepare_path(target), cleanup_journal_bytes(prepare_payload), "cleanup prepare")
        if pending:
            return True
        for entry, source in zip(entries, present):
            tombstone = cleanup_tombstone_path(target, entry["relative_name"])
            if not rename_no_replace(source, tombstone, "cleanup tombstone"):
                fail("cleanup tombstone already exists")
            fsync_directory(source.parent)
            fsync_directory(parent)
            cleanup_tombstone_state(target, entry, require_full=True)
        journal_payload = cleanup_journal_payload(target, entries, phase="journal")
        pending = cleanup_publish_file_no_replace(cleanup_journal_path(target), cleanup_journal_bytes(journal_payload), "cleanup journal")
        if pending:
            return True
        validate_cleanup_parent(target, allow_prepare=True, recover_aliases=True)
        if path_exists_no_follow(cleanup_prepare_path(target)):
            cleanup_prepare_path(target).unlink()
            fsync_directory(parent)
        _drained, still_pending = drain_cleanup_pending(target, allow_pending=True)
        return still_pending
    except BaseException:
        if validate_cleanup_parent(target, allow_prepare=True, recover_aliases=True) is not None:
            return True
        raise


def cleanup_mutation_result(target: Path, *, command: str) -> dict[str, Any]:
    return {
        "changed": True,
        "changes": ["cleanup-pending"],
        "cleanup_pending": False,
        "target": str(validate_target(target, create=False)),
        "operation": command,
    }


def cleanup_stage_directory(parent: Path, name: str, label: str) -> Path:
    path = parent / f".{name}.{os.getpid()}.{time.time_ns()}"
    parent_info = parent_metadata(parent, f"{label} parent")
    path.mkdir(mode=OWNER_DIRECTORY_MODE)
    path.chmod(OWNER_DIRECTORY_MODE)
    fsync_directory(parent)
    restore_directory_metadata(parent, parent_info, f"{label} parent")
    return path


def promote_lock_stage_alias(stage: Path, path: Path, label: str) -> bool:
    try:
        return rename_no_replace(stage, path, label)
    except KimicodeSetupError:
        if not path_exists_no_follow(stage) and path_exists_no_follow(path):
            return False
        raise


def publish_missing_lock_file(path: Path, label: str, *, canonical_target: str, kind: str) -> None:
    parent = path.parent
    if stat_existing(parent, f"{label} parent") is None:
        fail(f"{label} parent is missing")
    payload = canonical_json(lock_payload(kind, canonical_target, path))
    aliases = lock_stage_aliases(path, label)
    if aliases:
        identities: dict[Path, os.stat_result] = {}
        for alias in aliases:
            identities[alias] = read_valid_lock_stage_payload(
                alias,
                path,
                label,
                canonical_target=canonical_target,
                kind=kind,
            )
        promoting = aliases[0]
        revalidate_lock_stage_identity(promoting, identities[promoting], label)
        if promote_lock_stage_alias(promoting, path, label):
            fsync_directory(parent)
        return
    stage = path.with_name(f"{lock_stage_prefix(path)}{os.getpid()}.{time.time_ns()}")
    published = False
    try:
        write_lock_stage_file(stage, payload, f"{label} staged binding")
        if not rename_no_replace(stage, path, label):
            return
        published = True
        fsync_directory(parent)
    except BaseException:
        if path_exists_no_follow(stage):
            with contextlib.suppress(BaseException):
                cleanup_lock_stage_file(stage)
        raise
    if published:
        fd = open_lock_file(path, label, create=False)
        if fd is None:
            fail(f"{label} disappeared after publication")
        try:
            validate_lock_binding(
                read_lock_payload(fd, label),
                kind=kind,
                canonical_target=canonical_target,
                path=path,
                label=label,
            )
        finally:
            os.close(fd)


def drain_lock_stage_aliases_after_lock(
    fd: int,
    path: Path,
    label: str,
    *,
    canonical_target: str,
    kind: str,
) -> None:
    aliases = lock_stage_aliases(path, label)
    if not aliases:
        return
    identities: dict[Path, os.stat_result] = {}
    for alias in aliases:
        identities[alias] = read_valid_lock_stage_payload(alias, path, label, canonical_target=canonical_target, kind=kind)
    parent_fd = open_directory_fd(path.parent, f"{label} parent")
    parent_info = os.fstat(parent_fd)
    for alias in aliases:
        revalidate_lock_stage_identity(alias, identities[alias], label)
        try:
            alias.unlink()
        except FileNotFoundError:
            continue
    try:
        os.fsync(parent_fd)
        restore_directory_metadata_fd(parent_fd, parent_info, f"{label} parent")
        os.fsync(parent_fd)
        fd_info = os.fstat(fd)
        current = verify_lock_fd_path(fd, path, label)
        if current.st_dev != fd_info.st_dev or current.st_ino != fd_info.st_ino or current.st_nlink != 1:
            fail(f"{label} changed while draining staged aliases")
    finally:
        os.close(parent_fd)


def open_lock_file(path: Path, label: str, *, create: bool = False) -> int | None:
    flags = os.O_RDWR
    if not hasattr(os, "O_NOFOLLOW"):
        fail("lifecycle lock requires O_NOFOLLOW support")
    flags |= os.O_NOFOLLOW
    expected = stat_existing(path, label)
    if expected is not None:
        validate_lock_info(expected, label)
    try:
        fd = os.open(path, flags, OWNER_FILE_MODE)
    except FileNotFoundError:
        if create:
            fail(f"{label} is missing")
        return None
    except OSError as exc:
        fail(f"{label} could not be opened safely: {exc}")
    try:
        info = os.fstat(fd)
        os.fchmod(fd, OWNER_FILE_MODE)
        info = os.fstat(fd)
        validate_lock_info(info, label)
        current = stat_existing(path, label)
        if current is None:
            fail(f"{label} disappeared while opening")
        validate_lock_info(current, label)
        if current.st_dev != info.st_dev or current.st_ino != info.st_ino:
            fail(f"{label} changed while opening")
    except BaseException:
        os.close(fd)
        raise
    return fd


def verify_lock_fd_path(fd: int, path: Path, label: str) -> os.stat_result:
    info = os.fstat(fd)
    validate_lock_info(info, label)
    current = stat_existing(path, label)
    if current is None:
        fail(f"{label} disappeared")
    validate_lock_info(current, label)
    if current.st_dev != info.st_dev or current.st_ino != info.st_ino:
        fail(f"{label} changed")
    return info


def lock_payload(kind: str, canonical_target: str, path: Path) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "product_name": PRODUCT_NAME,
        "kind": kind,
        "canonical_target": canonical_target,
        "path": str(path),
        "pid": os.getpid(),
    }


def read_lock_payload(fd: int, label: str) -> dict[str, Any] | None:
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, METADATA_MAX_BYTES + 1)
    if len(data) > METADATA_MAX_BYTES:
        fail(f"{label} metadata is too large")
    if not data.strip():
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"{label} binding is malformed")
    if not isinstance(value, dict):
        fail(f"{label} binding is malformed")
    return value


def validate_lock_binding(
    payload: dict[str, Any] | None,
    *,
    kind: str,
    canonical_target: str,
    path: Path,
    label: str,
) -> None:
    if payload is None:
        fail(f"{label} binding is missing")
    if set(payload) != {"schema_version", "product_name", "kind", "canonical_target", "path", "pid"}:
        fail(f"{label} binding is malformed")
    if payload.get("schema_version") != 3:
        fail(f"{label} binding schema is unsupported")
    if payload.get("product_name") != PRODUCT_NAME or payload.get("kind") != kind:
        fail(f"{label} is bound to another lifecycle owner")
    if payload.get("canonical_target") != canonical_target:
        fail(f"{label} is bound to a different canonical target")
    if payload.get("path") != str(path):
        fail(f"{label} is bound to a different lock path")
    if not isinstance(payload.get("pid"), int) or payload.get("pid") < 0:
        fail(f"{label} binding is malformed")


def acquire_lock_file(
    path: Path,
    label: str,
    *,
    canonical_target: str,
    kind: str,
    create: bool,
    exclusive: bool,
) -> int | None:
    if stat_existing(path, label) is None:
        if create:
            publish_missing_lock_file(
                path,
                label,
                canonical_target=canonical_target,
                kind=kind,
            )
        else:
            aliases = lock_stage_aliases(path, label)
            for alias in aliases:
                read_valid_lock_stage_payload(alias, path, label, canonical_target=canonical_target, kind=kind)
            if aliases:
                fail(f"{label} has incomplete staged publication")
            return None
    fd = open_lock_file(path, label, create=False)
    if fd is None:
        if create:
            fail(f"{label} is missing")
        return None
    lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        fcntl.flock(fd, lock_mode | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            fail(f"target is locked: {path}")
        fail(f"{label} could not be locked: {exc}")
    try:
        verify_lock_fd_path(fd, path, label)
        validate_lock_binding(
            read_lock_payload(fd, label),
            kind=kind,
            canonical_target=canonical_target,
            path=path,
            label=label,
        )
        if exclusive:
            drain_lock_stage_aliases_after_lock(
                fd,
                path,
                label,
                canonical_target=canonical_target,
                kind=kind,
            )
        else:
            aliases = lock_stage_aliases(path, label)
            for alias in aliases:
                read_valid_lock_stage_payload(alias, path, label, canonical_target=canonical_target, kind=kind)
            if aliases:
                fail(f"{label} has incomplete staged publication")
    except BaseException:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        raise
    return fd


def release_lock_file(fd: int, path: Path, *, remove_file: bool = True, remove_empty_parent: bool = False) -> None:
    try:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    finally:
        if remove_file:
            with contextlib.suppress(OSError):
                if path_exists_no_follow(path) and not path.is_symlink():
                    path.unlink()
        if remove_empty_parent:
            with contextlib.suppress(OSError):
                path.parent.rmdir()


def protect_internal_lock_parent(path: Path) -> ProtectedDirectory:
    protected = open_protected_directory(path, "target lifecycle lock directory")
    protected.original_mode = OWNER_DIRECTORY_MODE
    return protected


def product_lock_binding_target() -> str:
    return PRODUCT_NAME


def expected_product_lock_payload(path: Path) -> bytes:
    return canonical_json(lock_payload("external-product", product_lock_binding_target(), path))


def validate_product_namespace(root: Path, *, allow_target_stage_aliases: bool) -> None:
    entries = bounded_directory_entries(root, "external lifecycle lock root")
    allowed = {PRODUCT_LOCK_NAME, TARGET_LOCK_ROOT_NAME}
    unknown = sorted(entry.name for entry in entries if entry.name not in allowed)
    if unknown:
        fail(f"external lifecycle lock root contains unknown entries: {', '.join(unknown[:4])}")
    target_root = target_lock_root_path(root)
    if path_exists_no_follow(target_root):
        info = stat_existing(target_root, "external target lock root")
        if info is None:
            fail("external target lock root is missing")
        if not stat.S_ISDIR(info.st_mode):
            fail("external target lock root must be a directory")
        if not is_current_owner(info):
            fail("external target lock root must be owned by the current user")
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail("external target lock root mode must be 0700")
        for entry in bounded_directory_entries(target_root, "external target lock root"):
            if entry.name.endswith(f".{EXTERNAL_LOCK_SUFFIX}") and re.fullmatch(
                r"[0-9a-f]{64}\." + re.escape(EXTERNAL_LOCK_SUFFIX),
                entry.name,
            ):
                info = stat_existing(entry, "external target lifecycle lock")
                if info is None:
                    raise ReadLifecycleRetry
                validate_lock_info(info, "external target lifecycle lock")
                continue
            if entry.name.startswith(".") and ".nddev.tmp." in entry.name:
                if allow_target_stage_aliases:
                    continue
                fail("external target lock root has incomplete staged publication")
            fail(f"external target lock root contains unknown entry: {entry.name}")


def ensure_product_namespace_ready_for_publication(root: Path, path: Path, label: str) -> None:
    aliases = lock_stage_aliases(path, label)
    alias_names = {alias.name for alias in aliases}
    unknown = [entry.name for entry in bounded_directory_entries(root, "external lifecycle lock root") if entry.name not in alias_names]
    if unknown:
        fail(f"external lifecycle lock root contains unknown entries: {', '.join(unknown[:4])}")


def finish_directory_creation_span(span: DirectoryCreationSpan | None, final_path: Path) -> None:
    if span is None:
        return
    if path_exists_no_follow(final_path):
        span.commit_parent_metadata()
    else:
        span.rollback()


def acquire_product_lock(*, create: bool, exclusive: bool) -> ProductLockHandle | None:
    root_span: DirectoryCreationSpan | None = None
    path: Path | None = None
    try:
        if create:
            root, root_span = ensure_external_lock_root_with_span()
        else:
            root = external_lock_root_no_create()
        if root is None:
            return None
        path = product_lock_path(root)
        if create and stat_existing(path, "external product lifecycle lock") is None:
            ensure_product_namespace_ready_for_publication(root, path, "external product lifecycle lock")
        fd = acquire_lock_file(
            path,
            "external product lifecycle lock",
            canonical_target=product_lock_binding_target(),
            kind="external-product",
            create=create,
            exclusive=exclusive,
        )
        if fd is None:
            finish_directory_creation_span(root_span, path)
            return None
    except BaseException:
        if path is not None:
            finish_directory_creation_span(root_span, path)
        elif root_span is not None:
            root_span.rollback()
        raise
    try:
        validate_product_namespace(root, allow_target_stage_aliases=exclusive)
        handle = ProductLockHandle(fd=fd, path=path, root=root)
    except BaseException:
        release_lock_file(fd, path, remove_file=False)
        finish_directory_creation_span(root_span, path)
        raise
    try:
        finish_directory_creation_span(root_span, path)
    except BaseException:
        release_lock_file(handle.fd, handle.path, remove_file=False)
        raise
    return handle


def release_product_lock(handle: ProductLockHandle | None) -> None:
    if handle is None:
        return
    release_lock_file(handle.fd, handle.path, remove_file=False)


def acquire_external_target_lock(
    product_root: Path,
    canonical_target: str,
    *,
    create: bool,
    exclusive: bool,
) -> ExternalTargetLockHandle | None:
    target_span: DirectoryCreationSpan | None = None
    path = bootstrap_lock_path_for_root(product_root, canonical_target)
    try:
        if create:
            target_root, target_span = ensure_external_target_lock_root_with_span(product_root)
        else:
            target_root = target_lock_root_path(product_root)
        if not create and stat_existing(target_root, "external target lock root") is None:
            return None
        fd = acquire_lock_file(
            path,
            "external target lifecycle lock",
            canonical_target=canonical_target,
            kind="external-bootstrap",
            create=create,
            exclusive=exclusive,
        )
        if fd is None:
            finish_directory_creation_span(target_span, path)
            return None
    except BaseException:
        finish_directory_creation_span(target_span, path)
        raise
    try:
        validate_product_namespace(product_root, allow_target_stage_aliases=exclusive)
        handle = ExternalTargetLockHandle(fd=fd, path=path, canonical_target=canonical_target)
    except BaseException:
        release_lock_file(fd, path, remove_file=False)
        finish_directory_creation_span(target_span, path)
        raise
    try:
        finish_directory_creation_span(target_span, path)
    except BaseException:
        release_lock_file(handle.fd, handle.path, remove_file=False)
        raise
    return handle


def release_external_target_lock(handle: ExternalTargetLockHandle | None) -> None:
    if handle is None:
        return
    release_lock_file(handle.fd, handle.path, remove_file=False)


def cold_product_namespace_snapshot(root: Path) -> tuple[Any, ...]:
    info = stat_existing(root, "external lifecycle lock root")
    if info is None:
        return ("absent",)
    if not stat.S_ISDIR(info.st_mode):
        fail("external lifecycle lock root must be a real directory")
    if not is_current_owner(info):
        fail("external lifecycle lock root must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("external lifecycle lock root mode must be 0700")
    entries = bounded_directory_entries(root, "external lifecycle lock root")
    if entries:
        if any(entry.name == PRODUCT_LOCK_NAME for entry in entries):
            raise ReadLifecycleRetry
        names = ", ".join(entry.name for entry in entries[:4])
        fail(f"external lifecycle lock root must be empty without product anchor: {names}")
    return (
        "present-empty",
        info.st_dev,
        info.st_ino,
        stat.S_IMODE(info.st_mode),
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
    )


@contextlib.contextmanager
def read_lifecycle_coordination(target: Path):
    product = acquire_product_lock(create=False, exclusive=False)
    external: ExternalTargetLockHandle | None = None
    if product is None:
        root = fixed_system_temp_root() / EXTERNAL_LOCK_ROOT_NAME
        before = cold_product_namespace_snapshot(root)
        try:
            canonical = validate_target(target, create=False)
            yield canonical
            after = cold_product_namespace_snapshot(root)
            if after != before:
                raise ReadLifecycleRetry
        except KimicodeSetupError:
            if cold_product_namespace_snapshot(root) != before:
                raise ReadLifecycleRetry
            raise
        return
    try:
        canonical = validate_target(target, create=False)
        identity = str(canonical)
        external = acquire_external_target_lock(
            product.root,
            identity,
            create=False,
            exclusive=False,
        )
        if external is not None:
            releasing_product = product
            product = None
            release_product_lock(releasing_product)
        yield canonical
        if external is None and product is not None:
            target_path = bootstrap_lock_path_for_root(product.root, identity)
            if path_exists_no_follow(target_path):
                raise ReadLifecycleRetry
            aliases = lock_stage_aliases(target_path, "external target lifecycle lock")
            for alias in aliases:
                read_valid_lock_stage_payload(
                    alias,
                    target_path,
                    "external target lifecycle lock",
                    canonical_target=identity,
                    kind="external-bootstrap",
                )
            if aliases:
                fail("external target lifecycle lock has incomplete staged publication")
    finally:
        release_external_target_lock(external)
        release_product_lock(product)


def read_lifecycle_payload(target: Path, reader: Any) -> Any:
    for attempt in range(READ_LIFECYCLE_MAX_ATTEMPTS):
        try:
            with read_lifecycle_coordination(target) as coordinated_target:
                return reader(coordinated_target)
        except ReadLifecycleRetry:
            if attempt + 1 >= READ_LIFECYCLE_MAX_ATTEMPTS:
                fail("read-only lifecycle coordination changed during inspection")
            continue
    fail("read-only lifecycle coordination changed during inspection")


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
    canonical_target = lock_canonical_target(target)
    product_lock: ProductLockHandle | None = None
    external_lock: ExternalTargetLockHandle | None = None
    internal_path: Path | None = None
    internal_fd: int | None = None
    internal_parent: ProtectedDirectory | None = None
    try:
        product_lock = acquire_product_lock(create=True, exclusive=True)
        if product_lock is None:
            fail("external product lifecycle lock was not created")
        external_lock = acquire_external_target_lock(
            product_lock.root,
            canonical_target,
            create=True,
            exclusive=True,
        )
        if external_lock is None:
            fail("external target lifecycle lock was not created")
        releasing_product = product_lock
        product_lock = None
        release_product_lock(releasing_product)
        target_info = stat_existing(target, "target")
        if target_info is None and create_parent:
            target.mkdir(mode=OWNER_DIRECTORY_MODE)
            target.chmod(OWNER_DIRECTORY_MODE)
            transaction.created.append(target)
            target_info = stat_existing(target, "target")
        if target_info is not None:
            if not stat.S_ISDIR(target_info.st_mode):
                fail("target must be a real directory")
            if not is_owner_private_directory(target_info):
                fail("target must be private and owned by the current user")
            lock_parent = ensure_lock_parent(target)
            internal_path = lock_path(target)
            internal_fd = acquire_lock_file(
                internal_path,
                "target lifecycle lock",
                canonical_target=canonical_target,
                kind="target-internal",
                create=True,
                exclusive=True,
            )
            if internal_fd is None:
                fail("target lifecycle lock was not created")
            internal_parent = protect_internal_lock_parent(lock_parent)
        failed = False
        try:
            yield transaction
        except BaseException:
            failed = True
            raise
        finally:
            try:
                if internal_fd is not None and internal_path is not None:
                    releasing_internal_fd = internal_fd
                    internal_fd = None
                    release_lock_file(releasing_internal_fd, internal_path, remove_file=False)
            finally:
                try:
                    if internal_parent is not None:
                        restoring_parent = internal_parent
                        internal_parent = None
                        restoring_parent.restore()
                finally:
                    if external_lock is not None:
                        releasing_external = external_lock
                        external_lock = None
                        release_external_target_lock(releasing_external)
            if failed:
                transaction.cleanup()
    except BaseException:
        if internal_fd is not None and internal_path is not None:
            releasing_internal_fd = internal_fd
            internal_fd = None
            release_lock_file(releasing_internal_fd, internal_path, remove_file=False)
        if internal_parent is not None:
            restoring_parent = internal_parent
            internal_parent = None
            restoring_parent.restore()
        if external_lock is not None:
            releasing_external = external_lock
            external_lock = None
            release_external_target_lock(releasing_external)
        if product_lock is not None:
            releasing_product = product_lock
            product_lock = None
            release_product_lock(releasing_product)
        transaction.cleanup()
        raise


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
            current.chmod(OWNER_DIRECTORY_MODE)
            continue
        if not stat.S_ISDIR(info.st_mode):
            fail(f"managed parent is not a directory: {current}")
        if not is_owner_private_directory(info):
            fail(f"managed parent must be private and owned by the current user: {current}")


def require_existing_managed_file(path: Path, label: str, *, max_bytes: int) -> os.stat_result | None:
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


def atomic_write(path: Path, data: bytes, target: Path, *, mode: int = OWNER_FILE_MODE) -> None:
    ensure_real_parent(path, target)
    require_existing_managed_file(path, str(path), max_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES))
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temporary, flags, mode)
    try:
        try:
            write_all(fd, data)
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
        fsync_directory(path.parent)
        info = require_existing_managed_file(path, str(path), max_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES))
        if info is None:
            fail(f"{path} atomic write postcondition is missing")
        if stat.S_IMODE(info.st_mode) != mode:
            fail(f"{path} atomic write mode postcondition failed")
        written = read_existing_file(path, max_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES), label=str(path))
        if written != data:
            fail(f"{path} atomic write content postcondition failed")
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        with contextlib.suppress(OSError):
            fsync_directory(path.parent)
        raise


def managed_file_state(target: Path, relative: str) -> ManagedFileState:
    path = safe_target_path(target, relative)
    info = stat_existing(path, relative)
    if info is None:
        return ManagedFileState(relative=relative, exists=False)
    if not stat.S_ISREG(info.st_mode):
        fail(f"{relative} must be a regular file")
    if not is_current_owner(info):
        fail(f"{relative} must be owned by the current user")
    if info.st_nlink != 1:
        fail(f"{relative} must not be a hardlink")
    if info.st_size > MANAGED_MAX_BYTES:
        fail(f"{relative} is too large")
    data = read_existing_file(path, max_bytes=MANAGED_MAX_BYTES, label=relative)
    if data is None:
        fail(f"{relative} changed while snapshotting")
    return ManagedFileState(
        relative=relative,
        exists=True,
        st_dev=info.st_dev,
        st_ino=info.st_ino,
        st_mode=stat.S_IMODE(info.st_mode),
        st_uid=info.st_uid,
        st_gid=info.st_gid,
        st_nlink=info.st_nlink,
        st_size=info.st_size,
        st_mtime_ns=info.st_mtime_ns,
        digest=sha256_bytes(data),
    )


def snapshot_directory_state(path: Path, label: str) -> ManagedDirectoryState:
    info = require_real_directory(path, label)
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    return ManagedDirectoryState(
        path=path,
        st_dev=info.st_dev,
        st_ino=info.st_ino,
        st_uid=info.st_uid,
        st_gid=info.st_gid,
        mode=stat.S_IMODE(info.st_mode),
        st_nlink=info.st_nlink,
        st_size=info.st_size,
        atime_ns=info.st_atime_ns,
        mtime_ns=info.st_mtime_ns,
    )


def restore_managed_directory_state(state: ManagedDirectoryState, *, strict_topology: bool) -> None:
    fd = open_directory_fd(state.path, str(state.path))
    try:
        current = os.fstat(fd)
        if current.st_dev != state.st_dev or current.st_ino != state.st_ino:
            fail(f"managed directory changed before metadata restore: {state.path}")
        if not stat.S_ISDIR(current.st_mode):
            fail(f"managed directory is not a directory: {state.path}")
        if current.st_uid != state.st_uid or current.st_gid != state.st_gid:
            fail(f"managed directory ownership changed before metadata restore: {state.path}")
        if strict_topology and (current.st_nlink != state.st_nlink or current.st_size != state.st_size):
            fail(f"managed directory topology changed before metadata restore: {state.path}")
        if stat.S_IMODE(current.st_mode) != state.mode:
            os.fchmod(fd, state.mode)
        os.utime(fd, ns=(state.atime_ns, state.mtime_ns))
        os.fsync(fd)
    finally:
        os.close(fd)


class ManagedObjectTransaction:
    def __init__(self, target: Path, relatives: tuple[str, ...]):
        self.target = target
        self.relatives = tuple(dict.fromkeys(relatives))
        self.states = {relative: managed_file_state(target, relative) for relative in self.relatives}
        self.held: dict[str, Path] = {}
        self.active_states: dict[str, ManagedFileState] = {}
        self.touched: set[str] = set()
        self.created_dirs: set[Path] = set()
        self.directory_states: dict[Path, ManagedDirectoryState] = {}
        self.closed = False
        require_owner_private_directory(target.parent, "managed rollback parent")
        self.parent_state = snapshot_directory_state(target.parent, "managed rollback parent")
        self.hold_root = target.parent / f".{target.name}.nddev-kimicode-managed-rollback.{os.getpid()}.{time.time_ns()}"
        self.hold_root.mkdir(mode=OWNER_DIRECTORY_MODE)
        self.hold_root.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(target.parent)
        self.capture_existing_directory(target)
        for relative in self.relatives:
            path = safe_target_path(target, relative)
            current = path.parent
            chain: list[Path] = []
            while current != target and target in current.parents:
                chain.append(current)
                current = current.parent
            for directory in reversed(chain):
                self.capture_existing_directory(directory)

    def capture_existing_directory(self, path: Path) -> None:
        info = stat_existing(path, str(path))
        if info is None:
            return
        if not stat.S_ISDIR(info.st_mode):
            fail(f"managed path parent must be a directory: {path}")
        if path not in self.directory_states:
            self.directory_states[path] = snapshot_directory_state(path, str(path))

    def hold_path(self, relative: str) -> Path:
        digest = sha256_bytes(relative.encode("utf-8"))
        return self.hold_root / f"{digest}.held"

    def revalidate_expected(self, relative: str) -> None:
        state = self.states.get(relative)
        if state is None:
            state = managed_file_state(self.target, relative)
            self.states[relative] = state
        path = safe_target_path(self.target, relative)
        info = stat_existing(path, relative)
        if not state.exists:
            if info is not None:
                fail(f"managed path changed before transition: {relative}")
            return
        if info is None:
            fail(f"managed path disappeared before transition: {relative}")
        if not stat.S_ISREG(info.st_mode):
            fail(f"managed path changed kind before transition: {relative}")
        if (
            info.st_dev != state.st_dev
            or info.st_ino != state.st_ino
            or stat.S_IMODE(info.st_mode) != state.st_mode
            or info.st_uid != state.st_uid
            or info.st_gid != state.st_gid
            or info.st_nlink != state.st_nlink
            or info.st_size != state.st_size
            or info.st_mtime_ns != state.st_mtime_ns
        ):
            fail(f"managed path changed before transition: {relative}")
        data = read_existing_file(path, max_bytes=MANAGED_MAX_BYTES, label=relative)
        if data is None or sha256_bytes(data) != state.digest:
            fail(f"managed path content changed before transition: {relative}")

    def ensure_parent(self, path: Path) -> None:
        relative_parent = path.relative_to(self.target).parent
        current = self.target
        for part in relative_parent.parts:
            current = current / part
            info = stat_existing(current, f"managed directory {current}")
            if info is None:
                parent = current.parent
                require_owner_private_directory(parent, f"managed parent {parent}")
                current.mkdir(mode=OWNER_DIRECTORY_MODE)
                current.chmod(OWNER_DIRECTORY_MODE)
                self.created_dirs.add(current)
                fsync_directory(parent)
                continue
            if not stat.S_ISDIR(info.st_mode):
                fail(f"managed parent is not a directory: {current}")
            if not is_owner_private_directory(info):
                fail(f"managed parent must be private and owned by the current user: {current}")
            self.capture_existing_directory(current)

    def stage_original(self, relative: str) -> None:
        if relative in self.held:
            return
        self.revalidate_expected(relative)
        state = self.states[relative]
        self.touched.add(relative)
        if not state.exists:
            return
        path = safe_target_path(self.target, relative)
        hold = self.hold_path(relative)
        path.rename(hold)
        self.held[relative] = hold
        fsync_directory(path.parent)
        fsync_directory(self.hold_root)

    def write_file(self, relative: str, data: bytes, *, mode: int = OWNER_FILE_MODE) -> None:
        path = safe_target_path(self.target, relative)
        self.stage_original(relative)
        self.ensure_parent(path)
        atomic_write(path, data, self.target, mode=mode)
        self.active_states[relative] = managed_file_state(self.target, relative)
        self.touched.add(relative)

    def delete_file(self, relative: str) -> None:
        self.stage_original(relative)
        self.active_states.pop(relative, None)
        self.touched.add(relative)

    def remove_managed_block(self, relative: str) -> None:
        self.revalidate_expected(relative)
        state = self.states[relative]
        if not state.exists:
            return
        path = safe_target_path(self.target, relative)
        data = read_existing_file(path, max_bytes=MANAGED_MAX_BYTES, label=relative)
        if data is None:
            fail(f"managed path disappeared before transition: {relative}")
        text = data.decode("utf-8")
        block = extract_managed_block(relative, text)
        if block is None:
            return
        updated = text.replace(block, "").encode("utf-8")
        if updated.strip():
            self.write_file(relative, updated)
        else:
            self.delete_file(relative)

    def validate_active_file_for_rollback(self, relative: str) -> None:
        path = safe_target_path(self.target, relative)
        info = stat_existing(path, relative)
        if info is None:
            return
        active = self.active_states.get(relative)
        if active is None:
            fail(f"managed rollback refuses concurrent replacement at active path: {relative}")
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_dev != active.st_dev
            or info.st_ino != active.st_ino
            or stat.S_IMODE(info.st_mode) != active.st_mode
            or info.st_uid != active.st_uid
            or info.st_gid != active.st_gid
            or info.st_nlink != active.st_nlink
            or info.st_size != active.st_size
            or info.st_mtime_ns != active.st_mtime_ns
        ):
            fail(f"managed rollback refuses concurrent replacement at active path: {relative}")
        data = read_existing_file(path, max_bytes=MANAGED_MAX_BYTES, label=relative)
        if data is None or sha256_bytes(data) != active.digest:
            fail(f"managed rollback refuses concurrent replacement at active path: {relative}")

    def remove_active_file_if_present(self, relative: str) -> None:
        path = safe_target_path(self.target, relative)
        info = stat_existing(path, relative)
        if info is None:
            return
        self.validate_active_file_for_rollback(relative)
        path.unlink()
        fsync_directory(path.parent)

    def prune_created_dirs(self) -> None:
        for directory in sorted(self.created_dirs, key=lambda item: len(item.parts), reverse=True):
            with contextlib.suppress(OSError):
                directory.rmdir()
                fsync_directory(directory.parent)

    def restore_directory_metadata(self, *, strict_topology: bool) -> None:
        for path in sorted(self.directory_states, key=lambda item: len(item.parts), reverse=True):
            if path_exists_no_follow(path):
                restore_managed_directory_state(self.directory_states[path], strict_topology=strict_topology)
        if path_exists_no_follow(self.parent_state.path):
            restore_managed_directory_state(self.parent_state, strict_topology=strict_topology)

    def rollback(self) -> None:
        if self.closed:
            return
        try:
            for relative in sorted(self.touched):
                self.validate_active_file_for_rollback(relative)
            for relative in sorted(self.touched):
                self.remove_active_file_if_present(relative)
            for relative, hold in self.held.items():
                path = safe_target_path(self.target, relative)
                parent = path.parent
                if not path_exists_no_follow(parent):
                    fail(f"managed rollback parent is missing: {parent}")
                hold.rename(path)
                fsync_directory(parent)
            self.prune_created_dirs()
            self.cleanup_hold_root()
            self.restore_directory_metadata(strict_topology=True)
        finally:
            self.closed = True

    def commit(self) -> None:
        if self.closed:
            return
        try:
            self.cleanup_hold_root()
            self.restore_directory_metadata(strict_topology=False)
        finally:
            self.closed = True

    def cleanup_hold_root(self) -> None:
        if not path_exists_no_follow(self.hold_root):
            return
        for child in sorted(self.hold_root.iterdir(), key=lambda item: item.name):
            info = child.lstat()
            if stat.S_ISREG(info.st_mode) and is_current_owner(info) and info.st_nlink == 1:
                child.unlink()
            else:
                fail(f"managed rollback hold contains unexpected path: {child.name}")
        self.hold_root.rmdir()
        fsync_directory(self.hold_root.parent)


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


def file_sha256(path: Path, *, label: str, max_bytes: int = SOFTWARE_MAX_BYTES) -> str:
    digest = hashlib.sha256()
    total = 0
    fd, _ = open_regular_readonly(path, label, max_bytes=max_bytes)
    with os.fdopen(fd, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                fail(f"{label} is too large")
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256_from_fd(fd: int, label: str, *, max_bytes: int = SOFTWARE_MAX_BYTES) -> str:
    digest = hashlib.sha256()
    total = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
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


def load_content_setup(setup_id: str) -> dict[str, Any]:
    if not ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id}")
    path = SETUP_ROOT / setup_id / "setup.json"
    if not path.is_file():
        fail(f"unknown content setup: {setup_id}")
    setup = read_json_file(path, max_bytes=METADATA_MAX_BYTES, label=f"content setup {setup_id}")
    if setup.get("id") != setup_id:
        fail(f"content setup id mismatch in {path}")
    return setup


def load_profile(profile_id: str) -> dict[str, Any]:
    if not ID_PATTERN.fullmatch(profile_id):
        fail(f"invalid profile id: {profile_id}")
    path = PROFILE_ROOT / profile_id / "profile.json"
    if not path.is_file():
        fail(f"unknown permission profile: {profile_id}")
    profile_data = read_json_file(path, max_bytes=METADATA_MAX_BYTES, label=f"profile {profile_id}")
    if profile_data.get("id") != profile_id:
        fail(f"profile id mismatch in {path}")
    mode = profile_data.get("native_permission_mode")
    if mode not in {"manual", "auto"}:
        fail(f"profile {profile_id} must use supported native permission mode manual or auto")
    return profile_data


def list_catalog() -> dict[str, Any]:
    content_setups = []
    for setup_id in CONTENT_SETUP_ORDER:
        setup = load_content_setup(setup_id)
        content_setups.append(
            {
                "id": setup["id"],
                "display_name": setup["display_name"],
                "description": setup["description"],
                "default": setup["id"] == DEFAULT_CONTENT_SETUP,
            }
        )
    profiles = []
    for profile_id in PROFILE_ORDER:
        profile_data = load_profile(profile_id)
        profiles.append(
            {
                "id": profile_data["id"],
                "display_name": profile_data["display_name"],
                "description": profile_data["description"],
                "native_permission_mode": profile_data["native_permission_mode"],
                "plan_mode": profile_data["plan_mode"],
                "default": profile_data["id"] == DEFAULT_PROFILE,
            }
        )
    return {
        "content_setups": [item["id"] for item in content_setups],
        "profiles": [item["id"] for item in profiles],
        "default_content_setup": DEFAULT_CONTENT_SETUP,
        "default_profile": DEFAULT_PROFILE,
        "items": {"content_setups": content_setups, "profiles": profiles},
    }


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


def render_permission_rules(profile_data: dict[str, Any]) -> str:
    rendered = []
    rules = profile_data.get("permission_rules", [])
    if not isinstance(rules, list):
        fail("permission_rules must be a list")
    for rule in rules:
        if not isinstance(rule, dict):
            fail("permission rule must be an object")
        decision = rule.get("decision")
        pattern = rule.get("pattern")
        if decision not in {"allow", "ask", "deny"} or not isinstance(pattern, str):
            fail("permission rule must include supported decision and string pattern")
        rendered.append("[[permission.rules]]\n")
        rendered.append(f"decision = {toml_string(decision)}\n")
        rendered.append(f"pattern = {toml_string(pattern)}\n")
        reason = rule.get("reason")
        if isinstance(reason, str):
            rendered.append(f"reason = {toml_string(reason)}\n")
        rendered.append("\n")
    return "".join(rendered)


def render_config(target: Path, setup: dict[str, Any], profile_data: dict[str, Any]) -> str:
    canonical = validate_target(target, create=False)
    skill_dir = str((canonical / "skills").resolve())
    agent_dir = str((canonical / "agents").resolve())
    hook_path = canonical / "hooks" / "nddev-builder-pretooluse.py"
    hook_command = "python3 " + shlex.quote(str(hook_path.resolve()))
    hook_block = ""
    if profile_data["id"] == "safe":
        hook_block = (
            "[[hooks]]\n"
            'event = "PreToolUse"\n'
            'matcher = "Bash"\n'
            f"command = {toml_string(hook_command)}\n"
            "timeout = 5\n"
        )
    return (
        f"{MANAGED_BEGIN}\n"
        "# Managed by nddev-kimicode-app. Edit outside this block to preserve local state.\n"
        f"default_permission_mode = {toml_string(str(profile_data['native_permission_mode']))}\n"
        f"default_plan_mode = {toml_bool(bool(profile_data['plan_mode']))}\n"
        f"extra_skill_dirs = {toml_array([skill_dir])}\n"
        f"extra_agent_dirs = {toml_array([agent_dir])}\n"
        "\n"
        "[loop_control]\n"
        f"max_steps_per_turn = {int(profile_data['max_steps_per_turn'])}\n"
        "\n"
        "[background]\n"
        f"max_running_tasks = {int(profile_data['max_running_tasks'])}\n"
        "\n"
        f"{render_permission_rules(profile_data)}"
        f"{hook_block}"
        f"{MANAGED_END}\n"
    )


def render_tui() -> str:
    return (
        f"{MANAGED_BEGIN}\n"
        "# Managed by nddev-kimicode-app.\n"
        "[upgrade]\n"
        "auto_install = false\n"
        f"{MANAGED_END}\n"
    )


def render_agents_block(setup: dict[str, Any], profile_data: dict[str, Any]) -> str:
    return (
        f"{MD_MANAGED_BEGIN}\n"
        "\n"
        "# NDDev Kimi Code Setup\n"
        "\n"
        "This Kimi Code home is managed by nddev-kimicode-app.\n"
        f"- Content setup: `{setup['id']}`.\n"
        f"- Permission profile: `{profile_data['id']}` using native Kimi `{profile_data['native_permission_mode']}` mode.\n"
        "- Exact release, checksum, schema, and lifecycle facts are owned by the manager,\n"
        "  config/nddev-contract.json, build/manifest.json, and references/kimi-code-baseline.json.\n"
        "- Use only documented Kimi Code surfaces projected here: AGENTS.md, Skills,\n"
        "  custom Agents, hooks, MCP JSON, and plugin source manifests.\n"
        "- Do not write Kimi runtime-owned plugins/installed.json. Use Kimi's native\n"
        "  /plugins UI or slash commands if plugin installation is ever explicitly required.\n"
        "- Credentials, OAuth state, sessions, logs, updates, and user history stay under\n"
        "  this explicit target through KIMI_CODE_HOME.\n"
        "\n"
        f"{MD_MANAGED_END}\n"
    )


def builder_source(relative: str) -> bytes:
    path = BUILDER_ROOT / relative
    if not path.is_file():
        fail(f"builder source missing: {relative}")
    if path.is_symlink():
        fail(f"builder source must be a regular file: {relative}")
    data = path.read_bytes()
    if len(data) > MANAGED_MAX_BYTES:
        fail(f"builder source too large: {relative}")
    return data


def builder_skill_sources() -> dict[str, bytes]:
    skill_root = BUILDER_ROOT / "skills"
    if not skill_root.is_dir():
        fail("builder skills root is missing")
    files: dict[str, bytes] = {}
    for path in sorted(skill_root.rglob("*"), key=lambda item: item.relative_to(skill_root).as_posix()):
        relative = path.relative_to(skill_root).as_posix()
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"builder skill source must be a regular file: {relative}")
        data = path.read_bytes()
        if len(data) > MANAGED_MAX_BYTES:
            fail(f"builder skill source too large: {relative}")
        files[f"skills/{relative}"] = data
    if "skills/nddev-builder/SKILL.md" not in files:
        fail("builder entry Skill is missing")
    return files


def content_managed_paths() -> tuple[str, ...]:
    return (*CONTENT_MANAGED_BASE_PATHS, *builder_skill_sources().keys())


def desired_files(target: Path, setup: dict[str, Any], profile_data: dict[str, Any]) -> dict[str, bytes]:
    existing_config = read_existing_file(target / "config.toml", max_bytes=MANAGED_MAX_BYTES, label="config.toml")
    existing_tui = read_existing_file(target / "tui.toml", max_bytes=MANAGED_MAX_BYTES, label="tui.toml")
    existing_agents = read_existing_file(target / "AGENTS.md", max_bytes=MANAGED_MAX_BYTES, label="AGENTS.md")
    files = {
        "config.toml": merge_managed_block("config.toml", existing_config, render_config(target, setup, profile_data)),
        "tui.toml": merge_managed_block("tui.toml", existing_tui, render_tui()),
        "AGENTS.md": merge_managed_block("AGENTS.md", existing_agents, render_agents_block(setup, profile_data)),
        "mcp.json": canonical_json({"mcpServers": {}}),
        "agents/nddev-builder.md": builder_source("agents/nddev-builder.md"),
        "hooks/nddev-builder-pretooluse.py": builder_source("hooks/nddev-builder-pretooluse.py"),
    }
    files.update(builder_skill_sources())
    return files


def managed_digest_for_bytes(relative: str, data: bytes) -> str:
    if relative in MERGED_MARKER_PATHS:
        block = extract_managed_block(relative, data.decode("utf-8"))
        if block is None:
            return ""
        return sha256_bytes(block.encode("utf-8"))
    return sha256_bytes(data)


def current_managed_digest(target: Path, relative: str) -> str | None:
    data = read_existing_file(safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative)
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


def stamp_is_current(stamp: dict[str, Any]) -> bool:
    return stamp.get("schema_version") == CURRENT_SETUP_SCHEMA


def stamp_descriptor(stamp: dict[str, Any] | None) -> dict[str, Any]:
    if stamp is None:
        return {
            "schema_version": None,
            "content_setup_id": None,
            "permission_profile_id": None,
            "legacy_setup_id": None,
            "legacy": False,
        }
    if stamp_is_current(stamp):
        return {
            "schema_version": CURRENT_SETUP_SCHEMA,
            "content_setup_id": stamp.get("content_setup_id"),
            "permission_profile_id": stamp.get("permission_profile_id"),
            "legacy_setup_id": None,
            "legacy": False,
        }
    return {
        "schema_version": stamp.get("schema_version", LEGACY_SETUP_SCHEMA),
        "content_setup_id": None,
        "permission_profile_id": None,
        "legacy_setup_id": stamp.get("setup_id"),
        "legacy": True,
    }


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


def auth_state(target: Path) -> dict[str, str]:
    credentials = target / "credentials"
    info = stat_existing(credentials, "credentials")
    if info is None:
        return {"state": "pre-login", "path": str(credentials), "scope": "target KIMI_CODE_HOME"}
    require_owner_private_directory(credentials, "credentials")
    return {"state": "target-local", "path": str(credentials), "scope": "target KIMI_CODE_HOME"}


def status_payload(target: Path) -> dict[str, Any]:
    return read_lifecycle_payload(target, _status_payload)


def _status_payload(target: Path) -> dict[str, Any]:
    canonical = validate_target(target, create=False)
    cleanup_state = cleanup_pending_state(canonical)
    if stat_existing(target, "target") is None:
        return {
            "state": "absent",
            "managed": False,
            "launch_allowed": False,
            "canonical_target": str(canonical),
            "content_setup_id": None,
            "permission_profile_id": None,
            "legacy_setup_id": None,
            "drift": [],
            "auth_state": {"state": "absent", "path": str(target / "credentials"), "scope": "target KIMI_CODE_HOME"},
            **cleanup_state,
        }
    require_owner_private_directory(target, "target")
    stamp = read_stamp(target)
    if stamp is None:
        return {
            "state": "unmanaged",
            "managed": False,
            "launch_allowed": False,
            "canonical_target": str(canonical),
            "content_setup_id": None,
            "permission_profile_id": None,
            "legacy_setup_id": None,
            "drift": [],
            "auth_state": auth_state(target),
            **cleanup_state,
        }
    descriptor = stamp_descriptor(stamp)
    drift = drift_for_stamp(target, stamp)
    current = stamp_is_current(stamp)
    software = _software_status_payload(canonical)
    return {
        "state": "managed" if current else "legacy-managed",
        "managed": True,
        "launch_allowed": bool(current and not drift and software["current"]),
        "canonical_target": str(canonical),
        "content_setup_id": descriptor["content_setup_id"],
        "permission_profile_id": descriptor["permission_profile_id"],
        "legacy_setup_id": descriptor["legacy_setup_id"],
        "schema_version": descriptor["schema_version"],
        "build_version": stamp.get("build_version"),
        "drift": drift,
        "managed_files": sorted(stamp["managed_files"]),
        "software_current": software["current"],
        "software_drift": software["drift"],
        "auth_state": auth_state(target),
        **cleanup_state,
    }


def stamp_managed_paths(stamp: dict[str, Any] | None) -> tuple[str, ...]:
    if stamp is None:
        return ()
    managed = stamp.get("managed_files")
    if not isinstance(managed, dict):
        return ()
    return tuple(str(path) for path in managed)


def choose_backup_slot(pool: Path) -> int:
    ensure_private_directory(pool, "backup pool")
    for slot in range(10):
        if not path_exists_no_follow(pool / str(slot)):
            return slot
    return min(range(10), key=lambda item: (pool / str(item)).lstat().st_mtime_ns)


def ensure_private_directory(path: Path, label: str, *, transaction: DirectoryTransaction | None = None) -> None:
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


def create_backup(target: Path, stamp: dict[str, Any]) -> tuple[int, bool]:
    pool = backup_pool(target)
    slot = choose_backup_slot(pool)
    slot_dir = pool / str(slot)
    stage_dir = cleanup_stage_directory(
        target.parent,
        f"{target.name}.nddev-kimicode-backup-stage",
        "backup stage",
    )
    retired_dir = target.parent / f".{target.name}.nddev-kimicode-backup-retired.{slot}.{os.getpid()}.{time.time_ns()}"
    old_retired = False
    published = False
    try:
        files: dict[str, Any] = {}
        backup_paths = tuple(dict.fromkeys((*content_managed_paths(), *stamp_managed_paths(stamp), STAMP_NAME)))
        for relative in backup_paths:
            data = read_existing_file(safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative)
            files[relative] = None if data is None else base64.b64encode(data).decode("ascii")
        descriptor = stamp_descriptor(stamp)
        envelope = {
            "schema_version": 1,
            "product_name": PRODUCT_NAME,
            "build_version": VERSION,
            "slot": slot,
            "canonical_target": str(validate_target(target, create=False)),
            "source": descriptor,
            "created_at": int(time.time()),
            "files": files,
        }
        atomic_write(stage_dir / BACKUP_NAME, canonical_json(envelope), stage_dir)
        slot_info = stat_existing(slot_dir, f"backup slot {slot}")
        if slot_info is not None:
            if not stat.S_ISDIR(slot_info.st_mode):
                fail(f"backup slot {slot} must be a directory")
            if not rename_no_replace(slot_dir, retired_dir, "backup slot retirement"):
                fail(f"backup slot {slot} retirement destination already exists")
            old_retired = True
            fsync_directory(pool)
            fsync_directory(target.parent)
        if not rename_no_replace(stage_dir, slot_dir, "backup slot publication"):
            fail(f"backup slot {slot} already exists")
        published = True
        fsync_directory(pool)
        pending = finish_postcommit_cleanup(target, "backup-rotate", [retired_dir])
        return slot, pending
    except BaseException:
        if old_retired and not published and not path_exists_no_follow(slot_dir) and path_exists_no_follow(retired_dir):
            with contextlib.suppress(BaseException):
                rename_no_replace(retired_dir, slot_dir, "backup slot rollback")
                old_retired = False
                fsync_directory(pool)
                fsync_directory(target.parent)
        if not published:
            finish_postcommit_cleanup(target, "backup-stage", [stage_dir, retired_dir])
        raise


def build_stamp(target: Path, setup: dict[str, Any], profile_data: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    managed = {relative: managed_digest_for_bytes(relative, data) for relative, data in files.items()}
    return {
        "schema_version": CURRENT_SETUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "content_setup_id": setup["id"],
        "permission_profile_id": profile_data["id"],
        "canonical_target": str(validate_target(target, create=False)),
        "managed_files": managed,
    }


def write_setup(
    target: Path,
    setup: dict[str, Any],
    profile_data: dict[str, Any],
    *,
    require_existing: bool = False,
    migrate_legacy: bool = False,
) -> dict[str, Any]:
    with target_lock(target, create_parent=not require_existing) as transaction:
        validate_target(target, create=not require_existing, transaction=transaction)
        cleanup_drained = drain_cleanup_before_mutation(target)
        current = read_stamp(target)
        if require_existing and current is None:
            fail("operation requires an already managed target")
        if current is not None:
            current_legacy = not stamp_is_current(current)
            if current_legacy and not migrate_legacy:
                fail("managed target uses a legacy setup schema; use migrate")
            if not current_legacy and migrate_legacy:
                return {
                    "changed": False,
                    "content_setup_id": current.get("content_setup_id"),
                    "permission_profile_id": current.get("permission_profile_id"),
                    "backup_slot": None,
                    "target": str(validate_target(target, create=False)),
                    "cleanup_drained": cleanup_drained,
                    **cleanup_pending_state(validate_target(target, create=False)),
                }
            drift = drift_for_stamp(target, current)
            if drift:
                fail(f"managed target has drift: {', '.join(drift)}")
        files = desired_files(target, setup, profile_data)
        desired_stamp = build_stamp(target, setup, profile_data, files)
        changed = [
            relative
            for relative, data in files.items()
            if current_managed_digest(target, relative) != managed_digest_for_bytes(relative, data)
        ]
        backup_slot = None
        backup_cleanup_pending = False
        if current is not None:
            descriptor = stamp_descriptor(current)
            if (
                descriptor["legacy"]
                or descriptor["content_setup_id"] != setup["id"]
                or descriptor["permission_profile_id"] != profile_data["id"]
            ):
                backup_slot, backup_cleanup_pending = create_backup(target, current)
        stale_paths = ()
        if current is not None:
            stale_paths = tuple(path for path in stamp_managed_paths(current) if path not in files)
        managed_transaction = ManagedObjectTransaction(
            target,
            tuple(dict.fromkeys((*content_managed_paths(), *stale_paths, STAMP_NAME))),
        )
        try:
            for relative in stale_paths:
                if relative in MERGED_MARKER_PATHS:
                    managed_transaction.remove_managed_block(relative)
                else:
                    managed_transaction.delete_file(relative)
            for relative, data in files.items():
                managed_transaction.write_file(relative, data)
            managed_transaction.write_file(STAMP_NAME, canonical_json(desired_stamp))
            managed_transaction.commit()
        except BaseException:
            managed_transaction.rollback()
            raise
        cleanup_state = cleanup_pending_state(validate_target(target, create=False))
        cleanup_state["cleanup_pending"] = backup_cleanup_pending or cleanup_state["cleanup_pending"]
        return {
            "content_setup_id": setup["id"],
            "permission_profile_id": profile_data["id"],
            "changed": changed,
            "backup_slot": backup_slot,
            "target": str(validate_target(target, create=False)),
            "cleanup_drained": cleanup_drained,
            **cleanup_state,
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    if slot < 0 or slot > 9:
        fail("backup slot must be between 0 and 9")
    with target_lock(target, create_parent=True) as transaction:
        validate_target(target, create=True, transaction=transaction)
        cleanup_drained = drain_cleanup_before_mutation(target)
        envelope_path = backup_pool(target) / str(slot) / BACKUP_NAME
        envelope = read_json_file(envelope_path, max_bytes=METADATA_MAX_BYTES, label=BACKUP_NAME)
        if envelope.get("product_name") != PRODUCT_NAME:
            fail("backup belongs to another product")
        if envelope.get("canonical_target") != str(validate_target(target, create=False)):
            fail("backup is bound to a different canonical target")
        files = envelope.get("files")
        if not isinstance(files, dict):
            fail("backup files are invalid")
        decoded_files: dict[str, bytes | None] = {}
        for relative in (*files.keys(),):
            encoded = files.get(relative)
            if encoded is None:
                decoded_files[relative] = None
                continue
            if not isinstance(encoded, str):
                fail("backup file payload is invalid")
            try:
                decoded_files[relative] = base64.b64decode(encoded.encode("ascii"), validate=True)
            except (binascii.Error, ValueError):
                fail("backup file payload is invalid base64")
        managed_transaction = ManagedObjectTransaction(target, tuple(decoded_files))
        try:
            for relative, decoded in decoded_files.items():
                if decoded is None:
                    managed_transaction.delete_file(relative)
                else:
                    managed_transaction.write_file(relative, decoded)
            managed_transaction.commit()
        except BaseException:
            managed_transaction.rollback()
            raise
        restored_stamp = read_stamp(target)
        descriptor = stamp_descriptor(restored_stamp)
        return {
            "content_setup_id": descriptor["content_setup_id"],
            "permission_profile_id": descriptor["permission_profile_id"],
            "legacy_setup_id": descriptor["legacy_setup_id"],
            "backup_slot": slot,
            "target": str(validate_target(target, create=False)),
            "cleanup_drained": cleanup_drained,
            **cleanup_pending_state(validate_target(target, create=False)),
        }


def remove_managed_block_from_target(target: Path, relative: str) -> None:
    transaction = ManagedObjectTransaction(target, (relative,))
    try:
        transaction.remove_managed_block(relative)
        transaction.commit()
    except BaseException:
        transaction.rollback()
        raise


def prune_empty_managed_dirs(target: Path, extra_paths: tuple[str, ...] = ()) -> None:
    candidates: set[Path] = set()
    for relative in (*content_managed_paths(), *extra_paths):
        directory = safe_target_path(target, relative).parent
        while directory != target and target in directory.parents:
            candidates.add(directory)
            directory = directory.parent
    directories = sorted(candidates, key=lambda item: len(item.parts), reverse=True)
    for directory in directories:
        with contextlib.suppress(OSError):
            directory.rmdir()


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target):
        validate_target(target, create=False)
        cleanup_drained = drain_cleanup_before_mutation(target)
        stamp = read_stamp(target)
        if stamp is None:
            return {
                "removed": None,
                "target": str(validate_target(target, create=False)),
                "cleanup_drained": cleanup_drained,
                **cleanup_pending_state(validate_target(target, create=False)),
            }
        drift = drift_for_stamp(target, stamp)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        descriptor = stamp_descriptor(stamp)
        remove_paths = tuple(dict.fromkeys((*content_managed_paths(), *stamp_managed_paths(stamp))))
        managed_transaction = ManagedObjectTransaction(target, tuple(dict.fromkeys((*remove_paths, STAMP_NAME))))
        try:
            for relative in remove_paths:
                if relative in MERGED_MARKER_PATHS:
                    managed_transaction.remove_managed_block(relative)
                else:
                    managed_transaction.delete_file(relative)
            managed_transaction.delete_file(STAMP_NAME)
            managed_transaction.commit()
        except BaseException:
            managed_transaction.rollback()
            raise
        return {
            "removed": descriptor,
            "target": str(validate_target(target, create=False)),
            "cleanup_drained": cleanup_drained,
            **cleanup_pending_state(validate_target(target, create=False)),
        }


def plan_payload(target: Path, setup: dict[str, Any], profile_data: dict[str, Any], *, migrate_legacy: bool = False) -> dict[str, Any]:
    status = status_payload(target)
    operation = "install"
    backup_required = False
    if status["managed"]:
        if status["state"] == "legacy-managed":
            operation = "migrate" if migrate_legacy else "blocked-legacy"
            backup_required = migrate_legacy
        elif status["content_setup_id"] == setup["id"] and status["permission_profile_id"] == profile_data["id"]:
            operation = "update"
        else:
            operation = "switch-profile" if status["content_setup_id"] == setup["id"] else "switch"
            backup_required = True
    return {
        "operation": operation,
        "content_setup_id": setup["id"],
        "permission_profile_id": profile_data["id"],
        "target": status["canonical_target"],
        "current_content_setup_id": status["content_setup_id"],
        "current_permission_profile_id": status["permission_profile_id"],
        "legacy_setup_id": status["legacy_setup_id"],
        "drift": status["drift"],
        "backup_required": backup_required,
        "mutates": False,
        "cleanup_pending": status["cleanup_pending"],
        "cleanup_pending_phase": status.get("cleanup_pending_phase"),
        "cleanup_pending_entries": status.get("cleanup_pending_entries", []),
    }


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
    return sorted(label for path, label in labels if existing_path_label(path, label) is not None)


def validate_software_file(path: Path, label: str) -> os.stat_result:
    info = require_existing_managed_file(path, label, max_bytes=SOFTWARE_MAX_BYTES)
    if info is None:
        fail(f"{label} is missing")
    return info


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
    require_safe_partial_file(software_entrypoint(target), "Kimi Code entrypoint", max_bytes=SOFTWARE_MAX_BYTES)
    require_safe_partial_file(software_stamp_path(target), SOFTWARE_STAMP_NAME, max_bytes=METADATA_MAX_BYTES)


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
    if stamp.get("product_name") != PRODUCT_NAME:
        fail("software stamp belongs to another product")
    if stamp.get("canonical_target") != canonical_target_readonly(target):
        fail("software stamp is bound to a different canonical target")
    if stamp.get("schema_version") == CURRENT_SOFTWARE_SCHEMA:
        exact_keys(stamp, SOFTWARE_STAMP_KEYS_V2, SOFTWARE_STAMP_NAME)
    return stamp


def software_is_legacy(stamp: dict[str, Any] | None) -> bool:
    return stamp is not None and stamp.get("schema_version") != CURRENT_SOFTWARE_SCHEMA


def software_current_binary(target: Path) -> Path:
    return software_current(target) / "bin" / KIMI_COMMAND


def software_status_payload(target: Path) -> dict[str, Any]:
    return read_lifecycle_payload(target, _software_status_payload)


def _software_status_payload(target: Path) -> dict[str, Any]:
    canonical = canonical_target_readonly(target)
    payload: dict[str, Any] = {
        "installed": False,
        "current": False,
        "legacy": False,
        "migration_required": False,
        "version": None,
        "expected_version": KIMI_PACKAGE_VERSION,
        "command": KIMI_COMMAND,
        "executable": str(software_entrypoint(target)),
        "installed_tree": str(software_current(target)),
        "drift": [],
        "present": False,
        "presence": [],
        "canonical_target": canonical,
        **cleanup_pending_state(Path(canonical)),
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
    if software_is_legacy(stamp):
        payload["legacy"] = True
        payload["migration_required"] = True
        payload["drift"] = ["legacy_bun_schema"]
        return payload
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
        entrypoint_info = validate_software_file(software_entrypoint(target), "Kimi Code entrypoint")
        if stat.S_IMODE(entrypoint_info.st_mode) != 0o700:
            drift.append("entrypoint_mode")
        current_binary_info = validate_software_file(software_current_binary(target), "current Kimi Code binary")
        if stat.S_IMODE(current_binary_info.st_mode) != 0o700:
            drift.append("current_binary_mode")
        platform_key = stamp.get("platform")
        binary = stamp.get("binary")
        source = stamp.get("source")
        if platform_key not in KIMI_BINARY_PLATFORMS:
            drift.append("platform")
        expected_binary = KIMI_BINARY_PLATFORMS.get(str(platform_key), {})
        expected_url = f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/{expected_binary.get('filename')}"
        if (
            not isinstance(binary, dict)
            or binary.get("filename") != expected_binary.get("filename")
            or binary.get("url") != expected_url
            or binary.get("sha256") != expected_binary.get("checksum")
        ):
            drift.append("binary")
        expected_source = {
            "channel": "official-binary",
            "install_script_url": KIMI_INSTALL_SCRIPT_URL,
            "install_script_sha256": KIMI_INSTALL_SCRIPT_SHA256,
            "latest_url": KIMI_LATEST_URL,
            "manifest_url": KIMI_BINARY_MANIFEST_URL,
            "manifest_sha256": KIMI_BINARY_MANIFEST_SHA256,
            "github_release_url": KIMI_GITHUB_RELEASE_URL,
            "github_release_id": KIMI_GITHUB_RELEASE_ID,
            "git_tag": KIMI_GIT_TAG,
            "git_tag_object": KIMI_GIT_TAG_OBJECT,
            "git_commit": KIMI_GIT_COMMIT,
            "npm_package": KIMI_PACKAGE_NAME,
            "npm_integrity": KIMI_NPM_INTEGRITY,
            "npm_shasum": KIMI_NPM_SHASUM,
        }
        if source != expected_source:
            drift.append("source")
        entrypoint_digest = file_sha256(software_entrypoint(target), label="Kimi Code entrypoint")
        current_binary_digest = file_sha256(software_current_binary(target), label="current Kimi Code binary")
        installed_tree_digest = tree_sha256(software_current(target))
        if stamp.get("version") != KIMI_PACKAGE_VERSION:
            drift.append("version")
        if stamp.get("command") != KIMI_COMMAND:
            drift.append("command")
        if stamp.get("entrypoint") != "bin/kimi":
            drift.append("entrypoint")
        if stamp.get("entrypoint_kind") != "official-binary":
            drift.append("entrypoint_kind")
        if stamp.get("installed_tree") != f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}":
            drift.append("installed_tree")
        if stamp.get("manager") != "cli-tools/nddev_kimicode.py":
            drift.append("manager")
        if stamp.get("entrypoint_sha256") != entrypoint_digest:
            drift.append("entrypoint_sha256")
        if current_binary_digest != expected_binary.get("checksum"):
            drift.append("current_binary_sha256")
        if stamp.get("installed_tree_sha256") != installed_tree_digest:
            drift.append("installed_tree_sha256")
        probe = stamp.get("version_probe")
        if (
            not isinstance(probe, dict)
            or probe.get("argv") != ["bin/kimi", "--version"]
            or not isinstance(probe.get("stdout_stderr_sha256"), str)
        ):
            drift.append("version_probe")
    except KimicodeSetupError as exc:
        drift.append(str(exc))
    payload["drift"] = drift
    payload["current"] = not drift and stamp.get("version") == KIMI_PACKAGE_VERSION
    return payload


def detect_official_platform() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        os_name = "darwin"
    elif system == "Linux":
        os_name = "linux"
        musl_markers = (
            Path("/lib/libc.musl-x86_64.so.1"),
            Path("/lib/libc.musl-aarch64.so.1"),
        )
        if any(path.exists() for path in musl_markers):
            fail("musl Linux is not supported by nddev-kimicode-app")
        with contextlib.suppress(Exception):
            completed = subprocess.run(
                ["ldd", "/bin/ls"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                check=False,
            )
            if "musl" in completed.stdout.lower():
                fail("musl Linux is not supported by nddev-kimicode-app")
    else:
        fail("nddev-kimicode-app supports only macOS and Ubuntu/Linux glibc")
    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        fail(f"unsupported architecture: {platform.machine()}")
    key = f"{os_name}-{arch}"
    if key not in KIMI_BINARY_PLATFORMS:
        fail(f"unsupported platform: {key}")
    return key


def fetch_url_bytes(url: str, *, max_bytes: int, label: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=PROCESS_TIMEOUT_SECONDS) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.URLError as exc:
        fail(f"{label} could not be downloaded: {exc}")
    if len(data) > max_bytes:
        fail(f"{label} download is too large")
    return data


def install_official_binary(stage_current: Path, platform_key: str) -> dict[str, Any]:
    manifest_bytes = fetch_url_bytes(KIMI_BINARY_MANIFEST_URL, max_bytes=METADATA_MAX_BYTES, label="Kimi Code binary manifest")
    manifest_digest = sha256_bytes(manifest_bytes)
    if manifest_digest != KIMI_BINARY_MANIFEST_SHA256:
        fail("Kimi Code binary manifest digest does not match the pinned baseline")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"Kimi Code binary manifest is invalid JSON: {exc}")
    if not isinstance(manifest, dict):
        fail("Kimi Code binary manifest must be a JSON object")
    if manifest.get("version") != KIMI_PACKAGE_VERSION or manifest.get("tag") != KIMI_GIT_TAG:
        fail("Kimi Code binary manifest version does not match the pinned baseline")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or platforms.get(platform_key) != KIMI_BINARY_PLATFORMS[platform_key]:
        fail("Kimi Code binary manifest platform entry does not match the pinned baseline")
    binary = KIMI_BINARY_PLATFORMS[platform_key]
    url = f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/{binary['filename']}"
    binary_bytes = fetch_url_bytes(url, max_bytes=DOWNLOAD_MAX_BYTES, label="Kimi Code binary")
    if sha256_bytes(binary_bytes) != binary["checksum"]:
        fail("Kimi Code binary digest does not match the pinned baseline")
    bin_dir = stage_current / "bin"
    bin_dir.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True)
    destination = bin_dir / KIMI_COMMAND
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(fd, "wb") as handle:
        handle.write(binary_bytes)
    destination.chmod(0o700)
    return {"platform": platform_key, "filename": binary["filename"], "url": url, "sha256": binary["checksum"], "manifest_sha256": manifest_digest}


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


def run_stage_version_probe(stage_current: Path, stage_workspace: Path) -> str:
    home = stage_workspace / "smoke-home"
    kimi_home = stage_workspace / "smoke-kimi-home"
    tmp = stage_workspace / "smoke-tmp"
    for directory in (home, kimi_home, tmp):
        directory.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        "KIMI_CODE_HOME": str(kimi_home),
        "KIMI_DISABLE_TELEMETRY": "1",
        "KIMI_CODE_BACKGROUND_KEEP_ALIVE_ON_EXIT": "0",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(tmp),
    }
    command = [str(stage_current / "bin" / KIMI_COMMAND), "--version"]
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
            fail("staged kimi binary is missing")
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


def software_source_contract() -> dict[str, Any]:
    return {
        "channel": "official-binary",
        "install_script_url": KIMI_INSTALL_SCRIPT_URL,
        "install_script_sha256": KIMI_INSTALL_SCRIPT_SHA256,
        "latest_url": KIMI_LATEST_URL,
        "manifest_url": KIMI_BINARY_MANIFEST_URL,
        "manifest_sha256": KIMI_BINARY_MANIFEST_SHA256,
        "github_release_url": KIMI_GITHUB_RELEASE_URL,
        "github_release_id": KIMI_GITHUB_RELEASE_ID,
        "git_tag": KIMI_GIT_TAG,
        "git_tag_object": KIMI_GIT_TAG_OBJECT,
        "git_commit": KIMI_GIT_COMMIT,
        "npm_package": KIMI_PACKAGE_NAME,
        "npm_integrity": KIMI_NPM_INTEGRITY,
        "npm_shasum": KIMI_NPM_SHASUM,
    }


def software_stamp(
    target: Path,
    *,
    platform_key: str,
    binary: dict[str, Any],
    entrypoint_digest: str,
    installed_tree_digest: str,
    version_probe_digest: str,
) -> dict[str, Any]:
    return {
        "schema_version": CURRENT_SOFTWARE_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(validate_target(target, create=False)),
        "version": KIMI_PACKAGE_VERSION,
        "command": KIMI_COMMAND,
        "entrypoint": "bin/kimi",
        "entrypoint_kind": "official-binary",
        "installed_tree": f"{SOFTWARE_DIR_NAME}/{SOFTWARE_CURRENT_NAME}",
        "manager": "cli-tools/nddev_kimicode.py",
        "platform": platform_key,
        "binary": {
            "filename": binary["filename"],
            "url": binary["url"],
            "sha256": binary["sha256"],
        },
        "source": software_source_contract(),
        "entrypoint_sha256": entrypoint_digest,
        "installed_tree_sha256": installed_tree_digest,
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
    return data, stat.S_IMODE(opened.st_mode)


def restore_software_entrypoint(target: Path, data: bytes | None, mode: int | None, *, remove_empty_parent: bool) -> None:
    path = software_entrypoint(target)
    if data is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        if remove_empty_parent:
            with contextlib.suppress(OSError):
                path.parent.rmdir()
        return
    atomic_write(path, data, target, mode=mode or 0o700)


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
    atomic_write(path, data, target, mode=mode or OWNER_FILE_MODE)


def copy_staged_binary(source: Path, destination: Path, target: Path) -> str:
    info = validate_software_file(source, "staged Kimi Code binary")
    ensure_real_parent(destination, target)
    temporary = destination.with_name(f".{destination.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    fd, _ = open_regular_readonly(source, "staged Kimi Code binary", max_bytes=SOFTWARE_MAX_BYTES)
    with os.fdopen(fd, "rb") as source_handle, temporary.open("xb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
    temporary.chmod(0o700 if stat.S_IMODE(info.st_mode) & 0o100 else OWNER_FILE_MODE)
    os.replace(temporary, destination)
    destination.chmod(0o700)
    return file_sha256(destination, label="Kimi Code entrypoint")


def install_or_update_software(target: Path, *, mode: str) -> dict[str, Any]:
    if mode not in {"install", "update", "migrate"}:
        fail("invalid software operation")
    preflight = software_status_payload(target)
    if preflight["current"]:
        return {
            "changed": False,
            "version": KIMI_PACKAGE_VERSION,
            "command": KIMI_COMMAND,
            "executable": str(software_entrypoint(target)),
            "installed_tree": str(software_current(target)),
            "target": canonical_target_readonly(target),
        }
    if mode == "install" and preflight["present"]:
        fail("install-cli found target-owned Kimi Code software presence; use update-cli or migrate-cli")
    if mode == "update":
        if not preflight["present"]:
            fail("update-cli requires existing target-owned Kimi Code software presence")
        if preflight["legacy"]:
            fail("update-cli refuses legacy Bun software; use migrate-cli")
    if mode == "migrate" and not preflight["legacy"]:
        fail("migrate-cli requires legacy target-owned Bun software state")

    with target_lock(target, create_parent=mode == "install") as transaction:
        validate_target(target, create=mode == "install", transaction=transaction)
        cleanup_drained = drain_cleanup_before_mutation(target)
        validate_safe_partial_software_presence(target)
        status = software_status_payload(target)
        if status["current"]:
            return {
                "changed": False,
                "version": KIMI_PACKAGE_VERSION,
                "command": KIMI_COMMAND,
                "executable": str(software_entrypoint(target)),
                "installed_tree": str(software_current(target)),
                "target": str(validate_target(target, create=False)),
                "cleanup_drained": cleanup_drained,
                **cleanup_pending_state(validate_target(target, create=False)),
            }
        if mode == "install" and status["present"]:
            fail("install-cli found target-owned Kimi Code software presence; use update-cli or migrate-cli")
        if mode == "update" and (not status["present"] or status["legacy"]):
            fail("update-cli requires non-legacy target-owned Kimi Code software presence")
        if mode == "migrate" and not status["legacy"]:
            fail("migrate-cli requires legacy target-owned Bun software state")

        parent = target.parent
        stage_root = cleanup_stage_directory(parent, f"{target.name}{SOFTWARE_STAGE_FRAGMENT}", "software stage")
        rollback_root = cleanup_stage_directory(parent, f"{target.name}{SOFTWARE_ROLLBACK_FRAGMENT}", "software rollback")
        postcommit_cleanup_pending = False
        try:
            stage_current = stage_root / SOFTWARE_CURRENT_NAME
            stage_current.mkdir(mode=OWNER_DIRECTORY_MODE)
            platform_key = detect_official_platform()
            binary = install_official_binary(stage_current, platform_key)
            version_probe_digest = run_stage_version_probe(stage_current, stage_root)
            installed_tree_digest = tree_sha256(stage_current)

            software_root_was_present = existing_path_label(software_root(target), SOFTWARE_DIR_NAME) is not None
            entrypoint_parent_was_present = existing_path_label(software_entrypoint(target).parent, "bin") is not None
            ensure_private_directory(software_root(target), "software root")
            current = software_current(target)
            rollback_current = rollback_root / SOFTWARE_CURRENT_NAME
            previous_entrypoint, previous_entrypoint_mode = snapshot_software_entrypoint(target)
            previous_stamp, previous_stamp_mode = snapshot_software_stamp(target)
            current_moved = False
            new_current_installed = False
            try:
                current_info = stat_existing(current, "current software tree")
                if current_info is not None:
                    if not stat.S_ISDIR(current_info.st_mode):
                        fail("current software tree must be a directory")
                    if not rename_no_replace(current, rollback_current, "software rollback current"):
                        fail("software rollback current already exists")
                    current_moved = True
                if not rename_no_replace(stage_current, current, "software current publication"):
                    fail("software current publication destination already exists")
                new_current_installed = True
                entrypoint_digest = copy_staged_binary(current / "bin" / KIMI_COMMAND, software_entrypoint(target), target)
                stamp = software_stamp(
                    target,
                    platform_key=platform_key,
                    binary=binary,
                    entrypoint_digest=entrypoint_digest,
                    installed_tree_digest=installed_tree_digest,
                    version_probe_digest=version_probe_digest,
                )
                atomic_write(software_stamp_path(target), canonical_json(stamp), target)
                verified = software_status_payload(target)
                if not verified["current"]:
                    fail(f"installed software failed status verification: {', '.join(verified['drift'])}")
            except BaseException:
                if new_current_installed:
                    failed_current = stage_root / "failed-current"
                    with contextlib.suppress(BaseException):
                        if not rename_no_replace(current, failed_current, "failed software current quarantine"):
                            fail("failed software current quarantine already exists")
                if current_moved:
                    if not rename_no_replace(rollback_current, current, "software rollback restore"):
                        finish_postcommit_cleanup(target, "software-failed", [stage_root, rollback_root])
                        fail("software rollback restore was blocked by replacement")
                restore_software_entrypoint(target, previous_entrypoint, previous_entrypoint_mode, remove_empty_parent=not entrypoint_parent_was_present)
                restore_software_stamp(target, previous_stamp, previous_stamp_mode)
                if not software_root_was_present:
                    with contextlib.suppress(OSError):
                        software_root(target).rmdir()
                finish_postcommit_cleanup(target, "software-failed", [stage_root, rollback_root])
                raise
            postcommit_cleanup_pending = finish_postcommit_cleanup(target, f"software-{mode}", [stage_root, rollback_root])
            return {
                "changed": True,
                "version": KIMI_PACKAGE_VERSION,
                "command": KIMI_COMMAND,
                "executable": str(software_entrypoint(target)),
                "installed_tree": str(software_current(target)),
                "target": str(validate_target(target, create=False)),
                "migrated_legacy": mode == "migrate",
                "cleanup_drained": cleanup_drained,
                "cleanup_pending": postcommit_cleanup_pending or cleanup_pending_state(validate_target(target, create=False))["cleanup_pending"],
            }
        except BaseException:
            raise


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
        for flag in FORBIDDEN_LAUNCH_SHORT_VALUE_FLAGS:
            if arg.startswith(flag) and arg != flag:
                fail(f"launch flag is managed by nddev-kimicode-app: {flag}")
        index += 1


def resolve_launch_workspace(raw_workspace: str | None) -> Path:
    if raw_workspace is None:
        try:
            workspace = Path.cwd()
        except OSError as exc:
            fail(f"launch workspace current directory is unavailable: {exc}")
        label = "launch workspace"
    else:
        workspace = Path(raw_workspace)
        if not workspace.is_absolute():
            fail("launch workspace must be an absolute path")
        label = "launch workspace"

    info = stat_existing(workspace, label)
    if info is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    if not hasattr(os, "O_NOFOLLOW"):
        fail("launch workspace validation requires O_NOFOLLOW support")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(workspace, flags)
    except OSError as exc:
        fail(f"{label} could not be opened safely: {exc}")
    try:
        opened = os.fstat(fd)
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            fail(f"{label} changed while opening")
        if not stat.S_ISDIR(opened.st_mode):
            fail(f"{label} must be a directory")
        try:
            resolved = workspace.resolve(strict=True)
        except OSError as exc:
            fail(f"{label} could not be resolved: {exc}")
        resolved_info = stat_existing(resolved, label)
        if resolved_info is None:
            fail(f"{label} is missing")
        if resolved_info.st_dev != opened.st_dev or resolved_info.st_ino != opened.st_ino:
            fail(f"{label} changed while resolving")
        return resolved
    finally:
        os.close(fd)


def ensure_launch_runtime_directories(canonical: Path) -> tuple[Path, Path, Path]:
    runtime = canonical / ".nddev-kimicode-runtime"
    home = runtime / "home"
    tmp = runtime / "tmp"
    ensure_private_directory(runtime, "runtime root")
    ensure_private_directory(home, "runtime home")
    ensure_private_directory(tmp, "runtime tmp")
    require_owner_private_directory(runtime, "runtime root")
    require_owner_private_directory(home, "runtime home")
    require_owner_private_directory(tmp, "runtime tmp")
    return runtime, home, tmp


def require_owner_directory_mode(path: Path, label: str, mode: int) -> None:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != mode:
        fail(f"{label} mode must be {mode:04o}")


def open_protected_directory(path: Path, label: str) -> ProtectedDirectory:
    flags = os.O_RDONLY
    if not hasattr(os, "O_NOFOLLOW"):
        fail("launch directory protection requires O_NOFOLLOW support")
    flags |= os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    expected = stat_existing(path, label)
    if expected is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(expected.st_mode):
        fail(f"{label} must be a directory")
    if not is_current_owner(expected):
        fail(f"{label} must be owned by the current user")
    original_mode = stat.S_IMODE(expected.st_mode)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} could not be opened safely: {exc}")
    try:
        opened = os.fstat(fd)
        if opened.st_dev != expected.st_dev or opened.st_ino != expected.st_ino:
            fail(f"{label} changed while opening")
        if not stat.S_ISDIR(opened.st_mode):
            fail(f"{label} must be a directory")
        if not is_current_owner(opened):
            fail(f"{label} must be owned by the current user")
        if original_mode != 0o500:
            os.fchmod(fd, 0o500)
        protected = os.fstat(fd)
        if stat.S_IMODE(protected.st_mode) != 0o500:
            fail(f"{label} mode must be 0500")
    except BaseException:
        os.close(fd)
        raise
    return ProtectedDirectory(path=path, fd=fd, original_mode=original_mode)


@contextlib.contextmanager
def protected_launch_path(target: Path):
    directories = (
        lock_path(target).parent,
        software_entrypoint(target).parent,
        software_root(target),
        software_current(target),
        software_current_binary(target).parent,
    )
    protected: list[ProtectedDirectory] = []
    for path in dict.fromkeys(directories):
        protected.append(open_protected_directory(path, f"launch protected directory {path}"))
    try:
        for directory in protected:
            info = os.fstat(directory.fd)
            if stat.S_IMODE(info.st_mode) != 0o500:
                fail(f"launch protected directory mode changed: {directory.path}")
        yield
    finally:
        for directory in reversed(protected):
            directory.restore()


def revalidate_launch_executable(
    target: Path,
    *,
    expected_digest: str | None = None,
    expected_stamp_digest: str | None = None,
) -> VerifiedLaunchExecutable:
    executable = software_entrypoint(target)
    label = "target-owned Kimi Code entrypoint"
    info = validate_software_file(executable, label)
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        fail(f"{label} mode must be 0700")
    fd, opened = open_regular_readonly(executable, label, max_bytes=SOFTWARE_MAX_BYTES)
    try:
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            fail(f"{label} changed while opening")
        if not stat.S_ISREG(opened.st_mode):
            fail(f"{label} must be a regular file")
        if opened.st_nlink != 1:
            fail(f"{label} must not be a hardlink")
        if not is_current_owner(opened):
            fail(f"{label} must be owned by the current user")
        if stat.S_IMODE(opened.st_mode) != 0o700:
            fail(f"{label} mode must be 0700")
        digest = file_sha256_from_fd(fd, label)
        after = os.fstat(fd)
        if after.st_dev != opened.st_dev or after.st_ino != opened.st_ino or after.st_size != opened.st_size:
            fail(f"{label} changed while hashing")

        if expected_digest is None or expected_stamp_digest is None:
            stamp = read_software_stamp(target)
            if stamp is None:
                fail("launch requires current target-owned Kimi Code binary: software stamp is missing")
            if software_is_legacy(stamp):
                fail("launch refuses legacy Bun software state; run migrate-cli first")
            platform_key = stamp.get("platform")
            expected_binary = KIMI_BINARY_PLATFORMS.get(str(platform_key))
            if expected_binary is None:
                fail("launch requires current target-owned Kimi Code binary: platform")
            expected_digest = expected_binary["checksum"]
            expected_stamp_digest = stamp.get("entrypoint_sha256")
        if digest != expected_digest:
            fail("target-owned Kimi Code entrypoint digest does not match pinned binary")
        if expected_stamp_digest != digest:
            fail("target-owned Kimi Code entrypoint digest does not match software stamp")
        return VerifiedLaunchExecutable(
            path=executable,
            fd=fd,
            digest=digest,
            st_dev=opened.st_dev,
            st_ino=opened.st_ino,
        )
    except BaseException:
        os.close(fd)
        raise


def prepare_launch_invocation_locked(target: Path, child_args: list[str], workspace: Path) -> LaunchInvocation:
    status = _status_payload(target)
    if not status["managed"]:
        fail("launch requires a managed target")
    if status["state"] == "legacy-managed":
        fail("launch refuses legacy managed setup state; run migrate first")
    if status["drift"]:
        fail(f"managed target has drift: {', '.join(status['drift'])}")
    software = _software_status_payload(target)
    if software["legacy"]:
        fail("launch refuses legacy Bun software state; run migrate-cli first")
    if not software["current"]:
        drift = software.get("drift") or ["target-owned Kimi Code binary is not installed"]
        fail(f"launch requires current target-owned Kimi Code binary: {', '.join(drift)}")
    canonical = validate_target(target, create=False)
    stamp = read_software_stamp(canonical)
    if stamp is None:
        fail("launch requires current target-owned Kimi Code binary: software stamp is missing")
    platform_key = stamp.get("platform")
    expected_binary = KIMI_BINARY_PLATFORMS.get(str(platform_key))
    if expected_binary is None:
        fail("launch requires current target-owned Kimi Code binary: platform")
    stamp_digest = stamp.get("entrypoint_sha256")
    if not isinstance(stamp_digest, str):
        fail("launch requires current target-owned Kimi Code binary: entrypoint stamp digest")
    runtime, home, tmp = ensure_launch_runtime_directories(canonical)
    require_owner_private_directory(runtime, "runtime root")
    require_owner_private_directory(home, "runtime home")
    require_owner_private_directory(tmp, "runtime tmp")
    child_env: dict[str, str] = {
        "HOME": str(home),
        "KIMI_CODE_HOME": str(canonical),
        "KIMI_DISABLE_TELEMETRY": "1",
        "KIMI_CODE_BACKGROUND_KEEP_ALIVE_ON_EXIT": "0",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(tmp),
    }
    return LaunchInvocation(
        target=canonical,
        workspace=workspace,
        command=[str(software_entrypoint(canonical)), *child_args],
        child_env=child_env,
        expected_entrypoint_digest=expected_binary["checksum"],
        stamp_entrypoint_digest=stamp_digest,
    )


def prepare_launch_invocation(
    target: Path,
    child_args: list[str],
    workspace: str | None = None,
) -> tuple[list[str], dict[str, str], Path]:
    reject_managed_launch_overrides(child_args)
    launch_workspace = resolve_launch_workspace(workspace)
    with target_lock(target):
        drain_cleanup_before_mutation(target)
        invocation = prepare_launch_invocation_locked(target, child_args, launch_workspace)
        return invocation.command, invocation.child_env, invocation.workspace


def launch(target: Path, child_args: list[str], workspace: str | None = None) -> int:
    reject_managed_launch_overrides(child_args)
    launch_workspace = resolve_launch_workspace(workspace)
    with target_lock(target):
        drain_cleanup_before_mutation(target)
        invocation = prepare_launch_invocation_locked(target, child_args, launch_workspace)
        with protected_launch_path(invocation.target):
            executable = revalidate_launch_executable(
                invocation.target,
                expected_digest=invocation.expected_entrypoint_digest,
                expected_stamp_digest=invocation.stamp_entrypoint_digest,
            )
            try:
                try:
                    completed = subprocess.run(
                        invocation.command,
                        env=invocation.child_env,
                        cwd=str(invocation.workspace),
                        check=False,
                    )
                except FileNotFoundError:
                    fail("target-owned kimi executable is missing")
                return int(completed.returncode)
            finally:
                executable.close()


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

    for name in ("install-cli", "update-cli", "migrate-cli"):
        command = subparsers.add_parser(name)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")

    for name in ("plan", "install"):
        command = subparsers.add_parser(name)
        command.add_argument("--setup", default=DEFAULT_CONTENT_SETUP)
        command.add_argument("--profile", default=DEFAULT_PROFILE)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")

    switch_profile = subparsers.add_parser("switch-profile")
    switch_profile.add_argument("--profile", required=True)
    switch_profile.add_argument("--target", required=True)
    switch_profile.add_argument("--json", action="store_true")

    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--setup", default=DEFAULT_CONTENT_SETUP)
    migrate.add_argument("--profile", default=DEFAULT_PROFILE)
    migrate.add_argument("--target", required=True)
    migrate.add_argument("--json", action="store_true")

    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True, type=int)
    restore.add_argument("--target", required=True)
    restore.add_argument("--json", action="store_true")

    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--target", required=True)
    launch_parser.add_argument("--workspace")
    launch_parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "list":
        emit(list_catalog(), as_json=args.json)
        return 0
    if args.command == "status":
        emit(status_payload(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "software-status":
        emit(software_status_payload(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "install-cli":
        emit(install_or_update_software(require_absolute_target(args.target), mode="install"), as_json=args.json)
        return 0
    if args.command == "update-cli":
        emit(install_or_update_software(require_absolute_target(args.target), mode="update"), as_json=args.json)
        return 0
    if args.command == "migrate-cli":
        emit(install_or_update_software(require_absolute_target(args.target), mode="migrate"), as_json=args.json)
        return 0
    if args.command == "plan":
        target = require_absolute_target(args.target)
        emit(plan_payload(target, load_content_setup(args.setup), load_profile(args.profile)), as_json=args.json)
        return 0
    if args.command == "install":
        target = require_absolute_target(args.target)
        emit(write_setup(target, load_content_setup(args.setup), load_profile(args.profile)), as_json=args.json)
        return 0
    if args.command == "switch-profile":
        target = require_absolute_target(args.target)
        current = read_stamp(target)
        if current is not None and not stamp_is_current(current):
            fail("managed target uses a legacy setup schema; use migrate")
        setup_id = DEFAULT_CONTENT_SETUP if current is None else str(current.get("content_setup_id", DEFAULT_CONTENT_SETUP))
        emit(write_setup(target, load_content_setup(setup_id), load_profile(args.profile), require_existing=True), as_json=args.json)
        return 0
    if args.command == "migrate":
        target = require_absolute_target(args.target)
        emit(
            write_setup(
                target,
                load_content_setup(args.setup),
                load_profile(args.profile),
                require_existing=True,
                migrate_legacy=True,
            ),
            as_json=args.json,
        )
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
        return launch(require_absolute_target(args.target), child_args, workspace=args.workspace)
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
