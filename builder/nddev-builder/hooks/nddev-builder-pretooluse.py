#!/usr/bin/env python3
"""Kimi PreToolUse hook for NDDev target-owned setup state."""

from __future__ import annotations

import json
import re
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input")
    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or "")
    if not command:
        command = str(payload.get("command") or "")
    if re.search(r"\brm\s+-rf\s+/(?:\s|$)", command) or re.match(r"\s*sudo(?:\s|$)", command):
        print("nddev-builder blocks destructive shell command patterns in managed setups", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
