#!/usr/bin/env python3
"""Validate public nddev-kimicode-app release contracts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import tempfile
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
    if contract["safety"].get("launch_revalidates_executable_before_handoff") is not True:
        raise ValueError("contract must state launch revalidates the executable before handoff")
    runtime_launch = contract["runtime_launch"]
    if runtime_launch.get("pre_login_supported") is not True:
        raise ValueError("contract must keep pre-login launch supported")
    if "child process completion" not in runtime_launch.get("lifecycle_lock_scope", ""):
        raise ValueError("contract must document launch lock scope through child completion")
    if "pinned official-binary digest" not in runtime_launch.get("pre_handoff_executable_revalidation", ""):
        raise ValueError("contract must document pinned digest revalidation before launch handoff")
    if manifest.get("runtime_launch") != {
        "holds_lifecycle_lock_through_child": True,
        "pre_handoff_executable_revalidation": True,
        "runtime_dirs_private": True,
    }:
        raise ValueError("manifest must expose launch lock and executable revalidation facts")
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


def write_stub_software(manager: Any, target: Path) -> None:
    platform_key = "linux-x64"
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


def validate_runtime_regressions() -> None:
    manager = load_manager()
    manager_text = (ROOT / "cli-tools" / "nddev_kimicode.py").read_text(encoding="utf-8")
    for forbidden in ("NDDEV_KIMICODE_TEST", "ENABLE_TEST_OVERRIDES"):
        if forbidden in manager_text:
            raise ValueError("manager must not expose public test environment switches")
    for required in (
        "with target_lock(target):\n        command, child_env = prepare_launch_invocation_locked",
        "is_current_owner(opened)",
        "opened.st_dev != info.st_dev or opened.st_ino != info.st_ino",
        "target-owned Kimi Code entrypoint digest does not match pinned binary",
    ):
        if required not in manager_text:
            raise ValueError(f"manager is missing launch hardening fragment: {required}")
    validate_status_launch_allowed_regression(manager)
    validate_corrupt_backup_regression(manager)
    validate_launch_lock_concurrency_regression(manager)
    validate_launch_pre_handoff_swap_regression(manager)
    validate_launch_executable_error_regression(manager)
    validate_launch_boundary_regression(manager)


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
            observed_mutation_failure: str | None = None

            def fake_run(command: list[str], *, env: dict[str, str], check: bool) -> SimpleNamespace:
                nonlocal observed_mutation_failure
                if not lock.is_dir():
                    raise ValueError("launch lifecycle lock was not held during child execution")
                if command[0] != str(target / "bin" / manager.KIMI_COMMAND):
                    raise ValueError("launch did not hand off to the target-owned executable")
                if env.get("KIMI_CODE_HOME") != str(target.resolve()):
                    raise ValueError("launch child environment is not target-scoped")
                try:
                    manager.write_setup(
                        target,
                        manager.load_content_setup(manager.DEFAULT_CONTENT_SETUP),
                        manager.load_profile("safe"),
                        require_existing=True,
                    )
                except manager.KimicodeSetupError as exc:
                    observed_mutation_failure = str(exc)
                else:
                    raise ValueError("lifecycle mutation succeeded while launch child was running")
                return SimpleNamespace(returncode=23)

            manager.subprocess.run = fake_run
            exit_code = manager.launch(target, ["--version"])
            if exit_code != 23:
                raise ValueError("launch did not forward child exit code under lifecycle lock")
            if observed_mutation_failure is None or "target is locked" not in observed_mutation_failure:
                raise ValueError("concurrent lifecycle mutation did not fail on target lock")
            if lock.exists():
                raise ValueError("launch lifecycle lock was not cleaned up after child completion")
        finally:
            manager.subprocess.run = original_run
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
        original_status = manager.software_status_payload
        original_run = manager.subprocess.run
        try:
            write_stub_software(manager, target)
            entrypoint = target / "bin" / manager.KIMI_COMMAND
            current_results = 0
            swapped = False

            def wrapped_status(status_target: Path) -> dict[str, Any]:
                nonlocal current_results, swapped
                result = original_status(status_target)
                if Path(status_target).resolve() == target.resolve() and result.get("current"):
                    current_results += 1
                    if current_results == 2 and not swapped:
                        entrypoint.write_bytes(b"#!/bin/sh\nprintf 'swapped\\n'\n")
                        entrypoint.chmod(0o700)
                        swapped = True
                return result

            def fake_run(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
                raise ValueError("launch spawned a swapped target-owned executable")

            manager.software_status_payload = wrapped_status
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
            manager.software_status_payload = original_status
            manager.KIMI_BINARY_PLATFORMS = original_platforms
    finally:
        temp.cleanup()


def expect_revalidation_rejected(manager: Any, target: Path, expected: str) -> None:
    try:
        manager.revalidate_launch_executable(target)
    except manager.KimicodeSetupError as exc:
        if expected not in str(exc):
            raise ValueError(f"launch executable revalidation returned unstable error: {exc}") from exc
        return
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
    for flag in ("--config", "--profile", "--settings"):
        if flag in manager.FORBIDDEN_LAUNCH_FLAGS or flag in manager.FORBIDDEN_LAUNCH_VALUE_FLAGS:
            raise ValueError(f"launch boundary must not invent unsupported upstream flag: {flag}")
        manager.reject_managed_launch_overrides([flag])
    expect_launch_rejected(manager, ["-C"], "launch flag is managed by nddev-kimicode-app: -C")
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


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    validate_catalog()
    validate_metadata()
    validate_builder_toolkit()
    validate_runtime_regressions()
    validate_workflows()
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"validate_public_contracts.py: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
