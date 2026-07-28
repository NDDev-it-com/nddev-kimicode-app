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
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
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
BACKUP_SCHEMA = 2
CLEANUP_DIR_NAME = ".nddev-kimicode-cleanup"
CLEANUP_JOURNAL_NAME = "journal.json"
CLEANUP_INTENT_NAME = "intent.json"
CLEANUP_SCHEMA = 1
CLEANUP_INTENT_SCHEMA = 1
CLEANUP_MAX_ENTRIES = 8
LOCK_DIR_NAME = ".nddev-kimicode-lock"
LOCK_NAME = "lifecycle.lock"
EXTERNAL_LOCK_ROOT_NAME = (
    f"{PRODUCT_NAME}.{os.getuid() if hasattr(os, 'getuid') else 'nouid'}.locks"
)
EXTERNAL_LOCK_NAMESPACE = f"{PRODUCT_NAME}:external-bootstrap:v1"
EXTERNAL_LOCK_SUFFIX = "external.lock"
EXTERNAL_PRODUCT_ANCHOR_NAME = "global.lock"
EXTERNAL_PRODUCT_ANCHOR_CANONICAL_TARGET = f"{PRODUCT_NAME}:product-anchor:v1"
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
CLEANUP_JOURNAL_MAX_BYTES = METADATA_MAX_BYTES
CLEANUP_INTENT_MAX_BYTES = METADATA_MAX_BYTES + 16 * 1024
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
KIMI_GITHUB_RELEASE_API_URL = (
    "https://api.github.com/repos/MoonshotAI/kimi-code/releases/tags/"
    "%40moonshot-ai%2Fkimi-code%400.29.2"
)
KIMI_GITHUB_RELEASE_ID = 360239506
KIMI_GIT_TAG = "@moonshot-ai/kimi-code@0.29.2"
KIMI_GIT_TAG_OBJECT = "57503c7c4d854f2c66ea32e10cba28b2c5715e9c"
KIMI_GIT_COMMIT = "8a45f10eddbb35c317047e82e567cdb59a220b4f"
KIMI_GITHUB_RELEASE_ASSETS = {
    "kimi-code-darwin-arm64.zip": {
        "kind": "platform-zip",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-darwin-arm64.zip",
        "size_bytes": 50866147,
        "sha256": "33fe10b7059ec39eecad8fc36b25059abc80c3d64d6d3975aa15c8fe183f5784",
    },
    "kimi-code-darwin-arm64.zip.sha256": {
        "kind": "sha256-sidecar",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-darwin-arm64.zip.sha256",
        "size_bytes": 93,
        "sha256": "073f840e4bc81de3c12c638147cf0265f03e53bd11b63d4b9d708fe5a4b23192",
    },
    "kimi-code-darwin-x64.zip": {
        "kind": "platform-zip",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-darwin-x64.zip",
        "size_bytes": 51878729,
        "sha256": "5e206bfe7251aa391b6700a53f6431dd2d9bf89e2693ab6eb440e20a332a72df",
    },
    "kimi-code-darwin-x64.zip.sha256": {
        "kind": "sha256-sidecar",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-darwin-x64.zip.sha256",
        "size_bytes": 91,
        "sha256": "e8864e2529e91883de1ec3deb859e7b998634d7dcd0c54eb8d806372e8e7a6c1",
    },
    "kimi-code-linux-arm64.zip": {
        "kind": "platform-zip",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-linux-arm64.zip",
        "size_bytes": 54391806,
        "sha256": "674622a6a274b7b84f2127a55c66b3744c0286fc37ae1ef20cf9c411042e63a8",
    },
    "kimi-code-linux-arm64.zip.sha256": {
        "kind": "sha256-sidecar",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-linux-arm64.zip.sha256",
        "size_bytes": 92,
        "sha256": "6f05e3e7be7b5a16c7c739307afdb70dc23c00f72648f75e328217826591a16e",
    },
    "kimi-code-linux-x64.zip": {
        "kind": "platform-zip",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-linux-x64.zip",
        "size_bytes": 54418242,
        "sha256": "20c184d8b0c0f8d7245a58eaf9c130be05878618e17e221eeefd352dcc011147",
    },
    "kimi-code-linux-x64.zip.sha256": {
        "kind": "sha256-sidecar",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-linux-x64.zip.sha256",
        "size_bytes": 90,
        "sha256": "d77ca236c83e3d4d8af1d6fe5c11876a6c1c4a8257b50754a053d9d5f1e0e59e",
    },
    "kimi-code-win32-arm64.zip": {
        "kind": "platform-zip",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-win32-arm64.zip",
        "size_bytes": 42022575,
        "sha256": "379be73d6b7fb9fbb582c3187e90251efddaf5a18caf16c77dfc5158c39b1a5c",
    },
    "kimi-code-win32-arm64.zip.sha256": {
        "kind": "sha256-sidecar",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-win32-arm64.zip.sha256",
        "size_bytes": 92,
        "sha256": "2bd34e8feabf9c75cfb6abf75f52faca90a5fb34030ab77ce3de326528bd90cd",
    },
    "kimi-code-win32-x64.zip": {
        "kind": "platform-zip",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-win32-x64.zip",
        "size_bytes": 45840378,
        "sha256": "0abd43b7428f493b2736ac3a4c8fc315e5fc4aa22dfb26dd764e1348e5b80718",
    },
    "kimi-code-win32-x64.zip.sha256": {
        "kind": "sha256-sidecar",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/kimi-code-win32-x64.zip.sha256",
        "size_bytes": 90,
        "sha256": "1b9276869597b39f42184dac95999961c8d2a7fa08ecb59ebbe6b2d1b17775b0",
    },
    "manifest.json": {
        "kind": "manifest",
        "url": "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai/kimi-code%400.29.2/manifest.json",
        "size_bytes": 1041,
        "sha256": "650a07b7b10f74eec20fb12b452f80b5319e6250563abf60acee97fc3aac9e12",
    },
}
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
KIMI_OBSERVED_BINARY_PLATFORMS = {
    "darwin-arm64": {
        "filename": "kimi-code-darwin-arm64",
        "url": f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/kimi-code-darwin-arm64",
        "size_bytes": 160002496,
        "sha256": "25dc8b14f8bb5ef98470577265b1e9c95892c168f34e9639c5f63b48d4ece6fb",
        "supported_product_hosts": ["macos-arm64"],
    },
    "darwin-x64": {
        "filename": "kimi-code-darwin-x64",
        "url": f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/kimi-code-darwin-x64",
        "size_bytes": 162344320,
        "sha256": "fe59f14cab74971768377e586bf3be30c1ca04079c058d4b492827ca4dfd6b16",
        "supported_product_hosts": ["macos-x64"],
    },
    "linux-arm64": {
        "filename": "kimi-code-linux-arm64",
        "url": f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/kimi-code-linux-arm64",
        "size_bytes": 160500864,
        "sha256": "5fb64e74eeec0b3900732cfbc3679cc505beb51aa323f486154fd79b0e20b26a",
        "supported_product_hosts": ["ubuntu-glibc-arm64"],
    },
    "linux-x64": {
        "filename": "kimi-code-linux-x64",
        "url": f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/kimi-code-linux-x64",
        "size_bytes": 162860224,
        "sha256": "f9977d259ed36019793cadf04b1f0343f12aaebfa76f90fa26cd3b02be671231",
        "supported_product_hosts": ["ubuntu-glibc-x64"],
    },
    "win32-arm64": {
        "filename": "kimi-code-win32-arm64.exe",
        "url": f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/kimi-code-win32-arm64.exe",
        "size_bytes": 120212992,
        "sha256": "26cd0ab7267aab92530a9584778deb5fa2c37c44131c8b2d8ec653e474f288c8",
        "supported_product_hosts": [],
    },
    "win32-x64": {
        "filename": "kimi-code-win32-x64.exe",
        "url": f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/kimi-code-win32-x64.exe",
        "size_bytes": 131644416,
        "sha256": "32ea71e814b53958afaa37f15982647e6c832cb70922941ca35a57d01f64e12f",
        "supported_product_hosts": [],
    },
}
KIMI_OBSERVED_VENDOR_PLATFORMS = tuple(KIMI_OBSERVED_BINARY_PLATFORMS)
KIMI_INSTALL_POWERSHELL_URL = "https://code.kimi.com/kimi-code/install.ps1"
KIMI_INSTALL_POWERSHELL_SHA256 = "28a0473a7c56d41eae52cb4dbd3232f87a9133dd7af416a6a04dfbf7856fa9fc"
KIMI_INSTALL_POWERSHELL_SIZE_BYTES = 15891
KIMI_SUPPORTED_PRODUCT_HOSTS = (
    "macos-arm64",
    "macos-x64",
    "ubuntu-glibc-arm64",
    "ubuntu-glibc-x64",
)
KIMI_UNSUPPORTED_HOST_CATEGORIES = (
    "windows",
    "non-ubuntu-linux",
    "linux-musl",
    "unsupported-architecture",
)
KIMI_PRODUCT_HOST_TO_VENDOR_PLATFORM = {
    "macos-arm64": "darwin-arm64",
    "macos-x64": "darwin-x64",
    "ubuntu-glibc-arm64": "linux-arm64",
    "ubuntu-glibc-x64": "linux-x64",
}
KIMI_VENDOR_PLATFORM_TO_PRODUCT_HOST = {
    vendor_platform: product_host
    for product_host, vendor_platform in KIMI_PRODUCT_HOST_TO_VENDOR_PLATFORM.items()
}
KIMI_UBUNTU_GLIBC_VERSION_FLOOR: str | None = None
KIMI_VENDOR_DISTRIBUTION_OBSERVATIONS = {
    "github_release_assets": {
        "source_family": "github-release-assets",
        "release_url": KIMI_GITHUB_RELEASE_URL,
        "api_url": KIMI_GITHUB_RELEASE_API_URL,
        "release_id": KIMI_GITHUB_RELEASE_ID,
        "tag": KIMI_GIT_TAG,
        "asset_count": 13,
        "platform_zip_count": 6,
        "sha256_sidecar_count": 6,
        "manifest_count": 1,
        "assets": KIMI_GITHUB_RELEASE_ASSETS,
    },
    "code_kimi_binary_manifest": {
        "source_family": "code.kimi.com-binary-manifest",
        "manifest_url": KIMI_BINARY_MANIFEST_URL,
        "manifest_sha256": KIMI_BINARY_MANIFEST_SHA256,
        "manifest_size_bytes": 929,
        "version": KIMI_PACKAGE_VERSION,
        "tag": KIMI_GIT_TAG,
        "platform_count": 6,
        "observed_vendor_platforms": list(KIMI_OBSERVED_VENDOR_PLATFORMS),
        "platforms": KIMI_OBSERVED_BINARY_PLATFORMS,
    },
    "product_selections": {
        "supported_hosts": list(KIMI_SUPPORTED_PRODUCT_HOSTS),
        "host_to_vendor_platform": KIMI_PRODUCT_HOST_TO_VENDOR_PLATFORM,
        "unsupported_host_categories": list(KIMI_UNSUPPORTED_HOST_CATEGORIES),
        "ubuntu_glibc_version_floor": KIMI_UBUNTU_GLIBC_VERSION_FLOOR,
        "ubuntu_glibc_version_floor_source": "no-official-floor",
    },
}
LINUX_OS_RELEASE_PATHS = (Path("/etc/os-release"), Path("/usr/lib/os-release"))
LINUX_MUSL_MARKER_PATHS = (
    Path("/lib/libc.musl-x86_64.so.1"),
    Path("/lib/libc.musl-aarch64.so.1"),
)

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


class KimicodeArgumentError(KimicodeSetupError):
    """Safe JSON-facing parser failure."""


class KimicodeArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, json_errors: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.json_errors = json_errors

    def error(self, message: str) -> NoReturn:
        if self.json_errors:
            raise KimicodeArgumentError(message)
        super().error(message)


@dataclass
class DirectoryTransaction:
    created: list[Path]
    directory_signatures: dict[Path, DirectoryObjectSignature | None] = field(default_factory=dict)

    def remember_directory(self, path: Path, label: str) -> None:
        if path not in self.directory_signatures:
            self.directory_signatures[path] = directory_object_signature(path, label)

    def cleanup_once(self) -> None:
        for path in reversed(self.created):
            if path_exists_no_follow(path):
                durable_rmdir(path)
        for path, signature in sorted(
            self.directory_signatures.items(),
            key=lambda item: len(item[0].parts),
            reverse=True,
        ):
            restore_directory_object_signature(path, signature, str(path))

    def verify_clean(self) -> None:
        for path in self.created:
            if path_exists_no_follow(path):
                fail(f"created directory rollback residue remains: {path}")
        for path, signature in self.directory_signatures.items():
            verify_directory_object_signature(path, signature, str(path))

    def cleanup(self) -> None:
        restore_with_retries(
            self.cleanup_once,
            self.verify_clean,
            "created directory cleanup",
        )


@dataclass(frozen=True)
class FileSnapshot:
    data: bytes | None
    mode: int | None


@dataclass(frozen=True)
class FileObjectSignature:
    st_dev: int
    st_ino: int
    mode: int
    mtime_ns: int
    size: int
    sha256: str


@dataclass(frozen=True)
class DirectoryObjectSignature:
    st_dev: int
    st_ino: int
    st_size: int
    mode: int
    atime_ns: int
    mtime_ns: int


@dataclass(frozen=True)
class TreeEntry:
    path: str
    kind: str
    size: int
    mode: int
    st_dev: int
    st_ino: int
    mtime_ns: int
    data: bytes | None = None


@dataclass(frozen=True)
class TreeSnapshot:
    entries: dict[str, TreeEntry] | None


@dataclass(frozen=True)
class SoftwareStateSnapshot:
    software_tree: TreeSnapshot
    entrypoint: FileSnapshot
    stamp: FileSnapshot
    entrypoint_parent_present: bool
    entrypoint_parent_mode: int | None
    entrypoint_parent_signature: DirectoryObjectSignature | None


@dataclass(frozen=True)
class PendingBackup:
    slot: int
    envelope: dict[str, Any]


@dataclass(frozen=True)
class BackupCommitResult:
    slot: int
    cleanup_sources: tuple[tuple[Path | None, str, int, int], ...] = ()
    cleanup_pending: bool = False


@dataclass(frozen=True)
class CleanupPromotion:
    entries: list[dict[str, Any]]
    journal: dict[str, Any]
    serialized_journal: bytes
    intent: dict[str, Any]
    serialized_intent: bytes
    moved: list[tuple[Path, Path]]
    parent_signature: DirectoryObjectSignature | None
    source_parent_signatures: dict[Path, DirectoryObjectSignature | None]


@dataclass(frozen=True)
class CleanupJournalPublishResult:
    published: bool
    cleanup_pending: bool = False


@dataclass(frozen=True)
class CleanupSourceAdmission:
    operation_kind: str
    anchor: str
    relative: str
    parent_anchor: str
    parent_relative: str
    parent_st_dev: int
    parent_st_ino: int


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


@dataclass(frozen=True)
class LinuxDistribution:
    distro_id: str
    id_like: tuple[str, ...]
    pretty_name: str
    source: str


@dataclass(frozen=True)
class DetectedHost:
    product_host_id: str
    vendor_platform_key: str
    os_name: str
    arch: str
    linux_distribution: LinuxDistribution | None


@dataclass
class FileObjectChange:
    path: Path
    rollback_path: Path | None
    staged_path: Path | None
    original_present: bool
    original_signature: FileObjectSignature | None
    original_checked: bool
    label: str
    max_bytes: int
    applied: bool = False


@dataclass
class TreeObjectChange:
    path: Path
    rollback_path: Path | None
    staged_path: Path | None
    original_present: bool
    label: str
    max_file_bytes: int
    max_paths: int
    applied: bool = False


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
    if ".." in target.parts[1:]:
        fail("target path must be lexical and must not contain '..'")
    return target


def lexical_target_identity(target: Path) -> str:
    if not target.is_absolute():
        fail("target must be an absolute path")
    if target.name in ("", ".", "..") or ".." in target.parts[1:]:
        fail("target path must be lexical and must name a directory")
    return str(target)


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
        transaction.remember_directory(current, f"{label} existing directory")
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
            local_transaction.remember_directory(parent, "target parent")
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
    return lexical_target_identity(target)


def canonicalize_target_under_product_lock(target: Path) -> Path:
    lexical_target_identity(target)
    info = stat_existing(target, "target")
    if info is not None and not stat.S_ISDIR(info.st_mode):
        fail("target must be a real directory")
    canonical = target.resolve(strict=False)
    lexical_target_identity(canonical)
    reject_symlink_ancestors(canonical)
    return canonical


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
    system_root = fixed_system_temp_root()
    system_root_signature = directory_object_signature(system_root, "system bootstrap root")
    root = system_root / EXTERNAL_LOCK_ROOT_NAME
    info = stat_existing(root, "external lifecycle lock root")
    if info is None:
        created = False
        try:
            root.mkdir(mode=OWNER_DIRECTORY_MODE)
            created = True
            root.chmod(OWNER_DIRECTORY_MODE)
            fsync_directory(system_root)
        except FileExistsError:
            pass
        except BaseException:
            if created and path_exists_no_follow(root):
                durable_rmdir(root)
            restore_directory_object_signature(
                system_root,
                system_root_signature,
                "system bootstrap root",
            )
            raise
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


def external_lock_root_path(system_root: Path | None = None) -> Path:
    root = fixed_system_temp_root() if system_root is None else system_root
    return root / EXTERNAL_LOCK_ROOT_NAME


def external_product_anchor_path(external_lock_root: Path) -> Path:
    return external_lock_root / EXTERNAL_PRODUCT_ANCHOR_NAME


def external_bootstrap_lock_path(external_lock_root: Path, canonical_target: str) -> Path:
    digest = sha256_bytes(f"{EXTERNAL_LOCK_NAMESPACE}\0{canonical_target}".encode("utf-8"))
    return external_lock_root / f"{digest}.{EXTERNAL_LOCK_SUFFIX}"


def bootstrap_lock_path(
    target: Path,
    canonical_target: str | None = None,
    *,
    external_lock_root: Path | None = None,
) -> Path:
    canonical = canonical_target if canonical_target is not None else lock_canonical_target(target)
    root = ensure_external_lock_root() if external_lock_root is None else external_lock_root
    return external_bootstrap_lock_path(root, canonical)


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


def validate_existing_external_lock_root(path: Path) -> Path | None:
    info = stat_existing(path, "external lifecycle lock root")
    if info is None:
        return None
    if not stat.S_ISDIR(info.st_mode):
        fail("external lifecycle lock root must be a real directory")
    if not is_current_owner(info):
        fail("external lifecycle lock root must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("external lifecycle lock root mode must be 0700")
    return path


def write_lock_stage_file(path: Path, payload: bytes, label: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, OWNER_FILE_MODE)
    try:
        try:
            write_all(fd, payload)
            os.fchmod(fd, OWNER_FILE_MODE)
            os.fsync(fd)
        finally:
            os.close(fd)
    except BaseException:
        restore_with_retries(
            lambda: durable_unlink(path),
            lambda: verify_file_snapshot(
                path,
                FileSnapshot(data=None, mode=None),
                label,
                max_bytes=METADATA_MAX_BYTES,
            ),
            label,
        )
        raise
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} staged file is missing")
    validate_lock_info(info, label)
    if read_existing_file(path, max_bytes=METADATA_MAX_BYTES, label=label) != payload:
        fail(f"{label} staged binding postcondition failed")


def cleanup_lock_stage_file(path: Path, label: str) -> None:
    restore_with_retries(
        lambda: durable_unlink(path),
        lambda: verify_file_snapshot(
            path,
            FileSnapshot(data=None, mode=None),
            label,
            max_bytes=METADATA_MAX_BYTES,
        ),
        label,
    )


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


def publish_missing_lock_file(
    path: Path,
    label: str,
    *,
    canonical_target: str,
    kind: str,
) -> None:
    parent = path.parent
    parent_signature = directory_object_signature(parent, f"{label} parent")
    if parent_signature is None:
        fail(f"{label} parent is missing")
    payload = canonical_json(lock_payload(kind, canonical_target, path))
    stage = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    published = False
    try:
        write_lock_stage_file(stage, payload, f"{label} staged binding")
        if not rename_no_replace(stage, path, label):
            cleanup_lock_stage_file(stage, f"{label} staged binding")
            return
        published = True
        fsync_directory(parent)
    except BaseException:
        if path_exists_no_follow(stage):
            with contextlib.suppress(BaseException):
                cleanup_lock_stage_file(stage, f"{label} staged binding")
        if not published:
            restore_with_retries(
                lambda: restore_directory_object_signature(
                    parent,
                    parent_signature,
                    f"{label} parent",
                ),
                lambda: verify_directory_object_signature(
                    parent,
                    parent_signature,
                    f"{label} parent",
                ),
                f"{label} parent",
            )
        raise


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
    }


def read_lock_payload(fd: int, label: str) -> dict[str, Any] | None:
    data = read_lock_bytes(fd, label)
    if not data.strip():
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"{label} binding is malformed")
    if not isinstance(value, dict):
        fail(f"{label} binding is malformed")
    return value


def read_lock_bytes(fd: int, label: str) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, METADATA_MAX_BYTES + 1)
    if len(data) > METADATA_MAX_BYTES:
        fail(f"{label} metadata is too large")
    return data


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
    if set(payload) != {"schema_version", "product_name", "kind", "canonical_target", "path"}:
        fail(f"{label} binding is malformed")
    if payload.get("schema_version") != 3:
        fail(f"{label} binding schema is unsupported")
    if payload.get("product_name") != PRODUCT_NAME or payload.get("kind") != kind:
        fail(f"{label} is bound to another lifecycle owner")
    if payload.get("canonical_target") != canonical_target:
        fail(f"{label} is bound to a different canonical target")
    if payload.get("path") != str(path):
        fail(f"{label} is bound to a different lock path")


def acquire_lock_file(
    path: Path,
    label: str,
    *,
    canonical_target: str,
    kind: str,
    lock_mode: int = fcntl.LOCK_EX,
    create: bool = True,
) -> int:
    if create and stat_existing(path, label) is None:
        publish_missing_lock_file(
            path,
            label,
            canonical_target=canonical_target,
            kind=kind,
        )
    fd = open_lock_file(path, label, create=False)
    if fd is None:
        fail(f"{label} is missing")
    try:
        fcntl.flock(fd, lock_mode | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in {errno.EACCES, errno.EAGAIN}:
            fail(f"target is locked: {path}")
        fail(f"{label} could not be locked: {exc}")
    try:
        verify_lock_fd_path(fd, path, label)
        current_payload = read_lock_payload(fd, label)
        validate_lock_binding(
            current_payload,
            kind=kind,
            canonical_target=canonical_target,
            path=path,
            label=label,
        )
    except BaseException:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        raise
    return fd


def acquire_existing_lock_file(
    path: Path,
    label: str,
    *,
    canonical_target: str,
    kind: str,
    lock_mode: int = fcntl.LOCK_EX,
) -> int | None:
    if stat_existing(path, label) is None:
        return None
    return acquire_lock_file(
        path,
        label,
        canonical_target=canonical_target,
        kind=kind,
        lock_mode=lock_mode,
        create=False,
    )


def release_lock_file(
    fd: int, path: Path, *, remove_file: bool = False, remove_empty_parent: bool = False
) -> None:
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


def restore_lock_snapshot(path: Path, snapshot: TreeSnapshot, label: str) -> None:
    restore_tree_snapshot(
        path,
        snapshot,
        label,
        max_file_bytes=METADATA_MAX_BYTES,
        max_paths=128,
    )


def verify_lock_snapshot(path: Path, snapshot: TreeSnapshot, label: str) -> None:
    verify_tree_snapshot(
        path,
        snapshot,
        label,
        max_file_bytes=METADATA_MAX_BYTES,
        max_paths=128,
    )


def restore_external_bootstrap_namespace(
    system_root: Path,
    system_root_signature: DirectoryObjectSignature | None,
    external_lock_root: Path,
    external_lock_snapshot: TreeSnapshot,
) -> None:
    def restore_once() -> None:
        restore_lock_snapshot(
            external_lock_root,
            external_lock_snapshot,
            "external lifecycle lock root",
        )
        restore_directory_object_signature(
            system_root,
            system_root_signature,
            "system bootstrap root",
        )

    def verify_restored() -> None:
        verify_lock_snapshot(
            external_lock_root,
            external_lock_snapshot,
            "external lifecycle lock root",
        )
        verify_directory_object_signature(
            system_root,
            system_root_signature,
            "system bootstrap root",
        )

    restore_with_retries(
        restore_once,
        verify_restored,
        "external lifecycle bootstrap namespace",
    )


class RetryReadOnlyLifecycle(KimicodeSetupError):
    """Internal retry signal for a cold read racing with anchor publication."""


def acquire_product_coordination_lock(
    external_lock_root: Path,
    *,
    lock_mode: int = fcntl.LOCK_EX,
    publish_missing: bool = True,
) -> int | None:
    path = external_product_anchor_path(external_lock_root)
    if publish_missing and stat_existing(path, "external product lifecycle anchor") is None:
        publish_missing_lock_file(
            path,
            "external product lifecycle anchor",
            canonical_target=EXTERNAL_PRODUCT_ANCHOR_CANONICAL_TARGET,
            kind="external-product",
        )
    return acquire_existing_lock_file(
        path,
        "external product lifecycle anchor",
        canonical_target=EXTERNAL_PRODUCT_ANCHOR_CANONICAL_TARGET,
        kind="external-product",
        lock_mode=lock_mode,
    )


def release_product_coordination_lock(fd: int) -> None:
    try:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextlib.contextmanager
def external_lifecycle_lock(target: Path):
    lexical_target_identity(target)
    product_fd: int | None = None
    bootstrap_path: Path | None = None
    bootstrap_fd: int | None = None
    system_root = fixed_system_temp_root()
    external_lock_root = external_lock_root_path(system_root)
    pre_product_system_signature = directory_object_signature(
        system_root,
        "system bootstrap root",
    )
    pre_product_external_snapshot = snapshot_tree(
        external_lock_root,
        "external lifecycle lock root",
        max_file_bytes=METADATA_MAX_BYTES,
        max_paths=128,
    )
    try:
        external_lock_root = ensure_external_lock_root()
        product_fd = acquire_product_coordination_lock(
            external_lock_root,
            lock_mode=fcntl.LOCK_EX,
            publish_missing=True,
        )
        if product_fd is None:
            fail("external product lifecycle anchor is missing")
        canonical_target_path = canonicalize_target_under_product_lock(target)
        canonical_target = str(canonical_target_path)
        bootstrap_path = bootstrap_lock_path(
            canonical_target_path,
            canonical_target,
            external_lock_root=external_lock_root,
        )
        bootstrap_fd = acquire_lock_file(
            bootstrap_path,
            "external bootstrap lifecycle lock",
            canonical_target=canonical_target,
            kind="external-bootstrap",
            lock_mode=fcntl.LOCK_EX,
            create=True,
        )
        releasing_product_fd = product_fd
        product_fd = None
        release_product_coordination_lock(releasing_product_fd)
        try:
            yield canonical_target
        finally:
            if bootstrap_fd is not None:
                releasing_bootstrap_fd = bootstrap_fd
                bootstrap_fd = None
                release_lock_file(releasing_bootstrap_fd, bootstrap_path, remove_file=False)
    except BaseException:
        if bootstrap_fd is not None and bootstrap_path is not None:
            releasing_bootstrap_fd = bootstrap_fd
            bootstrap_fd = None
            release_lock_file(releasing_bootstrap_fd, bootstrap_path, remove_file=False)
        if product_fd is not None:
            releasing_product_fd = product_fd
            product_fd = None
            release_product_coordination_lock(releasing_product_fd)
        if (
            stat_existing(
                external_product_anchor_path(external_lock_root),
                "external product lifecycle anchor",
            )
            is None
        ):
            restore_external_bootstrap_namespace(
                system_root,
                pre_product_system_signature,
                external_lock_root,
                pre_product_external_snapshot,
            )
        raise


@contextlib.contextmanager
def readonly_external_lifecycle_lock(target: Path):
    lexical_target_identity(target)
    system_root = fixed_system_temp_root()
    external_lock_root = external_lock_root_path(system_root)
    product_fd: int | None = None
    bootstrap_path: Path | None = None
    bootstrap_fd: int | None = None
    try:
        existing_root = validate_existing_external_lock_root(external_lock_root)
        if (
            existing_root is None
            or stat_existing(
                external_product_anchor_path(external_lock_root),
                "external product lifecycle anchor",
            )
            is None
        ):
            canonical_target_path = canonicalize_target_under_product_lock(target)
            canonical_target = str(canonical_target_path)
            yield canonical_target
            if (
                stat_existing(
                    external_product_anchor_path(external_lock_root),
                    "external product lifecycle anchor",
                )
                is not None
            ):
                raise RetryReadOnlyLifecycle("external lifecycle anchor appeared during read")
            return
        product_fd = acquire_product_coordination_lock(
            external_lock_root,
            lock_mode=fcntl.LOCK_SH,
            publish_missing=False,
        )
        if product_fd is None:
            raise RetryReadOnlyLifecycle("external lifecycle anchor disappeared during read")
        canonical_target_path = canonicalize_target_under_product_lock(target)
        canonical_target = str(canonical_target_path)
        bootstrap_path = external_bootstrap_lock_path(external_lock_root, canonical_target)
        bootstrap_fd = acquire_existing_lock_file(
            bootstrap_path,
            "external bootstrap lifecycle lock",
            canonical_target=canonical_target,
            kind="external-bootstrap",
            lock_mode=fcntl.LOCK_SH,
        )
        if bootstrap_fd is not None:
            releasing_product_fd = product_fd
            product_fd = None
            release_product_coordination_lock(releasing_product_fd)
        try:
            yield canonical_target
        finally:
            if bootstrap_fd is not None:
                releasing_bootstrap_fd = bootstrap_fd
                bootstrap_fd = None
                release_lock_file(releasing_bootstrap_fd, bootstrap_path, remove_file=False)
            if product_fd is not None:
                releasing_product_fd = product_fd
                product_fd = None
                release_product_coordination_lock(releasing_product_fd)
    except BaseException:
        if bootstrap_fd is not None and bootstrap_path is not None:
            releasing_bootstrap_fd = bootstrap_fd
            bootstrap_fd = None
            release_lock_file(releasing_bootstrap_fd, bootstrap_path, remove_file=False)
        if product_fd is not None:
            releasing_product_fd = product_fd
            product_fd = None
            release_product_coordination_lock(releasing_product_fd)
        raise


def run_under_readonly_external_lifecycle(target: Path, operation) -> Any:
    for _attempt in range(3):
        try:
            with readonly_external_lifecycle_lock(target) as canonical_target:
                return operation(Path(canonical_target))
        except RetryReadOnlyLifecycle:
            continue
    fail("external lifecycle coordination changed during read")


@contextlib.contextmanager
def target_lock(target: Path, *, create_parent: bool = False):
    transaction = DirectoryTransaction([])
    internal_path: Path | None = None
    internal_fd: int | None = None
    internal_parent: ProtectedDirectory | None = None
    internal_lock_snapshot: TreeSnapshot | None = None
    target_creation_snapshot: TreeSnapshot | None = None
    try:
        with external_lifecycle_lock(target) as canonical_target:
            target = Path(canonical_target)
            parent_info = stat_existing(target.parent, "target parent")
            if create_parent:
                ensure_directory_chain(target.parent, transaction, "target parent")
                require_owner_private_directory(target.parent, "target parent")
            elif parent_info is not None:
                if not stat.S_ISDIR(parent_info.st_mode):
                    fail("target parent must be a real directory")
                if not is_owner_private_directory(parent_info):
                    fail("target parent must be private and owned by the current user")
            target_info = stat_existing(target, "target")
            if target_info is None and create_parent:
                target_creation_snapshot = TreeSnapshot(entries=None)
                transaction.remember_directory(target.parent, "target parent")
                target.mkdir(mode=OWNER_DIRECTORY_MODE)
                target.chmod(OWNER_DIRECTORY_MODE)
                transaction.created.append(target)
                target_info = stat_existing(target, "target")
            if target_info is not None:
                if not stat.S_ISDIR(target_info.st_mode):
                    fail("target must be a real directory")
                if not is_owner_private_directory(target_info):
                    fail("target must be private and owned by the current user")
                internal_lock_snapshot = snapshot_tree(
                    lock_parent_path(target),
                    "target lifecycle lock directory",
                    max_file_bytes=METADATA_MAX_BYTES,
                    max_paths=16,
                )
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
                    if internal_parent is not None:
                        restoring_parent = internal_parent
                        internal_parent = None
                        restoring_parent.restore()
                if failed:
                    if internal_lock_snapshot is not None:
                        restore_lock_snapshot(
                            lock_parent_path(target),
                            internal_lock_snapshot,
                            "target lifecycle lock directory",
                        )
                    if target_creation_snapshot is not None:
                        restore_tree_snapshot(
                            target,
                            target_creation_snapshot,
                            "target",
                            max_file_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES),
                            max_paths=SOFTWARE_MAX_PATHS + 64,
                        )
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
        if internal_lock_snapshot is not None:
            restore_lock_snapshot(
                lock_parent_path(target),
                internal_lock_snapshot,
                "target lifecycle lock directory",
            )
        if target_creation_snapshot is not None:
            restore_tree_snapshot(
                target,
                target_creation_snapshot,
                "target",
                max_file_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES),
                max_paths=SOFTWARE_MAX_PATHS + 64,
            )
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
            fsync_directory(current.parent)
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


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    if path.parent.exists():
        fsync_directory(path.parent)


def durable_rmdir(path: Path) -> None:
    try:
        path.rmdir()
    except FileNotFoundError:
        pass
    if path.parent.exists():
        fsync_directory(path.parent)


def remove_empty_directory_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except FileNotFoundError:
        return
    except OSError as exc:
        if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
            return
        raise
    if path.parent.exists():
        fsync_directory(path.parent)


def restore_with_retries(operation, verify, label: str) -> None:
    last_error: BaseException | None = None
    for _attempt in range(3):
        try:
            operation()
            verify()
            return
        except BaseException as exc:
            last_error = exc
    assert last_error is not None
    fail(f"{label} rollback did not converge after retry: {last_error}")


def snapshot_replace_destination(
    path: Path,
    label: str,
    *,
    max_bytes: int,
) -> FileSnapshot:
    info = require_existing_managed_file(path, label, max_bytes=max_bytes)
    if info is None:
        return FileSnapshot(data=None, mode=None)
    fd, opened = open_regular_readonly(path, label, max_bytes=max_bytes)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        fail(f"{label} is too large")
    return FileSnapshot(data=data, mode=stat.S_IMODE(opened.st_mode))


def verify_file_snapshot(path: Path, snapshot: FileSnapshot, label: str, *, max_bytes: int) -> None:
    info = require_existing_managed_file(path, label, max_bytes=max_bytes)
    if snapshot.data is None:
        if info is not None:
            fail(f"{label} rollback postcondition failed: expected absent")
        return
    if info is None:
        fail(f"{label} rollback postcondition failed: expected present")
    assert info is not None
    if stat.S_IMODE(info.st_mode) != (snapshot.mode or OWNER_FILE_MODE):
        fail(f"{label} rollback postcondition failed: mode mismatch")
    data = read_existing_file(path, max_bytes=max_bytes, label=label)
    if data != snapshot.data:
        fail(f"{label} rollback postcondition failed: bytes mismatch")


def restore_file_snapshot_once(
    path: Path,
    snapshot: FileSnapshot,
    target: Path,
    label: str,
    *,
    max_bytes: int,
    default_mode: int = OWNER_FILE_MODE,
) -> None:
    current = snapshot_replace_destination(path, label, max_bytes=max_bytes)
    if current == snapshot:
        return
    if snapshot.data is None:
        durable_unlink(path)
    else:
        atomic_write(path, snapshot.data, target, mode=snapshot.mode or default_mode)
    verify_file_snapshot(path, snapshot, label, max_bytes=max_bytes)


def restore_file_snapshot(
    path: Path,
    snapshot: FileSnapshot,
    target: Path,
    label: str,
    *,
    max_bytes: int,
    default_mode: int = OWNER_FILE_MODE,
) -> None:
    restore_with_retries(
        lambda: restore_file_snapshot_once(
            path,
            snapshot,
            target,
            label,
            max_bytes=max_bytes,
            default_mode=default_mode,
        ),
        lambda: verify_file_snapshot(path, snapshot, label, max_bytes=max_bytes),
        label,
    )


def rollback_replaced_destination(
    path: Path,
    snapshot: FileSnapshot,
    target: Path,
    label: str,
    *,
    max_bytes: int,
) -> None:
    restore_file_snapshot(path, snapshot, target, label, max_bytes=max_bytes)


def atomic_write(path: Path, data: bytes, target: Path, *, mode: int = OWNER_FILE_MODE) -> None:
    ensure_real_parent(path, target)
    original = snapshot_replace_destination(
        path,
        str(path),
        max_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES),
    )
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    replaced = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            os.chmod(temporary, mode)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        replaced = True
        fsync_directory(path.parent)
    except BaseException:
        if replaced:
            rollback_replaced_destination(
                path,
                original,
                target,
                str(path),
                max_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES),
            )
        else:
            restore_with_retries(
                lambda: durable_unlink(temporary),
                lambda: verify_file_snapshot(
                    temporary,
                    FileSnapshot(data=None, mode=None),
                    str(temporary),
                    max_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES),
                ),
                str(temporary),
            )
        raise


def object_sidecar(path: Path, fragment: str) -> Path:
    return path.with_name(f".{path.name}{fragment}.{os.getpid()}.{time.time_ns()}")


def remove_path_strict(path: Path, label: str, *, max_file_bytes: int, max_paths: int) -> None:
    info = stat_existing(path, label)
    if info is None:
        return
    if stat.S_ISDIR(info.st_mode):
        remove_tree_strict(path, label, max_file_bytes=max_file_bytes, max_paths=max_paths)
        return
    if not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular file or directory")
    durable_unlink(path)


def write_staged_file(path: Path, data: bytes, *, mode: int, label: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            os.chmod(path, mode)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        restore_with_retries(
            lambda: durable_unlink(path),
            lambda: verify_file_snapshot(
                path,
                FileSnapshot(data=None, mode=None),
                label,
                max_bytes=max(MANAGED_MAX_BYTES, SOFTWARE_MAX_BYTES),
            ),
            label,
        )
        raise
    if not path.is_file():
        fail(f"{label} staged file was not created")


def file_object_signature(path: Path, label: str, *, max_bytes: int) -> FileObjectSignature | None:
    info = require_existing_managed_file(path, label, max_bytes=max_bytes)
    if info is None:
        return None
    fd, opened = open_regular_readonly(path, label, max_bytes=max_bytes)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        fail(f"{label} is too large")
    return FileObjectSignature(
        st_dev=opened.st_dev,
        st_ino=opened.st_ino,
        mode=stat.S_IMODE(opened.st_mode),
        mtime_ns=opened.st_mtime_ns,
        size=opened.st_size,
        sha256=sha256_bytes(data),
    )


def file_object_matches_signature(
    path: Path,
    expected: FileObjectSignature,
    label: str,
    *,
    max_bytes: int,
) -> bool:
    current = file_object_signature(path, label, max_bytes=max_bytes)
    return current == expected


def directory_object_signature(path: Path, label: str) -> DirectoryObjectSignature | None:
    info = stat_existing(path, label)
    if info is None:
        return None
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    return DirectoryObjectSignature(
        st_dev=info.st_dev,
        st_ino=info.st_ino,
        st_size=info.st_size,
        mode=stat.S_IMODE(info.st_mode),
        atime_ns=info.st_atime_ns,
        mtime_ns=info.st_mtime_ns,
    )


def restore_directory_object_signature(
    path: Path,
    signature: DirectoryObjectSignature | None,
    label: str,
) -> None:
    if signature is None:
        if path_exists_no_follow(path):
            durable_rmdir(path)
        return
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} rollback postcondition failed: directory is missing")
    assert info is not None
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} rollback postcondition failed: not a directory")
    if info.st_dev != signature.st_dev or info.st_ino != signature.st_ino:
        fail(f"{label} rollback postcondition failed: directory identity mismatch")
    if stat.S_IMODE(info.st_mode) != signature.mode:
        path.chmod(signature.mode)
    os.utime(path, ns=(signature.atime_ns, signature.mtime_ns))
    fsync_directory(path)


def verify_directory_object_signature(
    path: Path,
    signature: DirectoryObjectSignature | None,
    label: str,
) -> None:
    current = directory_object_signature(path, label)
    if current is None or signature is None:
        if current != signature:
            fail(f"{label} rollback postcondition failed: directory metadata mismatch")
        return
    if (
        current.st_dev != signature.st_dev
        or current.st_ino != signature.st_ino
        or current.st_size != signature.st_size
        or current.mode != signature.mode
        or current.mtime_ns != signature.mtime_ns
    ):
        fail(f"{label} rollback postcondition failed: directory metadata mismatch")


class FileObjectTransaction:
    def __init__(self, target: Path):
        self.target = target
        self.changes: list[FileObjectChange] = []
        self.directory_signatures: dict[Path, DirectoryObjectSignature | None] = {}

    def remember_directory(self, path: Path, label: str) -> None:
        if path not in self.directory_signatures:
            self.directory_signatures[path] = directory_object_signature(path, label)

    def ensure_parent(self, path: Path) -> None:
        relative_parent = path.relative_to(self.target).parent
        current = self.target
        for part in relative_parent.parts:
            self.remember_directory(current, f"managed directory {current}")
            current = current / part
            info = stat_existing(current, f"managed directory {current}")
            if info is None:
                self.remember_directory(current, f"managed directory {current}")
                current.mkdir(mode=OWNER_DIRECTORY_MODE)
                current.chmod(OWNER_DIRECTORY_MODE)
                fsync_directory(current.parent)
                continue
            if not stat.S_ISDIR(info.st_mode):
                fail(f"managed parent is not a directory: {current}")
            if not is_owner_private_directory(info):
                fail(f"managed parent must be private and owned by the current user: {current}")

    def stage_write(
        self,
        path: Path,
        data: bytes,
        *,
        mode: int = OWNER_FILE_MODE,
        label: str | None = None,
        max_bytes: int = MANAGED_MAX_BYTES,
    ) -> None:
        label = str(path) if label is None else label
        self.ensure_parent(path)
        self.remember_directory(path.parent, f"{label} parent")
        staged = object_sidecar(path, ".nddev.tmp")
        write_staged_file(staged, data, mode=mode, label=label)
        self.changes.append(
            FileObjectChange(
                path=path,
                rollback_path=None,
                staged_path=staged,
                original_present=False,
                original_signature=None,
                original_checked=False,
                label=label,
                max_bytes=max_bytes,
            )
        )

    def stage_remove(
        self,
        path: Path,
        *,
        label: str | None = None,
        max_bytes: int = MANAGED_MAX_BYTES,
    ) -> None:
        label = str(path) if label is None else label
        self.changes.append(
            FileObjectChange(
                path=path,
                rollback_path=None,
                staged_path=None,
                original_present=False,
                original_signature=None,
                original_checked=False,
                label=label,
                max_bytes=max_bytes,
            )
        )

    def stage_replace_with_staged(
        self,
        path: Path,
        staged_path: Path,
        *,
        label: str | None = None,
        max_bytes: int = MANAGED_MAX_BYTES,
    ) -> None:
        label = str(path) if label is None else label
        self.changes.append(
            FileObjectChange(
                path=path,
                rollback_path=None,
                staged_path=staged_path,
                original_present=False,
                original_signature=None,
                original_checked=False,
                label=label,
                max_bytes=max_bytes,
            )
        )

    def apply_once(self) -> None:
        for change in self.changes:
            if change.applied:
                continue
            self.remember_directory(change.path.parent, f"{change.label} parent")
            change.original_signature = file_object_signature(
                change.path, change.label, max_bytes=change.max_bytes
            )
            change.original_checked = True
            change.original_present = change.original_signature is not None
            if change.original_present:
                rollback = object_sidecar(change.path, ".nddev.rollback")
                os.replace(change.path, rollback)
                change.rollback_path = rollback
                change.applied = True
                fsync_directory(change.path.parent)
            else:
                change.applied = True
            if change.staged_path is not None:
                os.replace(change.staged_path, change.path)
                fsync_directory(change.path.parent)

    def original_is_restored(self, change: FileObjectChange) -> bool:
        signature = change.original_signature
        return (
            signature is not None
            and path_exists_no_follow(change.path)
            and file_object_matches_signature(
                change.path,
                signature,
                change.label,
                max_bytes=change.max_bytes,
            )
        )

    def rollback_once(self) -> None:
        for change in reversed(self.changes):
            if not change.applied:
                if change.staged_path is not None:
                    durable_unlink(change.staged_path)
                continue
            if (
                change.original_present
                and change.rollback_path is not None
                and not path_exists_no_follow(change.rollback_path)
                and self.original_is_restored(change)
            ):
                fsync_directory(change.path.parent)
                if change.staged_path is not None:
                    durable_unlink(change.staged_path)
                change.applied = False
                continue
            if path_exists_no_follow(change.path):
                durable_unlink(change.path)
            if change.original_present:
                if change.rollback_path is None:
                    fail(f"{change.label} rollback sidecar is missing")
                if not path_exists_no_follow(change.rollback_path):
                    if self.original_is_restored(change):
                        fsync_directory(change.path.parent)
                        change.applied = False
                        continue
                    fail(f"{change.label} rollback sidecar is missing")
                ensure_real_parent(change.path, self.target)
                os.replace(change.rollback_path, change.path)
                fsync_directory(change.path.parent)
            elif change.rollback_path is not None:
                durable_unlink(change.rollback_path)
            if change.staged_path is not None:
                durable_unlink(change.staged_path)
            change.applied = False
        self.restore_directory_signatures_once()

    def restore_directory_signatures_once(self) -> None:
        for path, signature in sorted(
            self.directory_signatures.items(),
            key=lambda item: len(item[0].parts),
            reverse=True,
        ):
            restore_directory_object_signature(path, signature, str(path))

    def rollback(self) -> None:
        restore_with_retries(
            self.rollback_once,
            self.verify_rolled_back,
            "managed file objects",
        )

    def verify_rolled_back(self) -> None:
        for change in self.changes:
            if change.applied:
                fail(f"{change.label} rollback did not finish")
            if change.original_checked and change.original_present:
                signature = change.original_signature
                if signature is None or not self.original_is_restored(change):
                    fail(f"{change.label} rollback postcondition failed: original identity")
            elif change.original_checked and path_exists_no_follow(change.path):
                fail(f"{change.label} rollback postcondition failed: expected absent")
            if change.staged_path is not None and path_exists_no_follow(change.staged_path):
                fail(f"{change.label} staged residue remains")
            if change.rollback_path is not None and path_exists_no_follow(change.rollback_path):
                fail(f"{change.label} rollback residue remains")
        self.verify_directory_signatures()

    def verify_no_residue(self) -> None:
        for change in self.changes:
            if change.staged_path is not None and path_exists_no_follow(change.staged_path):
                fail(f"{change.label} staged residue remains")
            if change.rollback_path is not None and path_exists_no_follow(change.rollback_path):
                fail(f"{change.label} rollback residue remains")

    def verify_directory_signatures(self) -> None:
        for path, signature in self.directory_signatures.items():
            verify_directory_object_signature(path, signature, str(path))

    def commit_once(self) -> None:
        for change in self.changes:
            if change.rollback_path is not None:
                durable_unlink(change.rollback_path)
            if change.staged_path is not None:
                durable_unlink(change.staged_path)

    def commit(self) -> None:
        restore_with_retries(
            self.commit_once,
            self.verify_no_residue,
            "managed file object cleanup",
        )


class TreeObjectTransaction:
    def __init__(self):
        self.changes: list[TreeObjectChange] = []
        self.directory_signatures: dict[Path, DirectoryObjectSignature | None] = {}

    def remember_directory(self, path: Path, label: str) -> None:
        if path not in self.directory_signatures:
            self.directory_signatures[path] = directory_object_signature(path, label)

    def stage_replace_tree(
        self,
        path: Path,
        staged_path: Path,
        *,
        label: str,
        max_file_bytes: int,
        max_paths: int,
    ) -> None:
        self.changes.append(
            TreeObjectChange(
                path=path,
                rollback_path=None,
                staged_path=staged_path,
                original_present=False,
                label=label,
                max_file_bytes=max_file_bytes,
                max_paths=max_paths,
            )
        )

    def stage_remove_tree(
        self,
        path: Path,
        *,
        label: str,
        max_file_bytes: int,
        max_paths: int,
    ) -> None:
        self.changes.append(
            TreeObjectChange(
                path=path,
                rollback_path=None,
                staged_path=None,
                original_present=False,
                label=label,
                max_file_bytes=max_file_bytes,
                max_paths=max_paths,
            )
        )

    def apply_once(self) -> None:
        for change in self.changes:
            if change.applied:
                continue
            self.remember_directory(change.path.parent, f"{change.label} parent")
            original_info = stat_existing(change.path, change.label)
            change.original_present = original_info is not None
            if change.original_present:
                if not stat.S_ISDIR(original_info.st_mode):
                    fail(f"{change.label} must be a directory")
                rollback = object_sidecar(change.path, ".nddev-kimicode-software-rollback")
                os.replace(change.path, rollback)
                change.rollback_path = rollback
                change.applied = True
                fsync_directory(change.path.parent)
            else:
                change.applied = True
            if change.staged_path is not None:
                os.replace(change.staged_path, change.path)
                fsync_directory(change.path.parent)

    def rollback_once(self) -> None:
        for change in reversed(self.changes):
            if not change.applied:
                if change.staged_path is not None:
                    remove_path_strict(
                        change.staged_path,
                        change.label,
                        max_file_bytes=change.max_file_bytes,
                        max_paths=change.max_paths,
                    )
                continue
            if (
                change.original_present
                and change.rollback_path is not None
                and not path_exists_no_follow(change.rollback_path)
                and path_exists_no_follow(change.path)
            ):
                fsync_directory(change.path.parent)
                if change.staged_path is not None:
                    remove_path_strict(
                        change.staged_path,
                        change.label,
                        max_file_bytes=change.max_file_bytes,
                        max_paths=change.max_paths,
                    )
                change.applied = False
                continue
            remove_path_strict(
                change.path,
                change.label,
                max_file_bytes=change.max_file_bytes,
                max_paths=change.max_paths,
            )
            if change.original_present:
                if change.rollback_path is None:
                    fail(f"{change.label} rollback sidecar is missing")
                if not path_exists_no_follow(change.rollback_path):
                    if path_exists_no_follow(change.path):
                        fsync_directory(change.path.parent)
                        change.applied = False
                        continue
                    fail(f"{change.label} rollback sidecar is missing")
                os.replace(change.rollback_path, change.path)
                fsync_directory(change.path.parent)
            elif change.rollback_path is not None:
                remove_path_strict(
                    change.rollback_path,
                    change.label,
                    max_file_bytes=change.max_file_bytes,
                    max_paths=change.max_paths,
                )
            if change.staged_path is not None:
                remove_path_strict(
                    change.staged_path,
                    change.label,
                    max_file_bytes=change.max_file_bytes,
                    max_paths=change.max_paths,
                )
            change.applied = False
        self.restore_directory_signatures_once()

    def restore_directory_signatures_once(self) -> None:
        for path, signature in sorted(
            self.directory_signatures.items(),
            key=lambda item: len(item[0].parts),
            reverse=True,
        ):
            restore_directory_object_signature(path, signature, str(path))

    def rollback(self) -> None:
        restore_with_retries(
            self.rollback_once,
            self.verify_rolled_back,
            "software tree objects",
        )

    def verify_rolled_back(self) -> None:
        for change in self.changes:
            if change.applied:
                fail(f"{change.label} rollback did not finish")
            for sidecar in (change.rollback_path, change.staged_path):
                if sidecar is not None and path_exists_no_follow(sidecar):
                    fail(f"{change.label} object transaction residue remains")
        self.verify_directory_signatures()

    def verify_clean(self) -> None:
        for change in self.changes:
            for sidecar in (change.rollback_path, change.staged_path):
                if sidecar is not None and path_exists_no_follow(sidecar):
                    fail(f"{change.label} object transaction residue remains")

    def verify_directory_signatures(self) -> None:
        for path, signature in self.directory_signatures.items():
            verify_directory_object_signature(path, signature, str(path))

    def commit_once(self) -> None:
        for change in self.changes:
            for sidecar in (change.rollback_path, change.staged_path):
                if sidecar is not None:
                    remove_path_strict(
                        sidecar,
                        change.label,
                        max_file_bytes=change.max_file_bytes,
                        max_paths=change.max_paths,
                    )

    def commit(self) -> None:
        restore_with_retries(self.commit_once, self.verify_clean, "software object cleanup")


def tree_relative(path: Path, root: Path) -> str:
    if path == root:
        return "."
    return path.relative_to(root).as_posix()


def tree_entry_from_stat(
    relative: str, kind: str, info: os.stat_result, data: bytes | None = None
) -> TreeEntry:
    return TreeEntry(
        path=relative,
        kind=kind,
        size=info.st_size,
        mode=stat.S_IMODE(info.st_mode),
        st_dev=info.st_dev,
        st_ino=info.st_ino,
        mtime_ns=info.st_mtime_ns,
        data=data,
    )


def snapshot_tree(root: Path, label: str, *, max_file_bytes: int, max_paths: int) -> TreeSnapshot:
    root_info = stat_existing(root, label)
    if root_info is None:
        return TreeSnapshot(entries=None)
    if not stat.S_ISDIR(root_info.st_mode):
        fail(f"{label} must be a directory")
    entries: dict[str, TreeEntry] = {
        ".": tree_entry_from_stat(".", "dir", root_info),
    }
    count = 1
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        count += 1
        if count > max_paths:
            fail(f"{label} has too many paths")
        relative = tree_relative(path, root)
        info = stat_existing(path, f"{label} entry {relative}")
        if info is None:
            fail(f"{label} entry disappeared while snapshotting: {relative}")
        if stat.S_ISDIR(info.st_mode):
            entries[relative] = tree_entry_from_stat(relative, "dir", info)
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"{label} entry must be a regular file or directory: {relative}")
        if info.st_nlink != 1:
            fail(f"{label} entry must not be a hardlink: {relative}")
        if info.st_size > max_file_bytes:
            fail(f"{label} entry is too large: {relative}")
        fd, opened = open_regular_readonly(
            path, f"{label} entry {relative}", max_bytes=max_file_bytes
        )
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(max_file_bytes + 1)
        if opened.st_size != info.st_size:
            fail(f"{label} entry changed while snapshotting: {relative}")
        if len(data) > max_file_bytes:
            fail(f"{label} entry is too large: {relative}")
        entries[relative] = tree_entry_from_stat(relative, "file", opened, data)
    return TreeSnapshot(entries=entries)


def verify_tree_snapshot(
    root: Path, expected: TreeSnapshot, label: str, *, max_file_bytes: int, max_paths: int
) -> None:
    current = snapshot_tree(root, label, max_file_bytes=max_file_bytes, max_paths=max_paths)
    if current != expected:
        fail(f"{label} rollback postcondition failed: tree mismatch")


def remove_tree_once(root: Path, label: str, *, max_file_bytes: int, max_paths: int) -> None:
    current = snapshot_tree(root, label, max_file_bytes=max_file_bytes, max_paths=max_paths)
    if current.entries is None:
        return
    for relative, entry in sorted(
        ((relative, entry) for relative, entry in current.entries.items() if relative != "."),
        key=lambda item: item[0].count("/"),
        reverse=True,
    ):
        path = root / relative
        if entry.kind == "dir":
            durable_rmdir(path)
        else:
            durable_unlink(path)
    durable_rmdir(root)


def remove_tree_strict(root: Path, label: str, *, max_file_bytes: int, max_paths: int) -> None:
    restore_with_retries(
        lambda: remove_tree_once(root, label, max_file_bytes=max_file_bytes, max_paths=max_paths),
        lambda: verify_tree_snapshot(
            root,
            TreeSnapshot(entries=None),
            label,
            max_file_bytes=max_file_bytes,
            max_paths=max_paths,
        ),
        label,
    )


def cleanup_journal_dir(target: Path) -> Path:
    return target / CLEANUP_DIR_NAME


def cleanup_journal_path(target: Path) -> Path:
    return cleanup_journal_dir(target) / CLEANUP_JOURNAL_NAME


def cleanup_intent_path(target: Path) -> Path:
    return cleanup_journal_dir(target) / CLEANUP_INTENT_NAME


def cleanup_journal_stage_alias_pattern(journal_path: Path) -> re.Pattern[str]:
    return re.compile(rf"\.{re.escape(journal_path.name)}\.nddev\.tmp\.[0-9]+\.[0-9]+\Z")


def cleanup_operation_kind_for_source(
    target: Path,
    path: Path,
    *,
    label: str,
    max_file_bytes: int,
    max_paths: int,
) -> str:
    name = path.name
    if (
        path.parent == backup_pool(target)
        and label == "old backup slot"
        and max_file_bytes == METADATA_MAX_BYTES
        and max_paths <= 64
        and re.fullmatch(r"\.[0-9]+\.nddev-backup-old\.[0-9]+\.[0-9]+\Z", name)
    ):
        return "backup-old-slot"
    if (
        path.parent == backup_pool(target)
        and label == "backup stage"
        and max_file_bytes == METADATA_MAX_BYTES
        and max_paths <= 64
        and re.fullmatch(r"\.[0-9]+\.nddev-backup-stage\.[0-9]+\.[0-9]+\Z", name)
    ):
        return "backup-stage"
    if (
        path.parent == target
        and label == "software stage"
        and max_file_bytes == SOFTWARE_MAX_BYTES
        and max_paths <= SOFTWARE_MAX_PATHS + 16
        and re.fullmatch(
            rf"\.{re.escape(target.name)}{re.escape(SOFTWARE_STAGE_FRAGMENT)}\.[0-9]+\.[0-9]+\Z",
            name,
        )
    ):
        return "software-stage"
    if (
        path.parent == software_root(target)
        and label == "current software tree"
        and max_file_bytes == SOFTWARE_MAX_BYTES
        and max_paths <= SOFTWARE_MAX_PATHS
        and re.fullmatch(
            rf"\.{re.escape(SOFTWARE_CURRENT_NAME)}\.nddev-kimicode-software-rollback\.[0-9]+\.[0-9]+\Z",
            name,
        )
    ):
        return "software-current-tree-rollback"
    if (
        path.parent == target
        and label == "software root"
        and max_file_bytes == SOFTWARE_MAX_BYTES
        and max_paths <= SOFTWARE_MAX_PATHS
        and re.fullmatch(
            rf"\.{re.escape(SOFTWARE_DIR_NAME)}\.nddev-kimicode-software-rollback\.[0-9]+\.[0-9]+\Z",
            name,
        )
    ):
        return "software-root-tree-rollback"
    if (
        path.parent == target
        and label == "Kimi Code bin parent"
        and max_file_bytes == SOFTWARE_MAX_BYTES
        and max_paths <= 16
        and re.fullmatch(r"\.bin\.nddev-kimicode-software-rollback\.[0-9]+\.[0-9]+\Z", name)
    ):
        return "software-bin-tree-rollback"
    if (
        path.parent == software_entrypoint(target).parent
        and label == "Kimi Code entrypoint"
        and max_file_bytes == SOFTWARE_MAX_BYTES
        and max_paths == 1
        and re.fullmatch(rf"\.{re.escape(KIMI_COMMAND)}\.nddev\.tmp\.[0-9]+\.[0-9]+\Z", name)
    ):
        return "software-entrypoint-stage-file"
    if (
        path.parent == software_entrypoint(target).parent
        and label == "Kimi Code entrypoint"
        and max_file_bytes == SOFTWARE_MAX_BYTES
        and max_paths == 1
        and re.fullmatch(rf"\.{re.escape(KIMI_COMMAND)}\.nddev\.rollback\.[0-9]+\.[0-9]+\Z", name)
    ):
        return "software-entrypoint-rollback-file"
    if (
        path.parent == target
        and label == SOFTWARE_STAMP_NAME
        and max_file_bytes == METADATA_MAX_BYTES
        and max_paths == 1
        and re.fullmatch(
            rf"\.{re.escape(SOFTWARE_STAMP_NAME)}\.nddev\.tmp\.[0-9]+\.[0-9]+\Z",
            name,
        )
    ):
        return "software-stamp-stage-file"
    if (
        path.parent == target
        and label == SOFTWARE_STAMP_NAME
        and max_file_bytes == METADATA_MAX_BYTES
        and max_paths == 1
        and re.fullmatch(
            rf"\.{re.escape(SOFTWARE_STAMP_NAME)}\.nddev\.rollback\.[0-9]+\.[0-9]+\Z",
            name,
        )
    ):
        return "software-stamp-rollback-file"
    fail(f"cleanup source is not a declared machine-generated object: {path}")


def cleanup_tombstone_is_allowed(target: Path, path: Path) -> bool:
    try:
        path.relative_to(cleanup_journal_dir(target))
    except ValueError:
        return False
    return (
        re.fullmatch(
            r"[0-9]{2}-(?:"
            r"\.[0-9]+\.nddev-backup-(?:old|stage)\.[0-9]+\.[0-9]+"
            r"|"
            + rf"\.{re.escape(KIMI_COMMAND)}\.nddev\.(?:tmp|rollback)\.[0-9]+\.[0-9]+"
            + r"|"
            + rf"\.{re.escape(SOFTWARE_STAMP_NAME)}\.nddev\.(?:tmp|rollback)\.[0-9]+\.[0-9]+"
            + r"|"
            + rf"\.{re.escape(target.name)}{re.escape(SOFTWARE_STAGE_FRAGMENT)}\.[0-9]+\.[0-9]+"
            + r"|"
            + rf"\.(?:{re.escape(SOFTWARE_CURRENT_NAME)}|{re.escape(SOFTWARE_DIR_NAME)}|bin)\.nddev-kimicode-software-rollback\.[0-9]+\.[0-9]+"
            + r")\Z",
            path.name,
        )
        is not None
    )


def cleanup_tombstone_name(source: Path, index: int) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", source.name)
    return f"{index:02d}-{safe}"


def cleanup_relative_to_anchor(target: Path, path: Path) -> tuple[str, str]:
    if path == target:
        return "target", "."
    if path == backup_pool(target):
        return "backup_pool", "."
    try:
        relative = path.relative_to(target).as_posix()
    except ValueError:
        try:
            relative = path.relative_to(backup_pool(target)).as_posix()
        except ValueError:
            fail(f"cleanup source is outside declared bounds: {path}")
        anchor = "backup_pool"
    else:
        anchor = "target"
    if relative == "":
        relative = "."
    relative_path = Path(relative)
    if relative_path.is_absolute() or relative in {"", ".."} or ".." in relative_path.parts:
        fail(f"cleanup source relative path is invalid: {path}")
    return anchor, relative


def cleanup_anchor_path(target: Path, anchor: str) -> Path:
    if anchor == "target":
        return target
    if anchor == "backup_pool":
        return backup_pool(target)
    fail("cleanup source anchor is invalid")


def cleanup_source_admission(
    target: Path,
    path: Path,
    *,
    label: str,
    max_file_bytes: int,
    max_paths: int,
) -> CleanupSourceAdmission:
    operation_kind = cleanup_operation_kind_for_source(
        target,
        path,
        label=label,
        max_file_bytes=max_file_bytes,
        max_paths=max_paths,
    )
    anchor, relative = cleanup_relative_to_anchor(target, path)
    parent_anchor, parent_relative = cleanup_relative_to_anchor(target, path.parent)
    parent_info = stat_existing(path.parent, "cleanup source parent")
    if parent_info is None or not stat.S_ISDIR(parent_info.st_mode):
        fail("cleanup source parent is invalid")
    return CleanupSourceAdmission(
        operation_kind=operation_kind,
        anchor=anchor,
        relative=relative,
        parent_anchor=parent_anchor,
        parent_relative=parent_relative,
        parent_st_dev=parent_info.st_dev,
        parent_st_ino=parent_info.st_ino,
    )


def cleanup_source_binding(
    target: Path,
    path: Path,
    *,
    label: str,
    max_file_bytes: int,
    max_paths: int,
) -> dict[str, Any]:
    admission = cleanup_source_admission(
        target,
        path,
        label=label,
        max_file_bytes=max_file_bytes,
        max_paths=max_paths,
    )
    return {
        "operation_kind": admission.operation_kind,
        "anchor": admission.anchor,
        "relative": admission.relative,
        "parent_anchor": admission.parent_anchor,
        "parent_relative": admission.parent_relative,
        "parent_st_dev": admission.parent_st_dev,
        "parent_st_ino": admission.parent_st_ino,
    }


def cleanup_parent_binding(target: Path, path: Path) -> dict[str, Any]:
    anchor, relative = cleanup_relative_to_anchor(target, path)
    if anchor != "target" or relative != CLEANUP_DIR_NAME:
        fail("cleanup parent binding is outside declared bounds")
    info = stat_existing(path, "cleanup journal directory")
    if info is None or not stat.S_ISDIR(info.st_mode):
        fail("cleanup journal directory is missing")
    if not is_current_owner(info) or stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("cleanup journal directory must be private and owned by the current user")
    return {
        "anchor": anchor,
        "relative": relative,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
    }


def validate_cleanup_parent_binding(target: Path, binding: Any) -> None:
    if not isinstance(binding, dict) or set(binding) != {
        "anchor",
        "relative",
        "st_dev",
        "st_ino",
        "mode",
    }:
        fail("cleanup intent parent binding schema is invalid")
    if (
        binding.get("anchor") != "target"
        or binding.get("relative") != CLEANUP_DIR_NAME
        or not isinstance(binding.get("st_dev"), int)
        or not isinstance(binding.get("st_ino"), int)
        or binding.get("mode") != OWNER_DIRECTORY_MODE
    ):
        fail("cleanup intent parent binding is invalid")
    info = stat_existing(cleanup_journal_dir(target), "cleanup journal directory")
    if info is None or not stat.S_ISDIR(info.st_mode):
        fail("cleanup journal directory is missing")
    if (
        info.st_dev != binding["st_dev"]
        or info.st_ino != binding["st_ino"]
        or stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE
        or not is_current_owner(info)
    ):
        fail("cleanup intent parent identity is invalid")


def cleanup_source_path_from_binding(target: Path, binding: dict[str, Any]) -> Path:
    if set(binding) != {
        "operation_kind",
        "anchor",
        "relative",
        "parent_anchor",
        "parent_relative",
        "parent_st_dev",
        "parent_st_ino",
    }:
        fail("cleanup intent source binding schema is invalid")
    anchor = binding.get("anchor")
    relative = binding.get("relative")
    if not isinstance(anchor, str) or not isinstance(relative, str):
        fail("cleanup intent source relative path is invalid")
    relative_path = Path(relative)
    if relative_path.is_absolute() or relative in {"", ".."} or ".." in relative_path.parts:
        fail("cleanup intent source relative path is invalid")
    if relative == ".":
        fail("cleanup intent source relative path is invalid")
    return cleanup_anchor_path(target, anchor) / relative_path


def cleanup_parent_path_from_binding(target: Path, binding: dict[str, Any]) -> Path:
    parent_anchor = binding.get("parent_anchor")
    parent_relative = binding.get("parent_relative")
    if not isinstance(parent_anchor, str) or not isinstance(parent_relative, str):
        fail("cleanup intent source parent binding is invalid")
    parent_relative_path = Path(parent_relative)
    if (
        parent_relative_path.is_absolute()
        or parent_relative in {"", ".."}
        or ".." in parent_relative_path.parts
    ):
        fail("cleanup intent source parent relative path is invalid")
    parent = cleanup_anchor_path(target, parent_anchor)
    return parent if parent_relative == "." else parent / parent_relative_path


def validate_cleanup_source_binding(
    target: Path,
    entry: dict[str, Any],
    binding: dict[str, Any],
) -> Path:
    source_path = cleanup_source_path_from_binding(target, binding)
    operation_kind = binding.get("operation_kind")
    parent = cleanup_parent_path_from_binding(target, binding)
    if not isinstance(operation_kind, str):
        fail("cleanup intent source kind is invalid")
    if parent != source_path.parent:
        fail("cleanup intent source parent binding is invalid")
    parent_info = stat_existing(parent, "cleanup source parent")
    if parent_info is None or not stat.S_ISDIR(parent_info.st_mode):
        fail("cleanup source parent is invalid")
    if (
        not isinstance(binding.get("parent_st_dev"), int)
        or not isinstance(binding.get("parent_st_ino"), int)
        or parent_info.st_dev != binding["parent_st_dev"]
        or parent_info.st_ino != binding["parent_st_ino"]
    ):
        fail("cleanup intent source parent identity is invalid")
    expected_kind = cleanup_operation_kind_for_source(
        target,
        source_path,
        label=str(entry["label"]),
        max_file_bytes=int(entry["max_file_bytes"]),
        max_paths=int(entry["max_paths"]),
    )
    if operation_kind != expected_kind:
        fail("cleanup intent source kind is invalid")
    return source_path


def tree_snapshot_summary(snapshot: TreeSnapshot) -> dict[str, Any]:
    if snapshot.entries is None:
        return {"path_count": 0, "size_bytes": 0, "sha256": None}
    digest = hashlib.sha256()
    total_size = 0
    for relative, entry in sorted(snapshot.entries.items()):
        digest.update(
            f"{relative}\0{entry.kind}\0{entry.mode:o}\0{entry.size}\0{entry.mtime_ns}\n".encode(
                "utf-8"
            )
        )
        if entry.data is not None:
            digest.update(entry.data)
            total_size += len(entry.data)
    return {
        "path_count": len(snapshot.entries),
        "size_bytes": total_size,
        "sha256": digest.hexdigest(),
    }


def cleanup_graph_entry(
    path: Path,
    root: Path,
    label: str,
    *,
    max_file_bytes: int,
) -> dict[str, Any]:
    relative = "." if path == root else path.relative_to(root).as_posix()
    info = stat_existing(path, f"{label} cleanup object {relative}")
    if info is None:
        fail(f"cleanup tombstone object disappeared while snapshotting: {relative}")
    if stat.S_ISDIR(info.st_mode):
        kind = "directory"
        digest = None
    elif stat.S_ISREG(info.st_mode):
        kind = "file"
        if info.st_nlink != 1:
            fail(f"cleanup tombstone object must not be a hardlink: {relative}")
        digest = file_sha256(
            path, label=f"{label} cleanup object {relative}", max_bytes=max_file_bytes
        )
    else:
        fail(f"cleanup tombstone object kind is invalid: {relative}")
    return {
        "relative": relative,
        "kind": kind,
        "uid": info.st_uid,
        "mode": stat.S_IMODE(info.st_mode),
        "nlink": info.st_nlink,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "sha256": digest,
    }


def cleanup_tombstone_graph(
    path: Path,
    label: str,
    kind: str,
    *,
    max_file_bytes: int,
    max_paths: int,
) -> list[dict[str, Any]]:
    if kind == "file":
        return [cleanup_graph_entry(path, path, label, max_file_bytes=max_file_bytes)]
    paths = [path]
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        paths.append(child)
        if len(paths) > max_paths:
            fail(f"{label} cleanup tombstone has too many paths")
    return [
        cleanup_graph_entry(child, path, label, max_file_bytes=max_file_bytes) for child in paths
    ]


def cleanup_graph_summary(graph: list[dict[str, Any]]) -> dict[str, Any]:
    digest = hashlib.sha256()
    total_size = 0
    for entry in sorted(graph, key=lambda item: str(item["relative"])):
        digest.update(
            (
                f"{entry['relative']}\0{entry['kind']}\0{entry['uid']}\0{entry['mode']:o}"
                f"\0{entry['nlink']}\0{entry['st_dev']}\0{entry['st_ino']}"
                f"\0{entry['size']}\0{entry['mtime_ns']}\0{entry['sha256']}\n"
            ).encode("utf-8")
        )
        if entry["kind"] == "file":
            total_size += int(entry["size"])
    return {
        "path_count": len(graph),
        "size_bytes": total_size,
        "sha256": digest.hexdigest(),
    }


def cleanup_entry_for_tombstone(
    target: Path,
    path: Path,
    *,
    relative_name: str,
    label: str,
    max_file_bytes: int,
    max_paths: int,
    require_tombstone_bound: bool = True,
) -> dict[str, Any] | None:
    if not path_exists_no_follow(path):
        return None
    if require_tombstone_bound and not cleanup_tombstone_is_allowed(target, path):
        fail(f"cleanup tombstone is outside declared bounds: {path}")
    info = stat_existing(path, label)
    if info is None:
        return None
    if stat.S_ISDIR(info.st_mode):
        kind = "directory"
    elif stat.S_ISREG(info.st_mode):
        kind = "file"
    else:
        fail(f"cleanup tombstone kind is invalid: {path}")
    if kind == "file" and info.st_nlink != 1:
        fail(f"cleanup tombstone link count is invalid: {path}")
    graph = cleanup_tombstone_graph(
        path,
        label,
        kind,
        max_file_bytes=max_file_bytes,
        max_paths=max_paths,
    )
    summary = cleanup_graph_summary(graph)
    return {
        "relative_name": relative_name,
        "label": label,
        "kind": kind,
        "uid": info.st_uid,
        "mode": stat.S_IMODE(info.st_mode),
        "nlink": info.st_nlink,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "max_file_bytes": max_file_bytes,
        "max_paths": max_paths,
        "path_count": summary["path_count"],
        "size_bytes": summary["size_bytes"],
        "sha256": summary["sha256"],
        "graph": graph,
    }


def cleanup_journal_payload(target: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": CLEANUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "canonical_target": str(validate_target(target, create=False)),
        "entries": entries,
    }


def serialized_cleanup_journal_bytes(journal: dict[str, Any]) -> bytes:
    data = canonical_json(journal)
    if len(data) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal serialized size exceeds bound")
    return data


def build_cleanup_journal_for_entries(
    target: Path, entries: list[dict[str, Any]]
) -> tuple[dict[str, Any], bytes]:
    journal = cleanup_journal_payload(target, entries)
    return journal, serialized_cleanup_journal_bytes(journal)


def cleanup_intent_payload(
    target: Path,
    journal: dict[str, Any],
    moves: list[dict[str, Any]],
    cleanup_parent: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": CLEANUP_INTENT_SCHEMA,
        "product_name": PRODUCT_NAME,
        "canonical_target": str(validate_target(target, create=False)),
        "cleanup_parent": cleanup_parent,
        "journal": journal,
        "moves": moves,
    }


def serialized_cleanup_intent_bytes(intent: dict[str, Any]) -> bytes:
    data = canonical_json(intent)
    if len(data) > CLEANUP_INTENT_MAX_BYTES:
        fail("cleanup intent serialized size exceeds bound")
    return data


def build_cleanup_intent(
    target: Path,
    journal: dict[str, Any],
    moves: list[dict[str, Any]],
    cleanup_parent: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bytes]:
    intent = cleanup_intent_payload(target, journal, moves, cleanup_parent)
    return intent, serialized_cleanup_intent_bytes(intent)


def read_cleanup_intent_json(target: Path) -> dict[str, Any]:
    intent_path = cleanup_intent_path(target)
    info = stat_existing(intent_path, CLEANUP_INTENT_NAME)
    if info is None:
        fail("cleanup intent is missing")
    if not stat.S_ISREG(info.st_mode):
        fail("cleanup intent must be a regular file")
    if not is_current_owner(info):
        fail("cleanup intent must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail("cleanup intent must be private with mode 0600")
    if info.st_nlink != 1:
        fail("cleanup intent must not be a hardlink")
    if info.st_size > CLEANUP_INTENT_MAX_BYTES:
        fail("cleanup intent is too large")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(intent_path, flags)
    except OSError as exc:
        fail(f"cleanup intent could not be opened safely: {exc}")
    try:
        opened = os.fstat(fd)
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            fail("cleanup intent changed while opening")
        if (
            not stat.S_ISREG(opened.st_mode)
            or not is_current_owner(opened)
            or stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE
            or opened.st_nlink != 1
            or opened.st_size > CLEANUP_INTENT_MAX_BYTES
        ):
            fail("cleanup intent metadata is invalid")
        data = os.read(fd, CLEANUP_INTENT_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > CLEANUP_INTENT_MAX_BYTES:
        fail("cleanup intent is too large")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cleanup intent is invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail("cleanup intent must contain a JSON object")
    return value


def validate_cleanup_intent(target: Path) -> dict[str, Any] | None:
    intent_path = cleanup_intent_path(target)
    if stat_existing(intent_path, CLEANUP_INTENT_NAME) is None:
        return None
    intent = read_cleanup_intent_json(target)
    if set(intent) != {
        "schema_version",
        "product_name",
        "canonical_target",
        "cleanup_parent",
        "journal",
        "moves",
    }:
        fail("cleanup intent schema is invalid")
    if (
        intent.get("schema_version") != CLEANUP_INTENT_SCHEMA
        or intent.get("product_name") != PRODUCT_NAME
    ):
        fail("cleanup intent owner is invalid")
    if intent.get("canonical_target") != str(validate_target(target, create=False)):
        fail("cleanup intent target binding is invalid")
    journal = intent.get("journal")
    moves = intent.get("moves")
    if not isinstance(journal, dict) or not isinstance(moves, list):
        fail("cleanup intent payload is invalid")
    validate_cleanup_parent_binding(target, intent.get("cleanup_parent"))
    expected_journal, _serialized_journal = build_cleanup_journal_for_entries(
        target, list(journal.get("entries", [])) if isinstance(journal.get("entries"), list) else []
    )
    if journal != expected_journal:
        fail("cleanup intent journal payload is invalid")
    entries = journal.get("entries")
    if (
        not isinstance(entries, list)
        or not entries
        or len(entries) > CLEANUP_MAX_ENTRIES
        or len(moves) != len(entries)
    ):
        fail("cleanup intent moves are invalid")
    seen: set[str] = set()
    for entry, move in zip(entries, moves):
        if not isinstance(entry, dict) or not isinstance(move, dict):
            fail("cleanup intent entry is invalid")
        if set(move) != {"relative_name", "source"}:
            fail("cleanup intent move schema is invalid")
        relative_name = move.get("relative_name")
        if not isinstance(relative_name, str) or relative_name != entry.get("relative_name"):
            fail("cleanup intent move binding is invalid")
        if relative_name in seen:
            fail("cleanup intent relative path set is invalid")
        seen.add(relative_name)
        source = move.get("source")
        if not isinstance(source, dict):
            fail("cleanup intent source binding is invalid")
        validate_cleanup_source_binding(target, entry, source)
        tombstone = cleanup_journal_dir(target) / relative_name
        if not cleanup_tombstone_is_allowed(target, tombstone):
            fail("cleanup intent tombstone is outside declared bounds")
        cleanup_graph_map(entry)
    return intent


def write_cleanup_intent_stage(stage: Path, serialized_intent: bytes) -> None:
    if len(serialized_intent) > CLEANUP_INTENT_MAX_BYTES:
        fail("cleanup intent serialized size exceeds bound")
    write_staged_file(
        stage,
        serialized_intent,
        mode=OWNER_FILE_MODE,
        label=CLEANUP_INTENT_NAME,
    )


def publish_cleanup_intent(target: Path, intent: dict[str, Any], serialized_intent: bytes) -> None:
    if path_exists_no_follow(cleanup_intent_path(target)):
        validate_cleanup_intent(target)
        fail("cleanup intent is already pending")
    journal_dir = cleanup_journal_dir(target)
    ensure_private_directory(journal_dir, "cleanup journal directory")
    intent_path = cleanup_intent_path(target)
    stage = intent_path.with_name(f".{intent_path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    published = False
    write_cleanup_intent_stage(stage, serialized_intent)
    try:
        if not rename_no_replace(stage, intent_path, CLEANUP_INTENT_NAME):
            cleanup_lock_stage_file(stage, CLEANUP_INTENT_NAME)
            fail("cleanup intent is already pending")
        published = True
        fsync_directory(journal_dir)
        validate_cleanup_intent(target)
    except BaseException:
        if path_exists_no_follow(stage):
            with contextlib.suppress(BaseException):
                durable_unlink(stage)
        if published and not path_exists_no_follow(cleanup_journal_path(target)):
            with contextlib.suppress(BaseException):
                durable_unlink(intent_path)
        raise


def remove_cleanup_intent_file(target: Path) -> None:
    intent_path = cleanup_intent_path(target)
    if not path_exists_no_follow(intent_path):
        return
    restore_with_retries(
        lambda: durable_unlink(intent_path),
        lambda: verify_file_snapshot(
            intent_path,
            FileSnapshot(data=None, mode=None),
            CLEANUP_INTENT_NAME,
            max_bytes=CLEANUP_INTENT_MAX_BYTES,
        ),
        CLEANUP_INTENT_NAME,
    )


def promote_cleanup_tombstones(
    target: Path,
    paths: list[tuple[Path | None, str, int, int]],
) -> CleanupPromotion:
    recover_cleanup_intent_for_mutation(target)
    present_paths = [
        (path, label, max_file_bytes, max_paths)
        for path, label, max_file_bytes, max_paths in paths
        if path is not None and path_exists_no_follow(path)
    ]
    if not present_paths:
        journal, serialized = build_cleanup_journal_for_entries(target, [])
        intent, serialized_intent = build_cleanup_intent(target, journal, [])
        return CleanupPromotion(
            entries=[],
            journal=journal,
            serialized_journal=serialized,
            intent=intent,
            serialized_intent=serialized_intent,
            moved=[],
            parent_signature=None,
            source_parent_signatures={},
        )
    entries: list[dict[str, Any]] = []
    move_plan: list[tuple[Path, Path]] = []
    moves: list[dict[str, Any]] = []
    for index, (path, label, max_file_bytes, max_paths) in enumerate(present_paths):
        cleanup_operation_kind_for_source(
            target,
            path,
            label=label,
            max_file_bytes=max_file_bytes,
            max_paths=max_paths,
        )
        relative_name = cleanup_tombstone_name(path, index)
        tombstone = cleanup_journal_dir(target) / relative_name
        entry = cleanup_entry_for_tombstone(
            target,
            path,
            relative_name=relative_name,
            label=label,
            max_file_bytes=max_file_bytes,
            max_paths=max_paths,
            require_tombstone_bound=False,
        )
        if entry is not None:
            entries.append(entry)
            move_plan.append((path, tombstone))
            moves.append(
                {
                    "relative_name": relative_name,
                    "source": cleanup_source_binding(
                        target,
                        path,
                        label=label,
                        max_file_bytes=max_file_bytes,
                        max_paths=max_paths,
                    ),
                }
            )
    if len(entries) > CLEANUP_MAX_ENTRIES:
        fail("cleanup journal entry bound exceeded")
    journal, serialized = build_cleanup_journal_for_entries(target, entries)
    parent_signature = directory_object_signature(target, "cleanup journal parent")
    source_parent_signatures = {
        path.parent: directory_object_signature(path.parent, "cleanup source parent")
        for path, _tombstone in move_plan
    }
    cleanup_dir = cleanup_journal_dir(target)
    ensure_private_directory(cleanup_dir, "cleanup journal directory")
    intent, serialized_intent = build_cleanup_intent(
        target,
        journal,
        moves,
        cleanup_parent_binding(target, cleanup_dir),
    )
    moved: list[tuple[Path, Path]] = []
    try:
        publish_cleanup_intent(target, intent, serialized_intent)
        for path, tombstone in move_plan:
            relative_name = tombstone.name
            if path_exists_no_follow(tombstone):
                fail(f"cleanup tombstone already exists: {relative_name}")
            os.replace(path, tombstone)
            fsync_directory(path.parent)
            fsync_directory(cleanup_dir)
            moved.append((path, tombstone))
        return CleanupPromotion(
            entries=entries,
            journal=journal,
            serialized_journal=serialized,
            intent=intent,
            serialized_intent=serialized_intent,
            moved=moved,
            parent_signature=parent_signature,
            source_parent_signatures=source_parent_signatures,
        )
    except BaseException:
        rollback_cleanup_promotion(
            target,
            CleanupPromotion(
                entries=entries,
                journal=journal,
                serialized_journal=serialized,
                intent=intent,
                serialized_intent=serialized_intent,
                moved=moved,
                parent_signature=parent_signature,
                source_parent_signatures=source_parent_signatures,
            ),
        )
        raise


def rollback_cleanup_promotion(target: Path, promotion: CleanupPromotion) -> None:
    cleanup_dir = cleanup_journal_dir(target)
    errors: list[str] = []
    for original, tombstone in reversed(promotion.moved):
        if not path_exists_no_follow(tombstone):
            continue
        try:
            os.replace(tombstone, original)
            fsync_directory(original.parent)
            fsync_directory(cleanup_dir)
        except BaseException as exc:
            errors.append(f"{original.name}: {type(exc).__name__}: {exc}")
    journal_path = cleanup_journal_path(target)
    if path_exists_no_follow(journal_path):
        errors.append("cleanup journal was already published")
    try:
        remove_cleanup_intent_file(target)
    except BaseException as exc:
        errors.append(f"cleanup intent: {type(exc).__name__}: {exc}")
    try:
        if path_exists_no_follow(cleanup_dir) and not any(cleanup_dir.iterdir()):
            durable_rmdir(cleanup_dir)
    except BaseException as exc:
        errors.append(f"cleanup directory: {type(exc).__name__}: {exc}")
    try:
        restore_directory_object_signature(
            target,
            promotion.parent_signature,
            "cleanup journal parent",
        )
    except BaseException as exc:
        errors.append(f"cleanup parent: {type(exc).__name__}: {exc}")
    for parent, signature in promotion.source_parent_signatures.items():
        try:
            restore_directory_object_signature(parent, signature, "cleanup source parent")
        except BaseException as exc:
            errors.append(f"cleanup source parent: {type(exc).__name__}: {exc}")
    if errors:
        fail("cleanup tombstone rollback failed: " + "; ".join(errors))


def cleanup_graph_relative_is_valid(relative_name: str) -> bool:
    if relative_name == ".":
        return True
    relative = Path(relative_name)
    return (
        not relative.is_absolute()
        and relative.as_posix() == relative_name
        and relative_name not in {"", ".."}
        and ".." not in relative.parts
    )


def cleanup_graph_map(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    graph = entry.get("graph")
    if not isinstance(graph, list) or not graph:
        fail("cleanup journal graph is invalid")
    if len(graph) != entry["path_count"]:
        fail("cleanup journal graph path count mismatch")
    seen: dict[str, dict[str, Any]] = {}
    for raw_object in graph:
        if not isinstance(raw_object, dict) or set(raw_object) != {
            "relative",
            "kind",
            "uid",
            "mode",
            "nlink",
            "st_dev",
            "st_ino",
            "size",
            "mtime_ns",
            "sha256",
        }:
            fail("cleanup journal graph entry schema is invalid")
        relative_name = raw_object.get("relative")
        kind = raw_object.get("kind")
        if (
            not isinstance(relative_name, str)
            or not cleanup_graph_relative_is_valid(relative_name)
            or relative_name in seen
            or kind not in {"directory", "file"}
            or not isinstance(raw_object.get("uid"), int)
            or not isinstance(raw_object.get("mode"), int)
            or not isinstance(raw_object.get("nlink"), int)
            or not isinstance(raw_object.get("st_dev"), int)
            or not isinstance(raw_object.get("st_ino"), int)
            or not isinstance(raw_object.get("size"), int)
            or not isinstance(raw_object.get("mtime_ns"), int)
            or not (isinstance(raw_object.get("sha256"), str) or raw_object.get("sha256") is None)
        ):
            fail("cleanup journal graph entry types are invalid")
        if kind == "file":
            if not isinstance(raw_object.get("sha256"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", raw_object["sha256"]
            ):
                fail("cleanup journal graph file digest is invalid")
        elif raw_object.get("sha256") is not None:
            fail("cleanup journal graph directory digest must be null")
        seen[relative_name] = raw_object
    if "." not in seen or seen["."]["kind"] != entry["kind"]:
        fail("cleanup journal graph root is invalid")
    for relative_name, graph_entry in seen.items():
        if relative_name == ".":
            continue
        parent = Path(relative_name).parent.as_posix()
        parent = "." if parent == "." else parent
        if parent not in seen or seen[parent]["kind"] != "directory":
            fail("cleanup journal graph topology is invalid")
        if graph_entry["kind"] == "file" and graph_entry["nlink"] != 1:
            fail("cleanup journal graph file link count is invalid")
    summary = cleanup_graph_summary(list(seen.values()))
    if (
        summary["path_count"] != entry["path_count"]
        or summary["size_bytes"] != entry["size_bytes"]
        or summary["sha256"] != entry["sha256"]
    ):
        fail("cleanup journal graph summary mismatch")
    return seen


def cleanup_object_path(root: Path, relative_name: str) -> Path:
    return root if relative_name == "." else root / relative_name


def current_cleanup_relatives(root: Path, expected_root_kind: str) -> set[str]:
    info = stat_existing(root, "cleanup tombstone root")
    if info is None:
        return set()
    if expected_root_kind == "file":
        if not stat.S_ISREG(info.st_mode):
            fail("cleanup journal tombstone kind mismatch")
        return {"."}
    if not stat.S_ISDIR(info.st_mode):
        fail("cleanup journal tombstone kind mismatch")
    relatives = {"."}
    for child in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relatives.add(child.relative_to(root).as_posix())
    return relatives


def cleanup_direct_child_names(relatives: set[str], relative_name: str) -> set[str]:
    names: set[str] = set()
    for candidate in relatives:
        if candidate == ".":
            continue
        parent = Path(candidate).parent.as_posix()
        parent = "." if parent == "." else parent
        if parent == relative_name:
            names.add(Path(candidate).name)
    return names


def cleanup_object_matches_record(
    path: Path,
    record: dict[str, Any],
    label: str,
    *,
    max_file_bytes: int,
    full_directory_metadata: bool,
) -> None:
    info = stat_existing(path, label)
    if info is None:
        fail(f"cleanup tombstone object is missing: {record['relative']}")
    expected_kind = record["kind"]
    if expected_kind == "directory":
        if not stat.S_ISDIR(info.st_mode):
            fail("cleanup tombstone object kind mismatch")
        if (
            info.st_uid != record["uid"]
            or stat.S_IMODE(info.st_mode) != record["mode"]
            or info.st_dev != record["st_dev"]
            or info.st_ino != record["st_ino"]
        ):
            fail("cleanup tombstone directory stable identity mismatch")
        if full_directory_metadata and (
            info.st_nlink != record["nlink"]
            or info.st_size != record["size"]
            or info.st_mtime_ns != record["mtime_ns"]
        ):
            fail("cleanup tombstone directory metadata mismatch")
        return
    if not stat.S_ISREG(info.st_mode):
        fail("cleanup tombstone object kind mismatch")
    if (
        info.st_uid != record["uid"]
        or stat.S_IMODE(info.st_mode) != record["mode"]
        or info.st_nlink != record["nlink"]
        or info.st_dev != record["st_dev"]
        or info.st_ino != record["st_ino"]
        or info.st_size != record["size"]
        or info.st_mtime_ns != record["mtime_ns"]
    ):
        fail("cleanup tombstone file identity mismatch")
    if file_sha256(path, label=label, max_bytes=max_file_bytes) != record["sha256"]:
        fail("cleanup tombstone file digest mismatch")


def validate_cleanup_graph_state_at_root(
    root: Path,
    entry: dict[str, Any],
    graph: dict[str, dict[str, Any]],
    *,
    require_full: bool,
) -> bool:
    current_relatives = current_cleanup_relatives(root, str(entry["kind"]))
    if not current_relatives:
        return False
    expected_relatives = set(graph)
    unknown = current_relatives - expected_relatives
    if unknown:
        fail("cleanup journal tombstone contains unknown children")
    if require_full and current_relatives != expected_relatives:
        fail("cleanup journal tombstone graph is incomplete before drain")
    for relative_name in current_relatives:
        record = graph[relative_name]
        if record["kind"] == "directory":
            actual_children = cleanup_direct_child_names(current_relatives, relative_name)
            expected_children = cleanup_direct_child_names(expected_relatives, relative_name)
            if require_full:
                visible_expected_children = expected_children
            else:
                visible_expected_children = cleanup_direct_child_names(
                    current_relatives, relative_name
                )
            if actual_children != visible_expected_children:
                fail("cleanup journal directory child set mismatch")
        missing_descendant = any(
            candidate != relative_name
            and candidate.startswith("" if relative_name == "." else f"{relative_name}/")
            and candidate not in current_relatives
            for candidate in expected_relatives
        )
        cleanup_object_matches_record(
            cleanup_object_path(root, relative_name),
            record,
            str(entry["label"]),
            max_file_bytes=int(entry["max_file_bytes"]),
            full_directory_metadata=require_full or not missing_descendant,
        )
    return current_relatives == expected_relatives


def validate_cleanup_graph_state(
    target: Path,
    entry: dict[str, Any],
    graph: dict[str, dict[str, Any]],
    *,
    require_full: bool,
) -> bool:
    root = cleanup_journal_dir(target) / str(entry["relative_name"])
    return validate_cleanup_graph_state_at_root(root, entry, graph, require_full=require_full)


def read_final_cleanup_journal_json(target: Path) -> dict[str, Any]:
    journal_path = cleanup_journal_path(target)
    info = stat_existing(journal_path, CLEANUP_JOURNAL_NAME)
    if info is None:
        fail("cleanup journal is missing")
    if not stat.S_ISREG(info.st_mode):
        fail("cleanup journal must be a regular file")
    if not is_current_owner(info):
        fail("cleanup journal must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail("cleanup journal must be private with mode 0600")
    if info.st_nlink != 1:
        fail("cleanup journal must not be a hardlink")
    if info.st_size > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal is too large")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(journal_path, flags)
    except OSError as exc:
        fail(f"cleanup journal could not be opened safely: {exc}")
    try:
        opened = os.fstat(fd)
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            fail("cleanup journal changed while opening")
        if (
            not stat.S_ISREG(opened.st_mode)
            or not is_current_owner(opened)
            or stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE
            or opened.st_nlink != 1
            or opened.st_size > CLEANUP_JOURNAL_MAX_BYTES
        ):
            fail("cleanup journal metadata is invalid")
        data = os.read(fd, CLEANUP_JOURNAL_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal is too large")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cleanup journal is invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail("cleanup journal must contain a JSON object")
    return value


def validate_cleanup_journal(target: Path) -> dict[str, Any] | None:
    journal_dir = cleanup_journal_dir(target)
    dir_info = stat_existing(journal_dir, "cleanup journal directory")
    if dir_info is None:
        return None
    if not stat.S_ISDIR(dir_info.st_mode):
        fail("cleanup journal directory must be a directory")
    if not is_current_owner(dir_info) or stat.S_IMODE(dir_info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("cleanup journal directory must be private and owned by the current user")
    entries = sorted(child.name for child in journal_dir.iterdir())
    if not entries:
        fail("cleanup journal directory is empty")
    if CLEANUP_JOURNAL_NAME not in entries:
        fail("cleanup journal directory contains unjournaled tombstones")
    if entries.count(CLEANUP_JOURNAL_NAME) != 1:
        fail("cleanup journal directory contains unknown entries")
    journal = read_final_cleanup_journal_json(target)
    expected_keys = {"schema_version", "product_name", "canonical_target", "entries"}
    if set(journal) != expected_keys:
        fail("cleanup journal schema is invalid")
    if (
        journal.get("schema_version") != CLEANUP_SCHEMA
        or journal.get("product_name") != PRODUCT_NAME
    ):
        fail("cleanup journal owner is invalid")
    if journal.get("canonical_target") != str(validate_target(target, create=False)):
        fail("cleanup journal target binding is invalid")
    raw_entries = journal.get("entries")
    if (
        not isinstance(raw_entries, list)
        or not raw_entries
        or len(raw_entries) > CLEANUP_MAX_ENTRIES
    ):
        fail("cleanup journal entries are invalid")
    seen: set[str] = set()
    for entry in raw_entries:
        if not isinstance(entry, dict) or set(entry) != {
            "relative_name",
            "label",
            "kind",
            "uid",
            "mode",
            "nlink",
            "st_dev",
            "st_ino",
            "size",
            "mtime_ns",
            "max_file_bytes",
            "max_paths",
            "path_count",
            "size_bytes",
            "sha256",
            "graph",
        }:
            fail("cleanup journal entry schema is invalid")
        relative_name = entry.get("relative_name")
        raw_label = entry.get("label")
        kind = entry.get("kind")
        max_file_bytes = entry.get("max_file_bytes")
        max_paths = entry.get("max_paths")
        if (
            not isinstance(relative_name, str)
            or not isinstance(raw_label, str)
            or kind not in {"directory", "file"}
            or not isinstance(entry.get("uid"), int)
            or not isinstance(entry.get("mode"), int)
            or not isinstance(entry.get("nlink"), int)
            or not isinstance(entry.get("st_dev"), int)
            or not isinstance(entry.get("st_ino"), int)
            or not isinstance(entry.get("size"), int)
            or not isinstance(entry.get("mtime_ns"), int)
            or not isinstance(max_file_bytes, int)
            or not isinstance(max_paths, int)
            or not isinstance(entry.get("path_count"), int)
            or not isinstance(entry.get("size_bytes"), int)
            or not (isinstance(entry.get("sha256"), str) or entry.get("sha256") is None)
        ):
            fail("cleanup journal entry types are invalid")
        relative = Path(relative_name)
        if (
            relative.is_absolute()
            or relative.name != relative_name
            or relative_name in {CLEANUP_JOURNAL_NAME, "", ".", ".."}
            or ".." in relative.parts
            or relative_name in seen
        ):
            fail("cleanup journal relative path set is invalid")
        seen.add(relative_name)
        path = journal_dir / relative_name
        if not cleanup_tombstone_is_allowed(target, path):
            fail("cleanup journal path is outside declared bounds")
        graph = cleanup_graph_map(entry)
        validate_cleanup_graph_state(target, entry, graph, require_full=False)
    unknown_entries = set(entries) - {CLEANUP_JOURNAL_NAME} - seen
    if unknown_entries:
        fail("cleanup journal directory contains unknown entries")
    return journal


def read_cleanup_journal_with_publication_alias(
    target: Path, info: os.stat_result
) -> dict[str, Any]:
    journal_path = cleanup_journal_path(target)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(journal_path, flags)
    except OSError as exc:
        fail(f"cleanup journal could not be opened safely: {exc}")
    try:
        opened = os.fstat(fd)
        if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
            fail("cleanup journal changed while opening publication alias")
        if (
            not stat.S_ISREG(opened.st_mode)
            or not is_current_owner(opened)
            or stat.S_IMODE(opened.st_mode) != OWNER_FILE_MODE
            or opened.st_nlink != 2
            or opened.st_size > CLEANUP_JOURNAL_MAX_BYTES
        ):
            fail("cleanup journal publication alias metadata is invalid")
        data = os.read(fd, CLEANUP_JOURNAL_MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal is too large")
    try:
        journal = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cleanup journal is invalid JSON: {exc}")
    if not isinstance(journal, dict):
        fail("cleanup journal must contain a JSON object")
    if (
        journal.get("schema_version") != CLEANUP_SCHEMA
        or journal.get("product_name") != PRODUCT_NAME
    ):
        fail("cleanup journal owner is invalid")
    if journal.get("canonical_target") != str(validate_target(target, create=False)):
        fail("cleanup journal target binding is invalid")
    raw_entries = journal.get("entries")
    if (
        not isinstance(raw_entries, list)
        or not raw_entries
        or len(raw_entries) > CLEANUP_MAX_ENTRIES
    ):
        fail("cleanup journal entries are invalid")
    seen: set[str] = set()
    for entry in raw_entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("relative_name"), str):
            fail("cleanup journal entry schema is invalid")
        relative_name = str(entry["relative_name"])
        relative = Path(relative_name)
        if (
            relative.is_absolute()
            or relative.name != relative_name
            or relative_name in {CLEANUP_JOURNAL_NAME, "", ".", ".."}
            or ".." in relative.parts
            or relative_name in seen
            or not cleanup_tombstone_is_allowed(target, cleanup_journal_dir(target) / relative_name)
        ):
            fail("cleanup journal relative path set is invalid")
        seen.add(relative_name)
    return journal


def recover_cleanup_intent_for_mutation(target: Path) -> None:
    intent = validate_cleanup_intent(target)
    if intent is None:
        return
    journal = intent["journal"]
    moves = intent["moves"]
    journal_path = cleanup_journal_path(target)
    if path_exists_no_follow(journal_path):
        final_journal = read_final_cleanup_journal_json(target)
        if final_journal != journal:
            fail("cleanup intent final journal binding is invalid")
        remove_cleanup_intent_file(target)
        validate_cleanup_journal(target)
        return
    cleanup_dir = cleanup_journal_dir(target)
    entries = journal["entries"]
    for entry, move in zip(entries, moves):
        relative_name = str(entry["relative_name"])
        tombstone = cleanup_dir / relative_name
        source = validate_cleanup_source_binding(target, entry, move["source"])
        graph = cleanup_graph_map(entry)
        source_exists = path_exists_no_follow(source)
        tombstone_exists = path_exists_no_follow(tombstone)
        if source_exists and tombstone_exists:
            fail("cleanup intent source and tombstone are both present")
        if not source_exists and not tombstone_exists:
            fail("cleanup intent source and tombstone are both absent")
        if source_exists:
            validate_cleanup_graph_state_at_root(source, entry, graph, require_full=True)
            if path_exists_no_follow(tombstone):
                fail(f"cleanup tombstone already exists: {relative_name}")
            os.replace(source, tombstone)
            fsync_directory(source.parent)
            fsync_directory(cleanup_dir)
        else:
            validate_cleanup_graph_state_at_root(tombstone, entry, graph, require_full=False)
    publish_result = publish_cleanup_journal(
        target,
        entries,
        journal,
        serialized_cleanup_journal_bytes(journal),
        validate_final=False,
    )
    if not publish_result.published and not path_exists_no_follow(journal_path):
        fail("cleanup intent recovery did not publish final journal")
    remove_cleanup_intent_file(target)
    validate_cleanup_journal(target)


def recover_cleanup_journal_publication_alias_for_mutation(target: Path) -> None:
    journal_dir = cleanup_journal_dir(target)
    journal_path = cleanup_journal_path(target)
    info = stat_existing(journal_path, CLEANUP_JOURNAL_NAME)
    if info is None:
        return
    if not stat.S_ISREG(info.st_mode):
        fail("cleanup journal must be a regular file")
    if not is_current_owner(info) or stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail("cleanup journal must be owner-only")
    if info.st_nlink == 1:
        return
    if info.st_nlink != 2:
        fail("cleanup journal publication alias count is invalid")
    journal = read_cleanup_journal_with_publication_alias(target, info)
    declared_names = {
        str(entry["relative_name"])
        for entry in journal["entries"]
        if isinstance(entry, dict) and isinstance(entry.get("relative_name"), str)
    }
    alias_pattern = cleanup_journal_stage_alias_pattern(journal_path)
    aliases: list[Path] = []
    for child in journal_dir.iterdir():
        if child.name == CLEANUP_JOURNAL_NAME or child.name in declared_names:
            continue
        child_info = stat_existing(child, "cleanup journal publication alias")
        if child_info is None:
            continue
        if not alias_pattern.fullmatch(child.name):
            fail("cleanup journal directory contains unknown entries")
        if child_info.st_dev == info.st_dev and child_info.st_ino == info.st_ino:
            aliases.append(child)
        else:
            fail("cleanup journal publication alias identity mismatch")
    if len(aliases) != 1:
        fail("cleanup journal publication alias set is invalid")
    durable_unlink(aliases[0])
    final_info = stat_existing(journal_path, CLEANUP_JOURNAL_NAME)
    if final_info is None:
        fail("cleanup journal disappeared during alias recovery")
    if (
        final_info.st_dev != info.st_dev
        or final_info.st_ino != info.st_ino
        or final_info.st_nlink != 1
        or not stat.S_ISREG(final_info.st_mode)
        or not is_current_owner(final_info)
        or stat.S_IMODE(final_info.st_mode) != OWNER_FILE_MODE
    ):
        fail("cleanup journal alias recovery postcondition failed")


def cleanup_pending_metadata(target: Path) -> list[dict[str, Any]]:
    journal = validate_cleanup_journal(target)
    if journal is None:
        return []
    return [
        {
            "label": entry["label"],
            "kind": entry["kind"],
            "path_count": entry["path_count"],
            "size_bytes": entry["size_bytes"],
            "sha256": entry["sha256"],
        }
        for entry in journal["entries"]
    ]


def write_cleanup_journal_stage(stage: Path, serialized_journal: bytes) -> None:
    if len(serialized_journal) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal serialized size exceeds bound")
    write_staged_file(
        stage,
        serialized_journal,
        mode=OWNER_FILE_MODE,
        label=CLEANUP_JOURNAL_NAME,
    )


def publish_cleanup_journal(
    target: Path,
    entries: list[dict[str, Any]],
    journal: dict[str, Any] | None = None,
    serialized_journal: bytes | None = None,
    *,
    validate_final: bool = True,
) -> CleanupJournalPublishResult:
    if not entries:
        return CleanupJournalPublishResult(published=False)
    if path_exists_no_follow(cleanup_journal_path(target)):
        validate_cleanup_journal(target)
        fail("cleanup journal is already pending")
    journal_dir = cleanup_journal_dir(target)
    ensure_private_directory(journal_dir, "cleanup journal directory")
    if journal is None or serialized_journal is None:
        journal, serialized_journal = build_cleanup_journal_for_entries(target, entries)
    else:
        rebuilt_journal, rebuilt_serialized = build_cleanup_journal_for_entries(target, entries)
        if rebuilt_journal != journal or rebuilt_serialized != serialized_journal:
            fail("cleanup journal serialized content changed before publication")
    journal_path = cleanup_journal_path(target)
    stage = journal_path.with_name(f".{journal_path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    published = False
    write_cleanup_journal_stage(stage, serialized_journal)
    try:
        if not rename_no_replace(stage, journal_path, CLEANUP_JOURNAL_NAME):
            cleanup_lock_stage_file(stage, CLEANUP_JOURNAL_NAME)
            fail("cleanup journal is already pending")
        published = True
        fsync_directory(journal_dir)
    except BaseException:
        if path_exists_no_follow(stage):
            with contextlib.suppress(BaseException):
                durable_unlink(stage)
        if published:
            if validate_final:
                validate_cleanup_journal(target)
            return CleanupJournalPublishResult(published=True, cleanup_pending=True)
        raise
    if validate_final:
        try:
            validate_cleanup_journal(target)
        except BaseException:
            return CleanupJournalPublishResult(published=True, cleanup_pending=True)
    return CleanupJournalPublishResult(published=True)


def republish_cleanup_journal(target: Path, journal: dict[str, Any]) -> None:
    journal_dir = cleanup_journal_dir(target)
    ensure_private_directory(journal_dir, "cleanup journal directory")
    journal_path = cleanup_journal_path(target)
    stage = journal_path.with_name(f".{journal_path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    serialized_journal = serialized_cleanup_journal_bytes(journal)
    write_cleanup_journal_stage(stage, serialized_journal)
    try:
        if not rename_no_replace(stage, journal_path, CLEANUP_JOURNAL_NAME):
            cleanup_lock_stage_file(stage, CLEANUP_JOURNAL_NAME)
            fail("cleanup journal recovery found an existing journal")
        fsync_directory(journal_dir)
    except BaseException:
        if path_exists_no_follow(stage):
            with contextlib.suppress(BaseException):
                durable_unlink(stage)
        raise
    validate_cleanup_journal(target)


def remove_cleanup_journal_file(target: Path, journal: dict[str, Any]) -> None:
    journal_path = cleanup_journal_path(target)
    removed = False
    try:
        journal_path.unlink()
        removed = True
        fsync_directory(journal_path.parent)
    except BaseException:
        if removed and not path_exists_no_follow(journal_path):
            republish_cleanup_journal(target, journal)
        raise


def remove_cleanup_journal_dir(target: Path, journal: dict[str, Any]) -> None:
    journal_dir = cleanup_journal_dir(target)
    removed = False
    try:
        journal_dir.rmdir()
        removed = True
        fsync_directory(target)
    except BaseException:
        if removed and not path_exists_no_follow(journal_dir):
            republish_cleanup_journal(target, journal)
        raise


def drain_cleanup_tombstone(target: Path, entry: dict[str, Any]) -> None:
    graph = cleanup_graph_map(entry)
    root = cleanup_journal_dir(target) / str(entry["relative_name"])
    if not path_exists_no_follow(root):
        return
    full_graph_present = validate_cleanup_graph_state(target, entry, graph, require_full=False)
    if full_graph_present:
        validate_cleanup_graph_state(target, entry, graph, require_full=True)
    for relative_name, record in sorted(
        graph.items(),
        key=lambda item: (item[0].count("/"), item[0] != "."),
        reverse=True,
    ):
        path = cleanup_object_path(root, relative_name)
        if not path_exists_no_follow(path):
            continue
        current_relatives = current_cleanup_relatives(root, str(entry["kind"]))
        if relative_name not in current_relatives:
            continue
        unknown = current_relatives - set(graph)
        if unknown:
            fail("cleanup journal tombstone contains unknown children")
        if record["kind"] == "directory":
            actual_children = cleanup_direct_child_names(current_relatives, relative_name)
            if actual_children:
                fail("cleanup journal directory still has declared children before rmdir")
            cleanup_object_matches_record(
                path,
                record,
                str(entry["label"]),
                max_file_bytes=int(entry["max_file_bytes"]),
                full_directory_metadata=False,
            )
            durable_rmdir(path)
        else:
            cleanup_object_matches_record(
                path,
                record,
                str(entry["label"]),
                max_file_bytes=int(entry["max_file_bytes"]),
                full_directory_metadata=True,
            )
            durable_unlink(path)
        if path_exists_no_follow(cleanup_journal_dir(target)):
            fsync_directory(cleanup_journal_dir(target))


def cleanup_journal_once(target: Path) -> None:
    journal = validate_cleanup_journal(target)
    if journal is None:
        return
    for entry in journal["entries"]:
        validate_cleanup_journal(target)
        drain_cleanup_tombstone(target, entry)
    journal = validate_cleanup_journal(target)
    if journal is None:
        return
    remove_cleanup_journal_file(target, journal)
    remove_cleanup_journal_dir(target, journal)


def drain_cleanup_journal(target: Path) -> bool:
    recover_cleanup_intent_for_mutation(target)
    recover_cleanup_journal_publication_alias_for_mutation(target)
    if validate_cleanup_journal(target) is None:
        return False
    restore_with_retries(
        lambda: cleanup_journal_once(target),
        lambda: (
            None
            if validate_cleanup_journal(target) is None
            else fail("cleanup journal drain did not finish")
        ),
        "cleanup journal drain",
    )
    return True


def finish_cleanup_journal(
    target: Path,
    paths: list[tuple[Path | None, str, int, int]],
) -> bool:
    promotion = promote_cleanup_tombstones(target, paths)
    if not promotion.entries:
        return False
    try:
        publish_result = publish_cleanup_journal(
            target,
            promotion.entries,
            promotion.journal,
            promotion.serialized_journal,
            validate_final=False,
        )
        if not publish_result.published:
            return False
        try:
            remove_cleanup_intent_file(target)
            validate_cleanup_journal(target)
        except BaseException:
            return True
        if publish_result.cleanup_pending:
            return True
    except BaseException:
        rollback_cleanup_promotion(target, promotion)
        raise
    try:
        if drain_cleanup_journal(target):
            return False
    except BaseException:
        validate_cleanup_journal(target)
        return True
    return False


def require_tree_entry_identity(path: Path, entry: TreeEntry, label: str) -> os.stat_result:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} rollback postcondition failed: missing original object")
    assert info is not None
    if entry.kind == "dir":
        if not stat.S_ISDIR(info.st_mode):
            fail(f"{label} rollback postcondition failed: not a directory")
    elif entry.kind == "file":
        if not stat.S_ISREG(info.st_mode):
            fail(f"{label} rollback postcondition failed: not a regular file")
        if info.st_nlink != 1:
            fail(f"{label} rollback postcondition failed: hardlink count changed")
    else:
        fail(f"{label} rollback postcondition failed: unknown tree entry kind")
    if info.st_dev != entry.st_dev or info.st_ino != entry.st_ino:
        fail(f"{label} rollback postcondition failed: object identity mismatch")
    return info


def write_all(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            fail("short write while restoring tree object")
        remaining = remaining[written:]


def restore_file_tree_entry(path: Path, entry: TreeEntry, label: str) -> None:
    if entry.data is None:
        fail(f"{label} rollback snapshot is missing file data")
    info = require_tree_entry_identity(path, entry, label)
    if not (stat.S_IMODE(info.st_mode) & 0o200):
        path.chmod(stat.S_IMODE(info.st_mode) | 0o200)
    flags = os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} rollback file restore could not open original object: {exc}")
    try:
        opened = os.fstat(fd)
        if opened.st_dev != entry.st_dev or opened.st_ino != entry.st_ino:
            fail(f"{label} rollback postcondition failed: object identity mismatch")
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        write_all(fd, entry.data)
        os.fchmod(fd, entry.mode)
        os.fsync(fd)
    finally:
        os.close(fd)
    current = require_tree_entry_identity(path, entry, label)
    os.utime(path, ns=(current.st_atime_ns, entry.mtime_ns))
    fsync_directory(path.parent)


def restore_directory_tree_entry(path: Path, entry: TreeEntry, label: str) -> None:
    info = require_tree_entry_identity(path, entry, label)
    if stat.S_IMODE(info.st_mode) != entry.mode:
        path.chmod(entry.mode)
    current = require_tree_entry_identity(path, entry, label)
    os.utime(path, ns=(current.st_atime_ns, entry.mtime_ns))
    fsync_directory(path)
    if path.parent.exists():
        fsync_directory(path.parent)


def restore_tree_snapshot_once(
    root: Path, snapshot: TreeSnapshot, label: str, *, max_file_bytes: int, max_paths: int
) -> None:
    if snapshot.entries is None:
        remove_tree_once(root, label, max_file_bytes=max_file_bytes, max_paths=max_paths)
        return
    current = snapshot_tree(root, label, max_file_bytes=max_file_bytes, max_paths=max_paths)
    current_entries = current.entries or {}
    expected_entries = snapshot.entries
    for relative, entry in sorted(
        (
            (relative, entry)
            for relative, entry in current_entries.items()
            if relative not in expected_entries and relative != "."
        ),
        key=lambda item: item[0].count("/"),
        reverse=True,
    ):
        path = root / relative
        if entry.kind == "dir":
            durable_rmdir(path)
        else:
            durable_unlink(path)
    for relative, entry in sorted(
        ((relative, entry) for relative, entry in expected_entries.items() if entry.kind == "dir"),
        key=lambda item: item[0].count("/"),
    ):
        path = root if relative == "." else root / relative
        require_tree_entry_identity(path, entry, f"{label} directory {relative}")
    for relative, entry in sorted(
        ((relative, entry) for relative, entry in expected_entries.items() if entry.kind == "file"),
        key=lambda item: item[0].count("/"),
    ):
        restore_file_tree_entry(
            root / relative,
            entry,
            f"{label} file {relative}",
        )
    for relative, entry in sorted(
        ((relative, entry) for relative, entry in expected_entries.items() if entry.kind == "dir"),
        key=lambda item: item[0].count("/"),
        reverse=True,
    ):
        path = root if relative == "." else root / relative
        restore_directory_tree_entry(path, entry, f"{label} directory {relative}")


def restore_tree_snapshot(
    root: Path, snapshot: TreeSnapshot, label: str, *, max_file_bytes: int, max_paths: int
) -> None:
    restore_with_retries(
        lambda: restore_tree_snapshot_once(
            root,
            snapshot,
            label,
            max_file_bytes=max_file_bytes,
            max_paths=max_paths,
        ),
        lambda: verify_tree_snapshot(
            root,
            snapshot,
            label,
            max_file_bytes=max_file_bytes,
            max_paths=max_paths,
        ),
        label,
    )


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
        digest.update(
            f"F {relative} {stat.S_IMODE(info.st_mode):04o} {info.st_size}\n".encode("utf-8")
        )
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
    for path in sorted(
        skill_root.rglob("*"), key=lambda item: item.relative_to(skill_root).as_posix()
    ):
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


def desired_files(
    target: Path, setup: dict[str, Any], profile_data: dict[str, Any]
) -> dict[str, bytes]:
    existing_config = read_existing_file(
        target / "config.toml", max_bytes=MANAGED_MAX_BYTES, label="config.toml"
    )
    existing_tui = read_existing_file(
        target / "tui.toml", max_bytes=MANAGED_MAX_BYTES, label="tui.toml"
    )
    existing_agents = read_existing_file(
        target / "AGENTS.md", max_bytes=MANAGED_MAX_BYTES, label="AGENTS.md"
    )
    files = {
        "config.toml": merge_managed_block(
            "config.toml", existing_config, render_config(target, setup, profile_data)
        ),
        "tui.toml": merge_managed_block("tui.toml", existing_tui, render_tui()),
        "AGENTS.md": merge_managed_block(
            "AGENTS.md", existing_agents, render_agents_block(setup, profile_data)
        ),
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


def _status_payload_locked(target: Path) -> dict[str, Any]:
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
            "cleanup_pending": False,
            "cleanup_pending_metadata": [],
            "auth_state": {
                "state": "absent",
                "path": str(target / "credentials"),
                "scope": "target KIMI_CODE_HOME",
            },
        }
    require_owner_private_directory(target, "target")
    stamp = read_stamp(target)
    if stamp is None:
        cleanup_metadata = cleanup_pending_metadata(target)
        return {
            "state": "unmanaged",
            "managed": False,
            "launch_allowed": False,
            "canonical_target": str(canonical),
            "content_setup_id": None,
            "permission_profile_id": None,
            "legacy_setup_id": None,
            "drift": [],
            "cleanup_pending": bool(cleanup_metadata),
            "cleanup_pending_metadata": cleanup_metadata,
            "auth_state": auth_state(target),
        }
    descriptor = stamp_descriptor(stamp)
    drift = drift_for_stamp(target, stamp)
    current = stamp_is_current(stamp)
    software = _software_status_payload_locked(canonical)
    cleanup_metadata = cleanup_pending_metadata(target)
    return {
        "state": "managed" if current else "legacy-managed",
        "managed": True,
        "launch_allowed": bool(
            current and not drift and software["current"] and not cleanup_metadata
        ),
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
        "cleanup_pending": bool(cleanup_metadata),
        "cleanup_pending_metadata": cleanup_metadata,
        "auth_state": auth_state(target),
    }


def status_payload(target: Path) -> dict[str, Any]:
    require_supported_product_host()
    return run_under_readonly_external_lifecycle(target, _status_payload_locked)


def stamp_managed_paths(stamp: dict[str, Any] | None) -> tuple[str, ...]:
    if stamp is None:
        return ()
    managed = stamp.get("managed_files")
    if not isinstance(managed, dict):
        return ()
    return tuple(str(path) for path in managed)


def snapshot_files(target: Path, extra_paths: tuple[str, ...] = ()) -> dict[str, FileSnapshot]:
    snapshot: dict[str, FileSnapshot] = {}
    for relative in (*content_managed_paths(), *extra_paths, STAMP_NAME):
        snapshot[relative] = snapshot_replace_destination(
            safe_target_path(target, relative),
            relative,
            max_bytes=MANAGED_MAX_BYTES,
        )
    return snapshot


def verify_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    for relative, data in snapshot.items():
        path = safe_target_path(target, relative)
        verify_file_snapshot(path, data, relative, max_bytes=MANAGED_MAX_BYTES)


def restore_snapshot_once(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    for relative, data in snapshot.items():
        restore_file_snapshot(
            safe_target_path(target, relative),
            data,
            target,
            relative,
            max_bytes=MANAGED_MAX_BYTES,
        )
    prune_empty_managed_dirs(target, tuple(snapshot))


def restore_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    restore_with_retries(
        lambda: restore_snapshot_once(target, snapshot),
        lambda: verify_snapshot(target, snapshot),
        "managed setup snapshot",
    )


def removed_managed_block_bytes(target: Path, relative: str) -> tuple[bool, bytes | None]:
    data = read_existing_file(
        safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
    )
    if data is None:
        return False, None
    text = data.decode("utf-8")
    block = extract_managed_block(relative, text)
    if block is None:
        return False, data
    updated = text.replace(block, "")
    if updated.strip():
        return True, updated.encode("utf-8")
    return True, None


def apply_setup_file_transaction(
    target: Path,
    files: dict[str, bytes],
    desired_stamp: dict[str, Any],
    stale_paths: tuple[str, ...],
) -> FileObjectTransaction:
    file_transaction = FileObjectTransaction(target)
    for relative in stale_paths:
        path = safe_target_path(target, relative)
        if relative in MERGED_MARKER_PATHS:
            changed, updated = removed_managed_block_bytes(target, relative)
            if not changed:
                continue
            if updated is None:
                file_transaction.stage_remove(path, label=relative)
            else:
                file_transaction.stage_write(path, updated, label=relative)
        else:
            file_transaction.stage_remove(path, label=relative)
    for relative, data in files.items():
        file_transaction.stage_write(safe_target_path(target, relative), data, label=relative)
    file_transaction.stage_write(
        stamp_path(target),
        canonical_json(desired_stamp),
        label=STAMP_NAME,
        max_bytes=METADATA_MAX_BYTES,
    )
    try:
        file_transaction.apply_once()
    except BaseException:
        file_transaction.rollback()
        raise
    return file_transaction


def require_backup_pool_if_present(pool: Path) -> bool:
    info = stat_existing(pool, "backup pool")
    if info is None:
        return False
    if not stat.S_ISDIR(info.st_mode):
        fail("backup pool must be a directory")
    if not is_current_owner(info):
        fail("backup pool must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail("backup pool must be private with mode 0700")
    return True


def choose_backup_slot(pool: Path) -> int:
    if not require_backup_pool_if_present(pool):
        return 0
    for slot in range(10):
        if not path_exists_no_follow(pool / str(slot)):
            return slot
    return min(range(10), key=lambda item: (pool / str(item)).lstat().st_mtime_ns)


def ensure_private_directory(
    path: Path, label: str, *, transaction: DirectoryTransaction | None = None
) -> None:
    info = stat_existing(path, label)
    if info is None:
        require_owner_private_directory(path.parent, f"{label} parent")
        path.mkdir(mode=OWNER_DIRECTORY_MODE)
        path.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(path.parent)
        if transaction is not None:
            transaction.created.append(path)
        return
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must be private with mode 0700")


def backup_entry(data: bytes | None) -> dict[str, Any]:
    if data is None:
        return {
            "present": False,
            "size_bytes": 0,
            "sha256": None,
            "data_base64": None,
        }
    return {
        "present": True,
        "size_bytes": len(data),
        "sha256": sha256_bytes(data),
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def backup_path_set(stamp: dict[str, Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*content_managed_paths(), *stamp_managed_paths(stamp), STAMP_NAME)))


def validate_backup_restored_stamp(target: Path, data: bytes | None) -> dict[str, Any]:
    if data is None:
        fail("backup setup stamp entry must be present")
    try:
        stamp = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"backup setup stamp entry is invalid JSON: {exc}")
    if not isinstance(stamp, dict):
        fail("backup setup stamp entry must contain a JSON object")
    if stamp.get("product_name") != PRODUCT_NAME:
        fail("backup setup stamp belongs to another product")
    if stamp.get("canonical_target") != str(validate_target(target, create=False)):
        fail("backup setup stamp is bound to a different canonical target")
    managed = stamp.get("managed_files")
    if not isinstance(managed, dict):
        fail("backup setup stamp managed_files is invalid")
    for relative, digest in managed.items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            fail("backup setup stamp managed file digest is invalid")
        safe_target_path(target, relative)
    return stamp


def backup_entry_data(relative: str, entry: Any) -> bytes | None:
    if not isinstance(entry, dict):
        fail("backup file entry is invalid")
    exact_keys(
        entry, {"present", "size_bytes", "sha256", "data_base64"}, f"backup file entry {relative}"
    )
    present = entry.get("present")
    size_bytes = entry.get("size_bytes")
    digest = entry.get("sha256")
    encoded = entry.get("data_base64")
    if present is False:
        if size_bytes != 0 or digest is not None or encoded is not None:
            fail("absent backup file entry is invalid")
        return None
    if present is not True:
        fail("backup file entry present flag is invalid")
    if not isinstance(size_bytes, int) or size_bytes < 0 or size_bytes > MANAGED_MAX_BYTES:
        fail("backup file entry size is invalid")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail("backup file entry sha256 is invalid")
    if not isinstance(encoded, str):
        fail("backup file payload is invalid")
    try:
        data = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, ValueError):
        fail("backup file payload is invalid base64")
    if len(data) != size_bytes:
        fail("backup file payload size mismatch")
    if sha256_bytes(data) != digest:
        fail("backup file payload sha256 mismatch")
    return data


def validate_backup_envelope(
    target: Path, slot: int, envelope: dict[str, Any]
) -> dict[str, bytes | None]:
    exact_keys(
        envelope,
        {
            "schema_version",
            "product_name",
            "build_version",
            "slot",
            "canonical_target",
            "source",
            "created_at",
            "managed_paths",
            "files",
        },
        BACKUP_NAME,
    )
    if envelope.get("schema_version") != BACKUP_SCHEMA:
        fail("backup schema is unsupported")
    if envelope.get("product_name") != PRODUCT_NAME:
        fail("backup belongs to another product")
    if envelope.get("slot") != slot:
        fail("backup slot binding is invalid")
    if envelope.get("canonical_target") != str(validate_target(target, create=False)):
        fail("backup is bound to a different canonical target")
    if not isinstance(envelope.get("build_version"), str):
        fail("backup build version is invalid")
    if not isinstance(envelope.get("created_at"), int):
        fail("backup created_at is invalid")
    source = exact_keys(
        envelope.get("source"),
        {
            "schema_version",
            "content_setup_id",
            "permission_profile_id",
            "legacy_setup_id",
            "legacy",
        },
        "backup source",
    )
    if not isinstance(source.get("legacy"), bool):
        fail("backup source legacy flag is invalid")
    managed_paths = envelope.get("managed_paths")
    if not isinstance(managed_paths, list) or not managed_paths:
        fail("backup managed_paths is invalid")
    normalized_paths: list[str] = []
    for relative in managed_paths:
        if not isinstance(relative, str):
            fail("backup managed path is invalid")
        safe_target_path(target, relative)
        normalized_paths.append(relative)
    if len(set(normalized_paths)) != len(normalized_paths):
        fail("backup managed_paths contains duplicates")
    if STAMP_NAME not in normalized_paths:
        fail("backup managed_paths must include setup stamp")
    files = envelope.get("files")
    if not isinstance(files, dict):
        fail("backup files are invalid")
    if set(files) != set(normalized_paths):
        fail("backup files path set is invalid")
    decoded: dict[str, bytes | None] = {}
    for relative in normalized_paths:
        decoded[relative] = backup_entry_data(relative, files[relative])
    restored_stamp = validate_backup_restored_stamp(target, decoded.get(STAMP_NAME))
    expected_paths = list(backup_path_set(restored_stamp))
    if normalized_paths != expected_paths:
        fail("backup managed_paths do not match restored stamp")
    if set(files) != set(expected_paths):
        fail("backup files path set does not match restored stamp")
    return decoded


def prepare_backup(target: Path, stamp: dict[str, Any]) -> PendingBackup:
    pool = backup_pool(target)
    slot = choose_backup_slot(pool)
    files: dict[str, Any] = {}
    backup_paths = backup_path_set(stamp)
    for relative in backup_paths:
        data = read_existing_file(
            safe_target_path(target, relative), max_bytes=MANAGED_MAX_BYTES, label=relative
        )
        files[relative] = backup_entry(data)
    descriptor = stamp_descriptor(stamp)
    envelope = {
        "schema_version": BACKUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(validate_target(target, create=False)),
        "source": descriptor,
        "created_at": int(time.time()),
        "managed_paths": list(backup_paths),
        "files": files,
    }
    validate_backup_envelope(target, slot, envelope)
    return PendingBackup(slot=slot, envelope=envelope)


def validate_backup_slot_directory(path: Path, label: str) -> None:
    info = stat_existing(path, label)
    if info is None:
        fail(f"{label} is missing")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a directory")
    if not is_current_owner(info):
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        fail(f"{label} must be private with mode 0700")
    entries = sorted(child.name for child in path.iterdir())
    if entries != [BACKUP_NAME]:
        fail(f"{label} must contain only {BACKUP_NAME}")


def commit_backup(target: Path, pending: PendingBackup) -> BackupCommitResult:
    pool = backup_pool(target)
    pool_snapshot = snapshot_tree(
        pool,
        "backup pool",
        max_file_bytes=METADATA_MAX_BYTES,
        max_paths=128,
    )
    ensure_private_directory(pool, "backup pool")
    slot_dir = pool / str(pending.slot)
    stage_dir = pool / f".{pending.slot}.nddev-backup-stage.{os.getpid()}.{time.time_ns()}"
    old_dir = pool / f".{pending.slot}.nddev-backup-old.{os.getpid()}.{time.time_ns()}"
    old_snapshot = snapshot_tree(
        slot_dir,
        f"backup slot {pending.slot}",
        max_file_bytes=METADATA_MAX_BYTES,
        max_paths=64,
    )
    published = False
    old_moved = False

    def rollback_backup_once() -> None:
        nonlocal old_moved, published
        if old_moved and not path_exists_no_follow(old_dir):
            verify_tree_snapshot(
                slot_dir,
                old_snapshot,
                f"backup slot {pending.slot}",
                max_file_bytes=METADATA_MAX_BYTES,
                max_paths=64,
            )
            fsync_directory(pool)
            published = False
            old_moved = False
        elif published:
            remove_tree_once(
                slot_dir,
                f"backup slot {pending.slot}",
                max_file_bytes=METADATA_MAX_BYTES,
                max_paths=64,
            )
            published = False
        if old_moved and path_exists_no_follow(old_dir):
            os.replace(old_dir, slot_dir)
            fsync_directory(pool)
            old_moved = False
        remove_path_strict(
            stage_dir,
            "backup stage",
            max_file_bytes=METADATA_MAX_BYTES,
            max_paths=64,
        )
        remove_path_strict(
            old_dir,
            "old backup slot",
            max_file_bytes=METADATA_MAX_BYTES,
            max_paths=64,
        )
        restore_tree_snapshot(
            pool,
            pool_snapshot,
            "backup pool",
            max_file_bytes=METADATA_MAX_BYTES,
            max_paths=128,
        )

    def verify_backup_rolled_back() -> None:
        verify_tree_snapshot(
            pool,
            pool_snapshot,
            "backup pool",
            max_file_bytes=METADATA_MAX_BYTES,
            max_paths=128,
        )
        verify_tree_snapshot(
            slot_dir,
            old_snapshot,
            f"backup slot {pending.slot}",
            max_file_bytes=METADATA_MAX_BYTES,
            max_paths=64,
        )
        for residue, label in ((stage_dir, "backup stage"), (old_dir, "old backup slot")):
            if path_exists_no_follow(residue):
                fail(f"{label} rollback residue remains")

    try:
        stage_dir.mkdir(mode=OWNER_DIRECTORY_MODE)
        stage_dir.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(pool)
        atomic_write(stage_dir / BACKUP_NAME, canonical_json(pending.envelope), stage_dir)
        reread = read_json_file(
            stage_dir / BACKUP_NAME, max_bytes=METADATA_MAX_BYTES, label=BACKUP_NAME
        )
        validate_backup_envelope(target, pending.slot, reread)
        slot_info = stat_existing(slot_dir, f"backup slot {pending.slot}")
        if slot_info is not None:
            validate_backup_slot_directory(slot_dir, f"backup slot {pending.slot}")
            os.replace(slot_dir, old_dir)
            fsync_directory(pool)
            old_moved = True
        os.replace(stage_dir, slot_dir)
        published = True
        fsync_directory(pool)
        validate_backup_slot_directory(slot_dir, f"backup slot {pending.slot}")
        committed = read_json_file(
            slot_dir / BACKUP_NAME, max_bytes=METADATA_MAX_BYTES, label=BACKUP_NAME
        )
        validate_backup_envelope(target, pending.slot, committed)
        cleanup_sources: tuple[tuple[Path | None, str, int, int], ...] = ()
        if path_exists_no_follow(old_dir):
            cleanup_sources = ((old_dir, "old backup slot", METADATA_MAX_BYTES, 64),)
        return BackupCommitResult(slot=pending.slot, cleanup_sources=cleanup_sources)
    except BaseException:
        restore_with_retries(
            rollback_backup_once,
            verify_backup_rolled_back,
            "backup slot publication",
        )
        raise


def build_stamp(
    target: Path, setup: dict[str, Any], profile_data: dict[str, Any], files: dict[str, bytes]
) -> dict[str, Any]:
    managed = {
        relative: managed_digest_for_bytes(relative, data) for relative, data in files.items()
    }
    return {
        "schema_version": CURRENT_SETUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "content_setup_id": setup["id"],
        "permission_profile_id": profile_data["id"],
        "canonical_target": str(validate_target(target, create=False)),
        "managed_files": managed,
    }


def setup_change_sets(
    target: Path,
    files: dict[str, bytes],
    current: dict[str, Any] | None,
) -> tuple[list[str], list[str], list[str]]:
    changed = sorted(
        relative
        for relative, data in files.items()
        if current_managed_digest(target, relative) != managed_digest_for_bytes(relative, data)
    )
    removed = sorted(relative for relative in stamp_managed_paths(current) if relative not in files)
    changed_paths = sorted(dict.fromkeys((*changed, *removed)))
    return changed, removed, changed_paths


def verify_setup_postcondition(
    target: Path,
    desired_stamp: dict[str, Any],
    files: dict[str, bytes],
    removed: tuple[str, ...],
) -> None:
    for relative, data in files.items():
        expected = managed_digest_for_bytes(relative, data)
        if current_managed_digest(target, relative) != expected:
            fail(f"postcondition failed for managed path: {relative}")
    for relative in removed:
        if current_managed_digest(target, relative) is not None:
            fail(f"postcondition failed for removed managed path: {relative}")
    stamp = read_stamp(target)
    if stamp != desired_stamp:
        fail("postcondition failed for setup stamp")


def write_setup(
    target: Path,
    setup: dict[str, Any],
    profile_data: dict[str, Any],
    *,
    require_existing: bool = False,
    migrate_legacy: bool = False,
    use_current_content_setup: bool = False,
) -> dict[str, Any]:
    require_supported_product_host()
    with target_lock(target, create_parent=not require_existing) as transaction:
        validate_target(target, create=not require_existing, transaction=transaction)
        cleanup_drained = drain_cleanup_journal(target)
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
                    "changed_paths": [],
                    "removed": [],
                    "backup_slot": None,
                    "cleanup_pending": False,
                    "cleanup_drained": cleanup_drained,
                    "target": str(validate_target(target, create=False)),
                }
            drift = drift_for_stamp(target, current)
            if drift:
                fail(f"managed target has drift: {', '.join(drift)}")
        if use_current_content_setup:
            if current is None:
                fail("operation requires an already managed target")
            setup = load_content_setup(str(current.get("content_setup_id", DEFAULT_CONTENT_SETUP)))
        files = desired_files(target, setup, profile_data)
        desired_stamp = build_stamp(target, setup, profile_data, files)
        changed, removed, changed_paths = setup_change_sets(target, files, current)
        descriptor = stamp_descriptor(current)
        backup_required = bool(
            current is not None
            and (
                descriptor["legacy"]
                or descriptor["content_setup_id"] != setup["id"]
                or descriptor["permission_profile_id"] != profile_data["id"]
            )
        )
        if current is not None and not backup_required and not changed and not removed:
            return {
                "content_setup_id": setup["id"],
                "permission_profile_id": profile_data["id"],
                "changed": [CLEANUP_DIR_NAME] if cleanup_drained else [],
                "changed_paths": [CLEANUP_DIR_NAME] if cleanup_drained else [],
                "removed": [],
                "backup_slot": None,
                "cleanup_pending": False,
                "cleanup_drained": cleanup_drained,
                "target": str(validate_target(target, create=False)),
            }
        pending_backup = (
            prepare_backup(target, current) if backup_required and current is not None else None
        )
        backup_slot = None
        cleanup_pending = False
        stale_paths = tuple(removed)
        snapshot = snapshot_files(target, stale_paths)
        backup_snapshot = snapshot_tree(
            backup_pool(target),
            "backup pool",
            max_file_bytes=METADATA_MAX_BYTES,
            max_paths=64,
        )
        file_transaction: FileObjectTransaction | None = None
        backup_cleanup_sources: tuple[tuple[Path | None, str, int, int], ...] = ()
        try:
            file_transaction = apply_setup_file_transaction(
                target,
                files,
                desired_stamp,
                stale_paths,
            )
            verify_setup_postcondition(target, desired_stamp, files, stale_paths)
            if pending_backup is not None:
                backup_result = commit_backup(target, pending_backup)
                backup_slot = backup_result.slot
                backup_cleanup_sources = backup_result.cleanup_sources
                slot_dir = backup_pool(target) / str(backup_slot)
                validate_backup_slot_directory(slot_dir, f"backup slot {backup_slot}")
                committed = read_json_file(
                    slot_dir / BACKUP_NAME, max_bytes=METADATA_MAX_BYTES, label=BACKUP_NAME
                )
                validate_backup_envelope(target, backup_slot, committed)
            prune_empty_managed_dirs(target, stale_paths)
            verify_setup_postcondition(target, desired_stamp, files, stale_paths)
            file_transaction.commit()
        except BaseException:
            if file_transaction is not None:
                file_transaction.rollback()
            else:
                restore_snapshot(target, snapshot)
            restore_tree_snapshot(
                backup_pool(target),
                backup_snapshot,
                "backup pool",
                max_file_bytes=METADATA_MAX_BYTES,
                max_paths=64,
            )
            raise
        if backup_cleanup_sources:
            cleanup_pending = finish_cleanup_journal(target, list(backup_cleanup_sources))
        return {
            "content_setup_id": setup["id"],
            "permission_profile_id": profile_data["id"],
            "changed": changed,
            "changed_paths": changed_paths,
            "removed": removed,
            "backup_slot": backup_slot,
            "cleanup_pending": cleanup_pending,
            "cleanup_drained": cleanup_drained,
            "target": str(validate_target(target, create=False)),
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    if slot < 0 or slot > 9:
        fail("backup slot must be between 0 and 9")
    require_supported_product_host()
    with target_lock(target, create_parent=True) as transaction:
        validate_target(target, create=True, transaction=transaction)
        cleanup_drained = drain_cleanup_journal(target)
        envelope_path = backup_pool(target) / str(slot) / BACKUP_NAME
        validate_backup_slot_directory(envelope_path.parent, f"backup slot {slot}")
        envelope = read_json_file(envelope_path, max_bytes=METADATA_MAX_BYTES, label=BACKUP_NAME)
        files = validate_backup_envelope(target, slot, envelope)
        current = read_stamp(target)
        restore_paths = tuple(
            dict.fromkeys(
                (*content_managed_paths(), *stamp_managed_paths(current), *files, STAMP_NAME)
            )
        )
        desired = {
            relative: FileSnapshot(
                data=files.get(relative),
                mode=OWNER_FILE_MODE if files.get(relative) is not None else None,
            )
            for relative in restore_paths
        }
        snapshot = snapshot_files(target, restore_paths)
        try:
            for relative in restore_paths:
                restore_file_snapshot(
                    safe_target_path(target, relative),
                    desired[relative],
                    target,
                    relative,
                    max_bytes=MANAGED_MAX_BYTES,
                )
            restored_stamp = read_stamp(target)
            if restored_stamp is None:
                fail("backup restore postcondition failed: setup stamp is missing")
            if list(backup_path_set(restored_stamp)) != list(files):
                fail("backup restore postcondition failed: restored stamp path set")
            for relative, expected in desired.items():
                current = read_existing_file(
                    safe_target_path(target, relative),
                    max_bytes=MANAGED_MAX_BYTES,
                    label=relative,
                )
                if current != expected.data:
                    fail(f"backup restore postcondition failed: {relative}")
            prune_empty_managed_dirs(target, restore_paths)
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
            "cleanup_pending": False,
            "cleanup_drained": cleanup_drained,
            "target": str(validate_target(target, create=False)),
        }


def remove_managed_block_from_target(target: Path, relative: str) -> None:
    path = safe_target_path(target, relative)
    changed, updated = removed_managed_block_bytes(target, relative)
    if not changed:
        return
    if updated is None:
        durable_unlink(path)
        return
    atomic_write(path, updated, target)


def prune_empty_managed_dirs(target: Path, extra_paths: tuple[str, ...] = ()) -> None:
    candidates: set[Path] = set()
    for relative in (*content_managed_paths(), *extra_paths):
        directory = safe_target_path(target, relative).parent
        while directory != target and target in directory.parents:
            candidates.add(directory)
            directory = directory.parent
    directories = sorted(candidates, key=lambda item: len(item.parts), reverse=True)
    for directory in directories:
        remove_empty_directory_if_empty(directory)


def remove_setup(target: Path) -> dict[str, Any]:
    require_supported_product_host()
    with target_lock(target):
        validate_target(target, create=False)
        cleanup_drained = drain_cleanup_journal(target)
        stamp = read_stamp(target)
        if stamp is None:
            return {
                "removed": None,
                "cleanup_pending": False,
                "cleanup_drained": cleanup_drained,
                "changed": cleanup_drained,
                "target": str(validate_target(target, create=False)),
            }
        drift = drift_for_stamp(target, stamp)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        descriptor = stamp_descriptor(stamp)
        remove_paths = tuple(dict.fromkeys((*content_managed_paths(), *stamp_managed_paths(stamp))))
        snapshot = snapshot_files(target, remove_paths)
        file_transaction: FileObjectTransaction | None = None
        try:
            file_transaction = FileObjectTransaction(target)
            for relative in remove_paths:
                path = safe_target_path(target, relative)
                if relative in MERGED_MARKER_PATHS:
                    changed, updated = removed_managed_block_bytes(target, relative)
                    if not changed:
                        continue
                    if updated is None:
                        file_transaction.stage_remove(path, label=relative)
                    else:
                        file_transaction.stage_write(path, updated, label=relative)
                else:
                    file_transaction.stage_remove(path, label=relative)
            file_transaction.stage_remove(
                stamp_path(target), label=STAMP_NAME, max_bytes=METADATA_MAX_BYTES
            )
            file_transaction.apply_once()
            prune_empty_managed_dirs(target, remove_paths)
            for relative in remove_paths:
                if current_managed_digest(target, relative) is not None:
                    fail(f"remove postcondition failed for managed path: {relative}")
            if read_stamp(target) is not None:
                fail("remove postcondition failed for setup stamp")
            file_transaction.commit()
        except BaseException:
            if file_transaction is not None:
                file_transaction.rollback()
            else:
                restore_snapshot(target, snapshot)
            raise
        return {
            "removed": descriptor,
            "cleanup_pending": False,
            "cleanup_drained": cleanup_drained,
            "target": str(validate_target(target, create=False)),
        }


def update_setup(target: Path) -> dict[str, Any]:
    require_supported_product_host()
    with target_lock(target):
        validate_target(target, create=False)
        cleanup_drained = drain_cleanup_journal(target)
        current = read_stamp(target)
        if current is None:
            fail("update requires an already managed target")
        if not stamp_is_current(current):
            fail("managed target uses a legacy setup schema; use migrate")
        drift = drift_for_stamp(target, current)
        if drift:
            fail(f"managed target has drift: {', '.join(drift)}")
        setup_id = str(current.get("content_setup_id"))
        profile_id = str(current.get("permission_profile_id"))
        setup = load_content_setup(setup_id)
        profile_data = load_profile(profile_id)
        files = desired_files(target, setup, profile_data)
        desired_stamp = build_stamp(target, setup, profile_data, files)
        changed, removed, changed_paths = setup_change_sets(target, files, current)
        if not changed and not removed:
            return {
                "content_setup_id": setup_id,
                "permission_profile_id": profile_id,
                "changed": [CLEANUP_DIR_NAME] if cleanup_drained else [],
                "changed_paths": [CLEANUP_DIR_NAME] if cleanup_drained else [],
                "removed": [],
                "backup_slot": None,
                "cleanup_pending": False,
                "cleanup_drained": cleanup_drained,
                "target": str(validate_target(target, create=False)),
            }
        stale_paths = tuple(removed)
        snapshot = snapshot_files(target, stale_paths)
        pending_backup = prepare_backup(target, current)
        backup_snapshot = snapshot_tree(
            backup_pool(target),
            "backup pool",
            max_file_bytes=METADATA_MAX_BYTES,
            max_paths=64,
        )
        file_transaction: FileObjectTransaction | None = None
        backup_slot: int | None = None
        cleanup_pending = False
        backup_cleanup_sources: tuple[tuple[Path | None, str, int, int], ...] = ()
        try:
            file_transaction = apply_setup_file_transaction(
                target,
                files,
                desired_stamp,
                stale_paths,
            )
            verify_setup_postcondition(target, desired_stamp, files, stale_paths)
            backup_result = commit_backup(target, pending_backup)
            backup_slot = backup_result.slot
            backup_cleanup_sources = backup_result.cleanup_sources
            committed = read_json_file(
                backup_pool(target) / str(backup_slot) / BACKUP_NAME,
                max_bytes=METADATA_MAX_BYTES,
                label=BACKUP_NAME,
            )
            validate_backup_envelope(target, backup_slot, committed)
            prune_empty_managed_dirs(target, stale_paths)
            verify_setup_postcondition(target, desired_stamp, files, stale_paths)
            file_transaction.commit()
        except BaseException:
            if file_transaction is not None:
                file_transaction.rollback()
            else:
                restore_snapshot(target, snapshot)
            restore_tree_snapshot(
                backup_pool(target),
                backup_snapshot,
                "backup pool",
                max_file_bytes=METADATA_MAX_BYTES,
                max_paths=64,
            )
            raise
        if backup_cleanup_sources:
            cleanup_pending = finish_cleanup_journal(target, list(backup_cleanup_sources))
        return {
            "content_setup_id": setup_id,
            "permission_profile_id": profile_id,
            "changed": changed,
            "changed_paths": changed_paths,
            "removed": removed,
            "backup_slot": backup_slot,
            "cleanup_pending": cleanup_pending,
            "cleanup_drained": cleanup_drained,
            "target": str(validate_target(target, create=False)),
        }


def _plan_payload_locked(
    target: Path,
    setup: dict[str, Any],
    profile_data: dict[str, Any],
    *,
    migrate_legacy: bool = False,
) -> dict[str, Any]:
    status = _status_payload_locked(target)
    operation = "install"
    backup_required = False
    if status["managed"]:
        if status["state"] == "legacy-managed":
            operation = "migrate" if migrate_legacy else "blocked-legacy"
            backup_required = migrate_legacy
        elif (
            status["content_setup_id"] == setup["id"]
            and status["permission_profile_id"] == profile_data["id"]
        ):
            operation = "update"
        else:
            operation = "switch-profile" if status["content_setup_id"] == setup["id"] else "switch"
            backup_required = True
    changed: list[str] = []
    removed: list[str] = []
    changed_paths: list[str] = []
    if operation != "blocked-legacy" and not status["drift"]:
        current = read_stamp(target)
        files = desired_files(target, setup, profile_data)
        changed, removed, changed_paths = setup_change_sets(target, files, current)
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
        "changed": changed,
        "removed": removed,
        "changed_paths": changed_paths,
        "cleanup_pending": status["cleanup_pending"],
        "cleanup_pending_metadata": status["cleanup_pending_metadata"],
        "mutates": False,
    }


def plan_payload(
    target: Path,
    setup: dict[str, Any],
    profile_data: dict[str, Any],
    *,
    migrate_legacy: bool = False,
) -> dict[str, Any]:
    require_supported_product_host()
    return run_under_readonly_external_lifecycle(
        target,
        lambda canonical_target: _plan_payload_locked(
            canonical_target,
            setup,
            profile_data,
            migrate_legacy=migrate_legacy,
        ),
    )


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
    require_safe_partial_file(
        software_entrypoint(target), "Kimi Code entrypoint", max_bytes=SOFTWARE_MAX_BYTES
    )
    require_safe_partial_file(
        software_stamp_path(target), SOFTWARE_STAMP_NAME, max_bytes=METADATA_MAX_BYTES
    )


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


def _software_status_payload_locked(target: Path) -> dict[str, Any]:
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
        "cleanup_pending": False,
        "cleanup_pending_metadata": [],
    }
    target_info = stat_existing(target, "target")
    if target_info is None:
        return payload
    if not stat.S_ISDIR(target_info.st_mode):
        fail("target must be a real directory")
    require_owner_private_directory(target, "target")
    cleanup_metadata = cleanup_pending_metadata(target)
    payload["cleanup_pending"] = bool(cleanup_metadata)
    payload["cleanup_pending_metadata"] = cleanup_metadata
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
        entrypoint_info = validate_software_file(
            software_entrypoint(target), "Kimi Code entrypoint"
        )
        if stat.S_IMODE(entrypoint_info.st_mode) != 0o700:
            drift.append("entrypoint_mode")
        current_binary_info = validate_software_file(
            software_current_binary(target), "current Kimi Code binary"
        )
        if stat.S_IMODE(current_binary_info.st_mode) != 0o700:
            drift.append("current_binary_mode")
        platform_key = stamp.get("platform")
        binary = stamp.get("binary")
        source = stamp.get("source")
        if platform_key not in KIMI_BINARY_PLATFORMS:
            drift.append("platform")
        expected_binary = KIMI_BINARY_PLATFORMS.get(str(platform_key), {})
        expected_url = (
            f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/{expected_binary.get('filename')}"
        )
        if (
            not isinstance(binary, dict)
            or binary.get("filename") != expected_binary.get("filename")
            or binary.get("url") != expected_url
            or binary.get("sha256") != expected_binary.get("checksum")
        ):
            drift.append("binary")
        if source != software_source_contract():
            drift.append("source")
        entrypoint_digest = file_sha256(software_entrypoint(target), label="Kimi Code entrypoint")
        current_binary_digest = file_sha256(
            software_current_binary(target), label="current Kimi Code binary"
        )
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


def software_status_payload(target: Path) -> dict[str, Any]:
    require_supported_product_host()
    return run_under_readonly_external_lifecycle(target, _software_status_payload_locked)


def parse_os_release(text: str, *, source: str) -> LinuxDistribution:
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        try:
            parts = shlex.split(raw_value, comments=False, posix=True)
        except ValueError:
            value = raw_value.strip().strip("'\"")
        else:
            value = parts[0] if parts else ""
        fields[key] = value
    distro_id = fields.get("ID", "").strip().lower() or "unknown"
    id_like = tuple(value.lower() for value in fields.get("ID_LIKE", "").split() if value)
    return LinuxDistribution(
        distro_id=distro_id,
        id_like=id_like,
        pretty_name=fields.get("PRETTY_NAME", ""),
        source=source,
    )


def detect_linux_distribution(
    os_release_paths: tuple[Path, ...] = LINUX_OS_RELEASE_PATHS,
) -> LinuxDistribution:
    for path in os_release_paths:
        try:
            with path.open("rb") as handle:
                data = handle.read(METADATA_MAX_BYTES + 1)
        except FileNotFoundError:
            continue
        except OSError as exc:
            fail(f"could not read Linux os-release metadata: {exc}")
        if len(data) > METADATA_MAX_BYTES:
            fail(f"Linux os-release metadata is too large: {path}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"Linux os-release metadata is not UTF-8: {exc}")
        return parse_os_release(text, source=str(path))
    return LinuxDistribution(
        distro_id="unknown",
        id_like=(),
        pretty_name="",
        source="missing os-release",
    )


def linux_libc_is_musl(
    *,
    marker_paths: tuple[Path, ...] = LINUX_MUSL_MARKER_PATHS,
    ldd_runner: Any | None = None,
) -> bool:
    if any(path.exists() for path in marker_paths):
        return True
    runner = subprocess.run if ldd_runner is None else ldd_runner
    with contextlib.suppress(Exception):
        completed = runner(
            ["ldd", "/bin/ls"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
            check=False,
        )
        if "musl" in str(getattr(completed, "stdout", "")).lower():
            return True
    return False


def require_ubuntu_linux(
    *,
    os_release_paths: tuple[Path, ...] = LINUX_OS_RELEASE_PATHS,
    musl_marker_paths: tuple[Path, ...] = LINUX_MUSL_MARKER_PATHS,
    ldd_runner: Any | None = None,
) -> LinuxDistribution:
    if linux_libc_is_musl(marker_paths=musl_marker_paths, ldd_runner=ldd_runner):
        fail(
            "unsupported host category: linux-musl; nddev-kimicode-app supports Ubuntu glibc hosts only"
        )
    distro = detect_linux_distribution(os_release_paths)
    if distro.distro_id != "ubuntu":
        fail(
            f"unsupported host category: non-ubuntu-linux; detected {distro.distro_id}; "
            "nddev-kimicode-app supports Ubuntu ID=ubuntu glibc hosts only"
        )
    return distro


def supported_arch(raw_machine: str) -> str:
    machine = raw_machine.lower()
    if machine in {"x86_64", "amd64"}:
        return "x64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    fail(f"unsupported host category: unsupported-architecture; detected {raw_machine}")


def detect_supported_host(
    *,
    system_name: str | None = None,
    machine_name: str | None = None,
    os_release_paths: tuple[Path, ...] = LINUX_OS_RELEASE_PATHS,
    musl_marker_paths: tuple[Path, ...] = LINUX_MUSL_MARKER_PATHS,
    ldd_runner: Any | None = None,
) -> DetectedHost:
    system = platform.system() if system_name is None else system_name
    raw_machine = platform.machine() if machine_name is None else machine_name
    if system not in {"Darwin", "Linux"}:
        category = "windows" if system.lower().startswith("win") else "unsupported-architecture"
        fail(
            f"unsupported host category: {category}; nddev-kimicode-app supports "
            + ", ".join(KIMI_SUPPORTED_PRODUCT_HOSTS)
        )
    arch = supported_arch(raw_machine)
    if system == "Darwin":
        os_name = "darwin"
        product_host_id = f"macos-{arch}"
        distro = None
    else:
        os_name = "linux"
        distro = require_ubuntu_linux(
            os_release_paths=os_release_paths,
            musl_marker_paths=musl_marker_paths,
            ldd_runner=ldd_runner,
        )
        product_host_id = f"ubuntu-glibc-{arch}"
    vendor_platform_key = KIMI_PRODUCT_HOST_TO_VENDOR_PLATFORM[product_host_id]
    if vendor_platform_key not in KIMI_BINARY_PLATFORMS:
        fail(f"unsupported platform: {product_host_id}")
    return DetectedHost(
        product_host_id=product_host_id,
        vendor_platform_key=vendor_platform_key,
        os_name=os_name,
        arch=arch,
        linux_distribution=distro,
    )


def detect_official_platform(
    *,
    system_name: str | None = None,
    machine_name: str | None = None,
    os_release_paths: tuple[Path, ...] = LINUX_OS_RELEASE_PATHS,
    musl_marker_paths: tuple[Path, ...] = LINUX_MUSL_MARKER_PATHS,
    ldd_runner: Any | None = None,
) -> str:
    return detect_supported_host(
        system_name=system_name,
        machine_name=machine_name,
        os_release_paths=os_release_paths,
        musl_marker_paths=musl_marker_paths,
        ldd_runner=ldd_runner,
    ).vendor_platform_key


def require_supported_product_host() -> DetectedHost:
    return detect_supported_host()


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
    manifest_bytes = fetch_url_bytes(
        KIMI_BINARY_MANIFEST_URL, max_bytes=METADATA_MAX_BYTES, label="Kimi Code binary manifest"
    )
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
    if (
        not isinstance(platforms, dict)
        or platforms.get(platform_key) != KIMI_BINARY_PLATFORMS[platform_key]
    ):
        fail("Kimi Code binary manifest platform entry does not match the pinned baseline")
    binary = KIMI_BINARY_PLATFORMS[platform_key]
    url = f"{KIMI_BINARY_BASE}/{KIMI_PACKAGE_VERSION}/{binary['filename']}"
    binary_bytes = fetch_url_bytes(url, max_bytes=DOWNLOAD_MAX_BYTES, label="Kimi Code binary")
    if sha256_bytes(binary_bytes) != binary["checksum"]:
        fail("Kimi Code binary digest does not match the pinned baseline")
    bin_dir = stage_current / "bin"
    bin_dir.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True)
    bin_dir.chmod(OWNER_DIRECTORY_MODE)
    fsync_directory(stage_current)
    destination = bin_dir / KIMI_COMMAND
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(fd, "wb") as handle:
        handle.write(binary_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    destination.chmod(0o700)
    fsync_directory(bin_dir)
    return {
        "platform": platform_key,
        "filename": binary["filename"],
        "url": url,
        "sha256": binary["checksum"],
        "manifest_sha256": manifest_digest,
    }


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
            fail(
                f"staged kimi version probe failed with exit code {completed.returncode}: {detail}"
            )
        output = (stdout_text + stderr_text).strip()
        if KIMI_PACKAGE_VERSION not in output:
            fail("staged kimi version probe did not report the pinned release")
        return sha256_bytes(output.encode("utf-8"))


def software_source_contract() -> dict[str, Any]:
    return {
        "channel": "official-binary",
        "install_script_url": KIMI_INSTALL_SCRIPT_URL,
        "install_script_sha256": KIMI_INSTALL_SCRIPT_SHA256,
        "install_powershell_url": KIMI_INSTALL_POWERSHELL_URL,
        "install_powershell_sha256": KIMI_INSTALL_POWERSHELL_SHA256,
        "install_powershell_size_bytes": KIMI_INSTALL_POWERSHELL_SIZE_BYTES,
        "install_powershell_product_supported": False,
        "latest_url": KIMI_LATEST_URL,
        "manifest_url": KIMI_BINARY_MANIFEST_URL,
        "manifest_sha256": KIMI_BINARY_MANIFEST_SHA256,
        "github_release_url": KIMI_GITHUB_RELEASE_URL,
        "github_release_api_url": KIMI_GITHUB_RELEASE_API_URL,
        "github_release_id": KIMI_GITHUB_RELEASE_ID,
        "git_tag": KIMI_GIT_TAG,
        "git_tag_object": KIMI_GIT_TAG_OBJECT,
        "git_commit": KIMI_GIT_COMMIT,
        "npm_package": KIMI_PACKAGE_NAME,
        "npm_integrity": KIMI_NPM_INTEGRITY,
        "npm_shasum": KIMI_NPM_SHASUM,
        "vendor_distribution_observations": KIMI_VENDOR_DISTRIBUTION_OBSERVATIONS,
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


def snapshot_software_entrypoint(target: Path) -> FileSnapshot:
    return snapshot_replace_destination(
        software_entrypoint(target),
        "Kimi Code entrypoint",
        max_bytes=SOFTWARE_MAX_BYTES,
    )


def snapshot_software_stamp(target: Path) -> FileSnapshot:
    return snapshot_replace_destination(
        software_stamp_path(target),
        SOFTWARE_STAMP_NAME,
        max_bytes=METADATA_MAX_BYTES,
    )


def snapshot_software_state(target: Path) -> SoftwareStateSnapshot:
    entrypoint_parent = software_entrypoint(target).parent
    parent_info = stat_existing(entrypoint_parent, "bin")
    if parent_info is not None and not stat.S_ISDIR(parent_info.st_mode):
        fail("bin must be a directory")
    return SoftwareStateSnapshot(
        software_tree=snapshot_tree(
            software_root(target),
            "software root",
            max_file_bytes=SOFTWARE_MAX_BYTES,
            max_paths=SOFTWARE_MAX_PATHS,
        ),
        entrypoint=snapshot_software_entrypoint(target),
        stamp=snapshot_software_stamp(target),
        entrypoint_parent_present=parent_info is not None,
        entrypoint_parent_mode=stat.S_IMODE(parent_info.st_mode)
        if parent_info is not None
        else None,
        entrypoint_parent_signature=directory_object_signature(entrypoint_parent, "bin"),
    )


def verify_software_state(target: Path, snapshot: SoftwareStateSnapshot) -> None:
    verify_tree_snapshot(
        software_root(target),
        snapshot.software_tree,
        "software root",
        max_file_bytes=SOFTWARE_MAX_BYTES,
        max_paths=SOFTWARE_MAX_PATHS,
    )
    verify_file_snapshot(
        software_entrypoint(target),
        snapshot.entrypoint,
        "Kimi Code entrypoint",
        max_bytes=SOFTWARE_MAX_BYTES,
    )
    verify_file_snapshot(
        software_stamp_path(target),
        snapshot.stamp,
        SOFTWARE_STAMP_NAME,
        max_bytes=METADATA_MAX_BYTES,
    )
    parent = software_entrypoint(target).parent
    parent_info = stat_existing(parent, "bin")
    verify_directory_object_signature(parent, snapshot.entrypoint_parent_signature, "bin")
    if snapshot.entrypoint_parent_present:
        if parent_info is None:
            fail("software rollback postcondition failed: bin parent is missing")
        assert parent_info is not None
        if stat.S_IMODE(parent_info.st_mode) != snapshot.entrypoint_parent_mode:
            fail("software rollback postcondition failed: bin parent mode mismatch")
    elif parent_info is not None:
        fail("software rollback postcondition failed: bin parent should be absent")


def restore_software_state_once(target: Path, snapshot: SoftwareStateSnapshot) -> None:
    restore_tree_snapshot(
        software_root(target),
        snapshot.software_tree,
        "software root",
        max_file_bytes=SOFTWARE_MAX_BYTES,
        max_paths=SOFTWARE_MAX_PATHS,
    )
    restore_file_snapshot(
        software_entrypoint(target),
        snapshot.entrypoint,
        target,
        "Kimi Code entrypoint",
        max_bytes=SOFTWARE_MAX_BYTES,
        default_mode=0o700,
    )
    restore_file_snapshot(
        software_stamp_path(target),
        snapshot.stamp,
        target,
        SOFTWARE_STAMP_NAME,
        max_bytes=METADATA_MAX_BYTES,
        default_mode=OWNER_FILE_MODE,
    )
    parent = software_entrypoint(target).parent
    if snapshot.entrypoint_parent_present:
        if snapshot.entrypoint_parent_mode is None:
            fail("software rollback snapshot is missing bin parent mode")
        info = stat_existing(parent, "bin")
        if info is None:
            parent.mkdir(mode=snapshot.entrypoint_parent_mode)
            parent.chmod(snapshot.entrypoint_parent_mode)
            fsync_directory(parent.parent)
        elif stat.S_IMODE(info.st_mode) != snapshot.entrypoint_parent_mode:
            parent.chmod(snapshot.entrypoint_parent_mode)
            fsync_directory(parent.parent)
    else:
        remove_empty_directory_if_empty(parent)
    restore_directory_object_signature(parent, snapshot.entrypoint_parent_signature, "bin")
    verify_software_state(target, snapshot)


def restore_software_state(target: Path, snapshot: SoftwareStateSnapshot) -> None:
    restore_with_retries(
        lambda: restore_software_state_once(target, snapshot),
        lambda: verify_software_state(target, snapshot),
        "software state",
    )


def copy_staged_binary(source: Path, destination: Path, target: Path) -> str:
    info = validate_software_file(source, "staged Kimi Code binary")
    ensure_real_parent(destination, target)
    expected_digest = file_sha256(source, label="staged Kimi Code binary")
    original = snapshot_replace_destination(
        destination,
        "Kimi Code entrypoint",
        max_bytes=SOFTWARE_MAX_BYTES,
    )
    temporary = destination.with_name(
        f".{destination.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}"
    )
    fd, _ = open_regular_readonly(source, "staged Kimi Code binary", max_bytes=SOFTWARE_MAX_BYTES)
    replaced = False
    try:
        with os.fdopen(fd, "rb") as source_handle:
            with temporary.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                temporary.chmod(0o700 if stat.S_IMODE(info.st_mode) & 0o100 else OWNER_FILE_MODE)
                target_handle.flush()
                os.fsync(target_handle.fileno())
        os.replace(temporary, destination)
        replaced = True
        fsync_directory(destination.parent)
    except BaseException:
        if replaced:
            rollback_replaced_destination(
                destination,
                original,
                target,
                "Kimi Code entrypoint",
                max_bytes=SOFTWARE_MAX_BYTES,
            )
        else:
            restore_with_retries(
                lambda: durable_unlink(temporary),
                lambda: verify_file_snapshot(
                    temporary,
                    FileSnapshot(data=None, mode=None),
                    str(temporary),
                    max_bytes=SOFTWARE_MAX_BYTES,
                ),
                str(temporary),
            )
        raise
    digest = file_sha256(destination, label="Kimi Code entrypoint")
    if digest != expected_digest:
        rollback_replaced_destination(
            destination,
            original,
            target,
            "Kimi Code entrypoint",
            max_bytes=SOFTWARE_MAX_BYTES,
        )
        fail("copied Kimi Code entrypoint does not match staged binary")
    return digest


def stage_binary_copy(source: Path, destination: Path, target: Path) -> tuple[Path, str]:
    info = validate_software_file(source, "staged Kimi Code binary")
    ensure_real_parent(destination, target)
    expected_digest = file_sha256(source, label="staged Kimi Code binary")
    staged = object_sidecar(destination, ".nddev.tmp")
    fd, _ = open_regular_readonly(source, "staged Kimi Code binary", max_bytes=SOFTWARE_MAX_BYTES)
    try:
        with os.fdopen(fd, "rb") as source_handle:
            with staged.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                staged.chmod(0o700 if stat.S_IMODE(info.st_mode) & 0o100 else OWNER_FILE_MODE)
                target_handle.flush()
                os.fsync(target_handle.fileno())
    except BaseException:
        restore_with_retries(
            lambda: durable_unlink(staged),
            lambda: verify_file_snapshot(
                staged,
                FileSnapshot(data=None, mode=None),
                "staged Kimi Code entrypoint",
                max_bytes=SOFTWARE_MAX_BYTES,
            ),
            "staged Kimi Code entrypoint",
        )
        raise
    digest = file_sha256(staged, label="staged Kimi Code entrypoint")
    if digest != expected_digest:
        durable_unlink(staged)
        fail("staged Kimi Code entrypoint copy does not match staged binary")
    return staged, digest


def create_transient_directory(parent: Path, name: str, label: str) -> Path:
    require_owner_private_directory(parent, f"{label} parent")
    parent_signature = directory_object_signature(parent, f"{label} parent")
    path = parent / f"{name}{os.getpid()}.{time.time_ns()}"
    created = False
    try:
        path.mkdir(mode=OWNER_DIRECTORY_MODE)
        created = True
        path.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(parent)
    except BaseException:
        if created:
            remove_tree_strict(
                path,
                label,
                max_file_bytes=SOFTWARE_MAX_BYTES,
                max_paths=SOFTWARE_MAX_PATHS + 16,
            )
        restore_directory_object_signature(parent, parent_signature, f"{label} parent")
        raise
    return path


def cleanup_transient_directory(
    path: Path,
    label: str,
    *,
    parent_signature: DirectoryObjectSignature | None = None,
) -> None:
    def cleanup_once() -> None:
        restore_tree_snapshot_once(
            path,
            TreeSnapshot(entries=None),
            label,
            max_file_bytes=SOFTWARE_MAX_BYTES,
            max_paths=SOFTWARE_MAX_PATHS + 16,
        )
        if parent_signature is not None:
            restore_directory_object_signature(path.parent, parent_signature, f"{label} parent")

    def verify_clean() -> None:
        verify_tree_snapshot(
            path,
            TreeSnapshot(entries=None),
            label,
            max_file_bytes=SOFTWARE_MAX_BYTES,
            max_paths=SOFTWARE_MAX_PATHS + 16,
        )
        if parent_signature is not None:
            verify_directory_object_signature(path.parent, parent_signature, f"{label} parent")

    restore_with_retries(
        cleanup_once,
        verify_clean,
        label,
    )


def verify_installed_software_postcondition(
    target: Path,
    *,
    stamp: dict[str, Any],
    binary: dict[str, Any],
) -> None:
    verified = _software_status_payload_locked(target)
    if not verified["current"]:
        fail(f"installed software failed status verification: {', '.join(verified['drift'])}")
    if read_software_stamp(target) != stamp:
        fail("installed software failed stamp postcondition")
    if file_sha256(software_entrypoint(target), label="Kimi Code entrypoint") != binary["sha256"]:
        fail("installed software failed entrypoint postcondition")
    if (
        file_sha256(software_current_binary(target), label="current Kimi Code binary")
        != binary["sha256"]
    ):
        fail("installed software failed current binary postcondition")


def install_or_update_software(target: Path, *, mode: str) -> dict[str, Any]:
    if mode not in {"install", "update", "migrate"}:
        fail("invalid software operation")
    platform_key = require_supported_product_host().vendor_platform_key
    with target_lock(target, create_parent=mode == "install") as transaction:
        try:
            validate_target(target, create=mode == "install", transaction=transaction)
            cleanup_drained = drain_cleanup_journal(target)
            validate_safe_partial_software_presence(target)
            status = _software_status_payload_locked(target)
            if status["current"]:
                return {
                    "changed": cleanup_drained,
                    "version": KIMI_PACKAGE_VERSION,
                    "command": KIMI_COMMAND,
                    "executable": str(software_entrypoint(target)),
                    "installed_tree": str(software_current(target)),
                    "cleanup_pending": False,
                    "cleanup_drained": cleanup_drained,
                    "target": str(validate_target(target, create=False)),
                }
            if mode == "install" and status["present"]:
                fail(
                    "install-cli found target-owned Kimi Code software presence; use update-cli or migrate-cli"
                )
            if mode == "update":
                if not status["present"]:
                    fail("update-cli requires existing target-owned Kimi Code software presence")
                if status["legacy"]:
                    fail("update-cli refuses legacy Bun software; use migrate-cli")
            if mode == "migrate" and not status["legacy"]:
                fail("migrate-cli requires legacy target-owned Bun software state")

            stage_parent = target
            stage_parent_signature = directory_object_signature(
                stage_parent, "software stage parent"
            )
            stage_root = create_transient_directory(
                stage_parent,
                f".{target.name}{SOFTWARE_STAGE_FRAGMENT}.",
                "software stage",
            )
            snapshot = snapshot_software_state(target)
            tree_transaction = TreeObjectTransaction()
            file_transaction = FileObjectTransaction(target)
            stage_current = stage_root / SOFTWARE_CURRENT_NAME
            cleanup_pending = False
            try:
                stage_current.mkdir(mode=OWNER_DIRECTORY_MODE)
                stage_current.chmod(OWNER_DIRECTORY_MODE)
                fsync_directory(stage_root)
                binary = install_official_binary(stage_current, platform_key)
                version_probe_digest = run_stage_version_probe(stage_current, stage_root)
                installed_tree_digest = tree_sha256(stage_current)

                ensure_private_directory(software_root(target), "software root")
                current = software_current(target)
                current_info = stat_existing(current, "current software tree")
                if current_info is not None:
                    if not stat.S_ISDIR(current_info.st_mode):
                        fail("current software tree must be a directory")
                tree_transaction.stage_replace_tree(
                    current,
                    stage_current,
                    label="current software tree",
                    max_file_bytes=SOFTWARE_MAX_BYTES,
                    max_paths=SOFTWARE_MAX_PATHS,
                )
                file_transaction.remember_directory(
                    software_entrypoint(target).parent,
                    "Kimi Code entrypoint parent",
                )
                staged_entrypoint, entrypoint_digest = stage_binary_copy(
                    stage_current / "bin" / KIMI_COMMAND, software_entrypoint(target), target
                )
                stamp = software_stamp(
                    target,
                    platform_key=platform_key,
                    binary=binary,
                    entrypoint_digest=entrypoint_digest,
                    installed_tree_digest=installed_tree_digest,
                    version_probe_digest=version_probe_digest,
                )
                file_transaction.stage_replace_with_staged(
                    software_entrypoint(target),
                    staged_entrypoint,
                    label="Kimi Code entrypoint",
                    max_bytes=SOFTWARE_MAX_BYTES,
                )
                file_transaction.stage_write(
                    software_stamp_path(target),
                    canonical_json(stamp),
                    label=SOFTWARE_STAMP_NAME,
                    max_bytes=METADATA_MAX_BYTES,
                )
                tree_transaction.apply_once()
                file_transaction.apply_once()
                verify_installed_software_postcondition(target, stamp=stamp, binary=binary)
                cleanup_pending = commit_software_transactions(
                    target,
                    file_transaction,
                    tree_transaction,
                    stage_root=stage_root,
                )
            except BaseException:
                file_transaction.rollback()
                tree_transaction.rollback()
                restore_software_state(target, snapshot)
                cleanup_transient_directory(
                    stage_root,
                    "software stage",
                    parent_signature=stage_parent_signature,
                )
                raise
            return {
                "changed": True,
                "version": KIMI_PACKAGE_VERSION,
                "command": KIMI_COMMAND,
                "executable": str(software_entrypoint(target)),
                "installed_tree": str(software_current(target)),
                "target": str(validate_target(target, create=False)),
                "migrated_legacy": mode == "migrate",
                "cleanup_pending": cleanup_pending,
                "cleanup_drained": cleanup_drained,
            }
        except BaseException:
            raise


def verify_removed_software_postcondition(target: Path) -> None:
    for path, label in (
        (software_root(target), SOFTWARE_DIR_NAME),
        (software_stamp_path(target), SOFTWARE_STAMP_NAME),
        (software_entrypoint(target), "bin/kimi"),
    ):
        if path_exists_no_follow(path):
            fail(f"remove-cli postcondition failed: {label} remains")
    bin_parent = software_entrypoint(target).parent
    if path_exists_no_follow(bin_parent) and bin_parent.is_dir() and not any(bin_parent.iterdir()):
        fail("remove-cli postcondition failed: empty bin parent remains")


def cleanup_file_object_sidecars(
    transaction: FileObjectTransaction,
    *,
    staged: bool,
    rollback: bool,
) -> None:
    for change in transaction.changes:
        if staged and change.staged_path is not None:
            durable_unlink(change.staged_path)
        if rollback and change.rollback_path is not None:
            durable_unlink(change.rollback_path)


def cleanup_tree_object_sidecars(
    transaction: TreeObjectTransaction,
    *,
    staged: bool,
    rollback: bool,
) -> None:
    for change in transaction.changes:
        if staged and change.staged_path is not None:
            remove_path_strict(
                change.staged_path,
                change.label,
                max_file_bytes=change.max_file_bytes,
                max_paths=change.max_paths,
            )
        if rollback and change.rollback_path is not None:
            remove_path_strict(
                change.rollback_path,
                change.label,
                max_file_bytes=change.max_file_bytes,
                max_paths=change.max_paths,
            )


def software_cleanup_tombstones(
    file_transaction: FileObjectTransaction,
    tree_transaction: TreeObjectTransaction,
    *,
    stage_root: Path | None = None,
) -> list[tuple[Path | None, str, int, int]]:
    paths: list[tuple[Path | None, str, int, int]] = []
    if stage_root is not None:
        paths.append(
            (
                stage_root,
                "software stage",
                SOFTWARE_MAX_BYTES,
                SOFTWARE_MAX_PATHS + 16,
            )
        )
    for change in file_transaction.changes:
        paths.append((change.staged_path, change.label, change.max_bytes, 1))
        paths.append((change.rollback_path, change.label, change.max_bytes, 1))
    for change in tree_transaction.changes:
        paths.append((change.staged_path, change.label, change.max_file_bytes, change.max_paths))
        paths.append((change.rollback_path, change.label, change.max_file_bytes, change.max_paths))
    return paths


def commit_software_transactions(
    target: Path,
    file_transaction: FileObjectTransaction,
    tree_transaction: TreeObjectTransaction,
    *,
    stage_root: Path | None = None,
) -> bool:
    return finish_cleanup_journal(
        target,
        software_cleanup_tombstones(
            file_transaction,
            tree_transaction,
            stage_root=stage_root,
        ),
    )


def rollback_software_transactions(
    target: Path,
    snapshot: SoftwareStateSnapshot,
    file_transaction: FileObjectTransaction,
    tree_transaction: TreeObjectTransaction,
    original_error: BaseException,
) -> None:
    errors: list[str] = []
    for label, operation in (
        ("managed file objects", file_transaction.rollback),
        ("software tree objects", tree_transaction.rollback),
        ("software state", lambda: restore_software_state(target, snapshot)),
    ):
        try:
            operation()
        except BaseException as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
    try:
        verify_software_state(target, snapshot)
    except BaseException as exc:
        errors.append(f"software state postcondition: {type(exc).__name__}: {exc}")
    if errors:
        fail(
            "remove-cli rollback failed after best-effort restoration: "
            f"original={type(original_error).__name__}: {original_error}; " + "; ".join(errors)
        )


def remove_software(target: Path) -> dict[str, Any]:
    require_supported_product_host()
    with target_lock(target):
        validate_target(target, create=False)
        cleanup_drained = drain_cleanup_journal(target)
        validate_safe_partial_software_presence(target)
        status = _software_status_payload_locked(target)
        if not status["present"]:
            return {
                "changed": cleanup_drained,
                "version": None,
                "command": KIMI_COMMAND,
                "executable": str(software_entrypoint(target)),
                "installed_tree": str(software_current(target)),
                "cleanup_pending": False,
                "cleanup_drained": cleanup_drained,
                "target": str(validate_target(target, create=False)),
            }
        snapshot = snapshot_software_state(target)
        tree_transaction = TreeObjectTransaction()
        file_transaction = FileObjectTransaction(target)
        try:
            bin_parent = software_entrypoint(target).parent
            bin_info = stat_existing(bin_parent, "bin")
            remove_bin_parent = False
            if bin_info is not None:
                if not stat.S_ISDIR(bin_info.st_mode):
                    fail("bin must be a directory")
                entries = sorted(bin_parent.iterdir(), key=lambda item: item.name)
                remove_bin_parent = entries in ([], [software_entrypoint(target)])
            tree_transaction.stage_remove_tree(
                software_root(target),
                label="software root",
                max_file_bytes=SOFTWARE_MAX_BYTES,
                max_paths=SOFTWARE_MAX_PATHS,
            )
            if remove_bin_parent:
                tree_transaction.stage_remove_tree(
                    bin_parent,
                    label="Kimi Code bin parent",
                    max_file_bytes=SOFTWARE_MAX_BYTES,
                    max_paths=16,
                )
            else:
                file_transaction.stage_remove(
                    software_entrypoint(target),
                    label="Kimi Code entrypoint",
                    max_bytes=SOFTWARE_MAX_BYTES,
                )
            file_transaction.stage_remove(
                software_stamp_path(target),
                label=SOFTWARE_STAMP_NAME,
                max_bytes=METADATA_MAX_BYTES,
            )
            tree_transaction.apply_once()
            file_transaction.apply_once()
            verify_removed_software_postcondition(target)
            cleanup_pending = commit_software_transactions(
                target, file_transaction, tree_transaction
            )
        except BaseException as exc:
            rollback_software_transactions(
                target,
                snapshot,
                file_transaction,
                tree_transaction,
                exc,
            )
            raise
        return {
            "changed": True,
            "version": status.get("version"),
            "command": KIMI_COMMAND,
            "executable": str(software_entrypoint(target)),
            "installed_tree": str(software_current(target)),
            "target": str(validate_target(target, create=False)),
            "cleanup_pending": cleanup_pending,
            "cleanup_drained": cleanup_drained,
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
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_size != opened.st_size
        ):
            fail(f"{label} changed while hashing")

        if expected_digest is None or expected_stamp_digest is None:
            stamp = read_software_stamp(target)
            if stamp is None:
                fail(
                    "launch requires current target-owned Kimi Code binary: software stamp is missing"
                )
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


def prepare_launch_invocation_locked(
    target: Path, child_args: list[str], *, host_platform_key: str
) -> LaunchInvocation:
    if cleanup_pending_metadata(target):
        fail("launch requires no cleanup-pending lifecycle state")
    status = _status_payload_locked(target)
    if not status["managed"]:
        fail("launch requires a managed target")
    if status["state"] == "legacy-managed":
        fail("launch refuses legacy managed setup state; run migrate first")
    if status["drift"]:
        fail(f"managed target has drift: {', '.join(status['drift'])}")
    software = _software_status_payload_locked(target)
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
    if platform_key != host_platform_key:
        fail("launch requires current target-owned Kimi Code binary: host platform")
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


def prepare_launch_invocation(
    target: Path, child_args: list[str]
) -> tuple[list[str], dict[str, str]]:
    reject_managed_launch_overrides(child_args)
    host_platform_key = require_supported_product_host().vendor_platform_key
    with target_lock(target):
        drain_cleanup_journal(target)
        invocation = prepare_launch_invocation_locked(
            target, child_args, host_platform_key=host_platform_key
        )
        return invocation.command, invocation.child_env


def launch(target: Path, child_args: list[str]) -> int:
    reject_managed_launch_overrides(child_args)
    host_platform_key = require_supported_product_host().vendor_platform_key
    with target_lock(target):
        drain_cleanup_journal(target)
        invocation = prepare_launch_invocation_locked(
            target, child_args, host_platform_key=host_platform_key
        )
        with protected_launch_path(invocation.target):
            executable = revalidate_launch_executable(
                invocation.target,
                expected_digest=invocation.expected_entrypoint_digest,
                expected_stamp_digest=invocation.stamp_entrypoint_digest,
            )
            try:
                try:
                    completed = subprocess.run(
                        invocation.command, env=invocation.child_env, check=False
                    )
                except FileNotFoundError:
                    fail("target-owned kimi executable is missing")
                return int(completed.returncode)
            finally:
                executable.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_argv = sys.argv[1:] if argv is None else argv
    json_errors = "--json" in raw_argv
    parser = KimicodeArgumentParser(description=__doc__, json_errors=json_errors)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=lambda *args, **kwargs: KimicodeArgumentParser(
            *args,
            json_errors=json_errors,
            **kwargs,
        ),
    )

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")

    for name in ("status", "update", "remove"):
        command = subparsers.add_parser(name)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")

    software_status = subparsers.add_parser("software-status")
    software_status.add_argument("--target", required=True)
    software_status.add_argument("--json", action="store_true")

    for name in ("install-cli", "update-cli", "migrate-cli", "remove-cli"):
        command = subparsers.add_parser(name)
        command.add_argument("--target", required=True)
        command.add_argument("--json", action="store_true")

    plan = subparsers.add_parser("plan")
    plan.add_argument("--setup", default=DEFAULT_CONTENT_SETUP)
    plan.add_argument("--profile", default=DEFAULT_PROFILE)
    plan.add_argument("--target", required=True)
    plan.add_argument("--migrate-legacy", action="store_true")
    plan.add_argument("--json", action="store_true")

    install = subparsers.add_parser("install")
    install.add_argument("--setup", default=DEFAULT_CONTENT_SETUP)
    install.add_argument("--profile", default=DEFAULT_PROFILE)
    install.add_argument("--target", required=True)
    install.add_argument("--json", action="store_true")

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
    launch_parser.add_argument("--json", action="store_true")
    launch_parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "list":
        emit(list_catalog(), as_json=args.json)
        return 0
    if args.command in {
        "status",
        "remove",
        "software-status",
        "install-cli",
        "update-cli",
        "migrate-cli",
        "remove-cli",
        "plan",
        "install",
        "update",
        "switch-profile",
        "migrate",
        "restore",
        "launch",
    }:
        require_supported_product_host()
    if args.command == "status":
        emit(status_payload(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "software-status":
        emit(software_status_payload(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "install-cli":
        emit(
            install_or_update_software(require_absolute_target(args.target), mode="install"),
            as_json=args.json,
        )
        return 0
    if args.command == "update-cli":
        emit(
            install_or_update_software(require_absolute_target(args.target), mode="update"),
            as_json=args.json,
        )
        return 0
    if args.command == "migrate-cli":
        emit(
            install_or_update_software(require_absolute_target(args.target), mode="migrate"),
            as_json=args.json,
        )
        return 0
    if args.command == "remove-cli":
        emit(remove_software(require_absolute_target(args.target)), as_json=args.json)
        return 0
    if args.command == "plan":
        target = require_absolute_target(args.target)
        emit(
            plan_payload(
                target,
                load_content_setup(args.setup),
                load_profile(args.profile),
                migrate_legacy=args.migrate_legacy,
            ),
            as_json=args.json,
        )
        return 0
    if args.command == "install":
        target = require_absolute_target(args.target)
        emit(
            write_setup(target, load_content_setup(args.setup), load_profile(args.profile)),
            as_json=args.json,
        )
        return 0
    if args.command == "update":
        target = require_absolute_target(args.target)
        emit(update_setup(target), as_json=args.json)
        return 0
    if args.command == "switch-profile":
        target = require_absolute_target(args.target)
        emit(
            write_setup(
                target,
                load_content_setup(DEFAULT_CONTENT_SETUP),
                load_profile(args.profile),
                require_existing=True,
                use_current_content_setup=True,
            ),
            as_json=args.json,
        )
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
    try:
        args = parse_args(argv)
        return dispatch(args)
    except KimicodeSetupError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
