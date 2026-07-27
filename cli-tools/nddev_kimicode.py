#!/usr/bin/env python3
"""Transactional setup manager for an explicit Kimi Code CLI target."""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
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
FORBIDDEN_LAUNCH_FLAGS = {
    "--auto",
    "--auto-approve",
    "--continue",
    "--plan",
    "--resume",
    "--session",
    "--yolo",
    "--yes",
    "-C",
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
    "--skills-dir",
    "-m",
}
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
    command: list[str]
    child_env: dict[str, str]
    expected_entrypoint_digest: str
    stamp_entrypoint_digest: str


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


def ensure_external_lock_root() -> Path:
    root = fixed_system_temp_root() / EXTERNAL_LOCK_ROOT_NAME
    info = stat_existing(root, "external lifecycle lock root")
    if info is None:
        try:
            root.mkdir(mode=OWNER_DIRECTORY_MODE)
        except FileExistsError:
            pass
        else:
            root.chmod(OWNER_DIRECTORY_MODE)
        info = stat_existing(root, "external lifecycle lock root")
    if info is None:
        fail("external lifecycle lock root is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail("external lifecycle lock root must be a real directory")
    if not is_current_owner(info):
        fail("external lifecycle lock root must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("external lifecycle lock root mode must be 0700")
    return root


def bootstrap_lock_path(target: Path, canonical_target: str | None = None) -> Path:
    canonical = canonical_target if canonical_target is not None else lock_canonical_target(target)
    digest = sha256_bytes(f"{EXTERNAL_LOCK_NAMESPACE}\0{canonical}".encode("utf-8"))
    return ensure_external_lock_root() / f"{digest}.{EXTERNAL_LOCK_SUFFIX}"


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


def open_lock_file(path: Path, label: str) -> int:
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
        try:
            fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        except FileExistsError:
            try:
                fd = os.open(path, flags, OWNER_FILE_MODE)
            except OSError as exc:
                fail(f"{label} could not be opened safely: {exc}")
        except OSError as exc:
            fail(f"{label} could not be opened safely: {exc}")
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
        return
    if payload.get("product_name") != PRODUCT_NAME or payload.get("kind") != kind:
        fail(f"{label} is bound to another lifecycle owner")
    if payload.get("canonical_target") != canonical_target:
        fail(f"{label} is bound to a different canonical target")
    if payload.get("path") != str(path):
        fail(f"{label} is bound to a different lock path")


def acquire_lock_file(path: Path, label: str, *, canonical_target: str, kind: str) -> int:
    fd = open_lock_file(path, label)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
        payload = canonical_json(lock_payload(kind, canonical_target, path))
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
        os.fsync(fd)
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
    bootstrap_path = bootstrap_lock_path(target, canonical_target)
    bootstrap_fd: int | None = None
    internal_path: Path | None = None
    internal_fd: int | None = None
    internal_parent: ProtectedDirectory | None = None
    try:
        bootstrap_fd = acquire_lock_file(
            bootstrap_path,
            "external bootstrap lifecycle lock",
            canonical_target=canonical_target,
            kind="external-bootstrap",
        )
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
            )
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
                    if bootstrap_fd is not None:
                        releasing_bootstrap_fd = bootstrap_fd
                        bootstrap_fd = None
                        release_lock_file(releasing_bootstrap_fd, bootstrap_path, remove_file=False)
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
        if bootstrap_fd is not None:
            releasing_bootstrap_fd = bootstrap_fd
            bootstrap_fd = None
            release_lock_file(releasing_bootstrap_fd, bootstrap_path, remove_file=False)
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
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
        path.chmod(mode)
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
    canonical = validate_target(target, create=False)
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
        }
    descriptor = stamp_descriptor(stamp)
    drift = drift_for_stamp(target, stamp)
    current = stamp_is_current(stamp)
    software = software_status_payload(canonical)
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
    }


def stamp_managed_paths(stamp: dict[str, Any] | None) -> tuple[str, ...]:
    if stamp is None:
        return ()
    managed = stamp.get("managed_files")
    if not isinstance(managed, dict):
        return ()
    return tuple(str(path) for path in managed)


def snapshot_files(target: Path, extra_paths: tuple[str, ...] = ()) -> dict[str, bytes | None]:
    snapshot: dict[str, bytes | None] = {}
    for relative in (*content_managed_paths(), *extra_paths, STAMP_NAME):
        snapshot[relative] = read_existing_file(safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative)
    return snapshot


def restore_snapshot(target: Path, snapshot: dict[str, bytes | None]) -> None:
    for relative, data in snapshot.items():
        path = safe_target_path(target, relative)
        if data is None:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            continue
        atomic_write(path, data, target)
    prune_empty_managed_dirs(target, tuple(snapshot))


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
    atomic_write(slot_dir / BACKUP_NAME, canonical_json(envelope), slot_dir)
    return slot


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
        if current is not None:
            descriptor = stamp_descriptor(current)
            if (
                descriptor["legacy"]
                or descriptor["content_setup_id"] != setup["id"]
                or descriptor["permission_profile_id"] != profile_data["id"]
            ):
                backup_slot = create_backup(target, current)
        stale_paths = ()
        if current is not None:
            stale_paths = tuple(path for path in stamp_managed_paths(current) if path not in files)
        snapshot = snapshot_files(target, stale_paths)
        try:
            for relative in stale_paths:
                path = safe_target_path(target, relative)
                if relative in MERGED_MARKER_PATHS:
                    remove_managed_block_from_target(target, relative)
                else:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
            for relative, data in files.items():
                atomic_write(safe_target_path(target, relative), data, target)
            atomic_write(stamp_path(target), canonical_json(desired_stamp), target)
            prune_empty_managed_dirs(target, stale_paths)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        return {
            "content_setup_id": setup["id"],
            "permission_profile_id": profile_data["id"],
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
        snapshot = snapshot_files(target, tuple(files))
        try:
            for relative in (*files.keys(),):
                encoded = files.get(relative)
                path = safe_target_path(target, relative)
                if encoded is None:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
                    continue
                if not isinstance(encoded, str):
                    fail("backup file payload is invalid")
                try:
                    decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
                except (binascii.Error, ValueError):
                    fail("backup file payload is invalid base64")
                atomic_write(path, decoded, target)
            prune_empty_managed_dirs(target, tuple(files))
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        restored_stamp = read_stamp(target)
        descriptor = stamp_descriptor(restored_stamp)
        return {
            "content_setup_id": descriptor["content_setup_id"],
            "permission_profile_id": descriptor["permission_profile_id"],
            "legacy_setup_id": descriptor["legacy_setup_id"],
            "backup_slot": slot,
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
        stamp = read_stamp(target)
        if stamp is None:
            return {"removed": None, "target": str(validate_target(target, create=False))}
        drift = drift_for_stamp(target, stamp)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        descriptor = stamp_descriptor(stamp)
        remove_paths = tuple(dict.fromkeys((*content_managed_paths(), *stamp_managed_paths(stamp))))
        snapshot = snapshot_files(target, remove_paths)
        try:
            for relative in remove_paths:
                path = safe_target_path(target, relative)
                if relative in MERGED_MARKER_PATHS:
                    remove_managed_block_from_target(target, relative)
                else:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
            with contextlib.suppress(FileNotFoundError):
                stamp_path(target).unlink()
            prune_empty_managed_dirs(target, remove_paths)
        except BaseException:
            restore_snapshot(target, snapshot)
            raise
        return {"removed": descriptor, "target": str(validate_target(target, create=False))}


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
        "target": str(validate_target(target, create=False)),
        "current_content_setup_id": status["content_setup_id"],
        "current_permission_profile_id": status["permission_profile_id"],
        "legacy_setup_id": status["legacy_setup_id"],
        "drift": status["drift"],
        "backup_required": backup_required,
        "mutates": False,
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
            }
        if mode == "install" and status["present"]:
            fail("install-cli found target-owned Kimi Code software presence; use update-cli or migrate-cli")
        if mode == "update" and (not status["present"] or status["legacy"]):
            fail("update-cli requires non-legacy target-owned Kimi Code software presence")
        if mode == "migrate" and not status["legacy"]:
            fail("migrate-cli requires legacy target-owned Bun software state")

        parent = target.parent
        with tempfile.TemporaryDirectory(prefix=f".{target.name}{SOFTWARE_STAGE_FRAGMENT}.", dir=str(parent)) as stage_raw, tempfile.TemporaryDirectory(
            prefix=f".{target.name}.nddev-kimicode-software-rollback.", dir=str(parent)
        ) as rollback_raw:
            stage_root = Path(stage_raw)
            rollback_root = Path(rollback_raw)
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
                    current.rename(rollback_current)
                    current_moved = True
                stage_current.rename(current)
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
                    shutil.rmtree(current, ignore_errors=True)
                if current_moved:
                    rollback_current.rename(current)
                restore_software_entrypoint(target, previous_entrypoint, previous_entrypoint_mode, remove_empty_parent=not entrypoint_parent_was_present)
                restore_software_stamp(target, previous_stamp, previous_stamp_mode)
                if not software_root_was_present:
                    with contextlib.suppress(OSError):
                        software_root(target).rmdir()
                raise
            return {
                "changed": True,
                "version": KIMI_PACKAGE_VERSION,
                "command": KIMI_COMMAND,
                "executable": str(software_entrypoint(target)),
                "installed_tree": str(software_current(target)),
                "target": str(validate_target(target, create=False)),
                "migrated_legacy": mode == "migrate",
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


def prepare_launch_invocation_locked(target: Path, child_args: list[str]) -> LaunchInvocation:
    status = status_payload(target)
    if not status["managed"]:
        fail("launch requires a managed target")
    if status["state"] == "legacy-managed":
        fail("launch refuses legacy managed setup state; run migrate first")
    if status["drift"]:
        fail(f"managed target has drift: {', '.join(status['drift'])}")
    software = software_status_payload(target)
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
        command=[str(software_entrypoint(canonical)), *child_args],
        child_env=child_env,
        expected_entrypoint_digest=expected_binary["checksum"],
        stamp_entrypoint_digest=stamp_digest,
    )


def prepare_launch_invocation(target: Path, child_args: list[str]) -> tuple[list[str], dict[str, str]]:
    reject_managed_launch_overrides(child_args)
    with target_lock(target):
        invocation = prepare_launch_invocation_locked(target, child_args)
        return invocation.command, invocation.child_env


def launch(target: Path, child_args: list[str]) -> int:
    reject_managed_launch_overrides(child_args)
    with target_lock(target):
        invocation = prepare_launch_invocation_locked(target, child_args)
        with protected_launch_path(invocation.target):
            executable = revalidate_launch_executable(
                invocation.target,
                expected_digest=invocation.expected_entrypoint_digest,
                expected_stamp_digest=invocation.stamp_entrypoint_digest,
            )
            try:
                try:
                    completed = subprocess.run(invocation.command, env=invocation.child_env, check=False)
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
