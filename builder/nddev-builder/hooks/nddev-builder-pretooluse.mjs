#!/usr/bin/env node
const chunks = [];
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => chunks.push(chunk));
process.stdin.on("end", () => {
  let payload = {};
  try {
    payload = JSON.parse(chunks.join("") || "{}");
  } catch {
    process.exit(0);
  }
  const command = String(payload.command || payload.tool_input?.command || "");
  if (/\brm\s+-rf\b/.test(command) || /^\s*sudo\b/.test(command)) {
    console.error("nddev-builder blocks destructive shell command patterns in managed setups");
    process.exit(2);
  }
  process.exit(0);
});
