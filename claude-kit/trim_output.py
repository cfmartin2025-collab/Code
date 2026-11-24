#!/usr/bin/env python3
"""PostToolUse hook: trim noisy Bash output (installs, builds, test runs)
to error lines + last 30 lines before it enters Claude's context.
Requires a Claude Code build that honors hookSpecificOutput.updatedToolOutput."""
import json, re, sys

TAIL = 30          # lines always kept from the end
MIN_LINES = 60     # don't touch output shorter than this
MAX_ERR = 40       # cap on error lines kept from the trimmed head

NOISY = re.compile(r"\b(npm|pnpm|yarn|npx|pip3?|uv|poetry|cargo|make|cmake|gradle|mvn|"
                   r"dotnet|go\s+(build|test|get|mod)|pytest|jest|vitest|tsc|webpack|vite|"
                   r"apt(-get)?|brew|docker\s+(build|pull|compose)|bundle|gem|composer)\b")
ERR = re.compile(r"(error|fail(ed|ure)?|exception|traceback|fatal|panic|denied|"
                 r"not found|cannot|undefined|E\d{3,}|\bERR!)", re.I)

def main():
    try:
        ev = json.load(sys.stdin)
    except Exception:
        return
    if ev.get("tool_name") != "Bash":
        return
    cmd = (ev.get("tool_input") or {}).get("command", "")
    if not NOISY.search(cmd):
        return
    resp = ev.get("tool_response") or {}
    if not isinstance(resp, dict):
        return
    text = (resp.get("stdout") or "")
    if resp.get("stderr"):
        text += ("\n" if text else "") + resp["stderr"]
    lines = text.splitlines()
    if len(lines) < MIN_LINES:
        return
    head, tail = lines[:-TAIL], lines[-TAIL:]
    errs = [l for l in head if ERR.search(l)][:MAX_ERR]
    out = []
    if errs:
        out += ["[trim_output] error lines from trimmed section:"] + errs
    out += [f"[trim_output] {len(head)} lines trimmed; last {TAIL} follow:"] + tail
    trimmed = dict(resp, stdout="\n".join(out), stderr="")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "updatedToolOutput": trimmed}}))

if __name__ == "__main__":
    main()
