# claude-kit — token-efficiency kit

| File | What it does |
|---|---|
| `trim_output.py` | PostToolUse hook: Bash output from installs/builds/tests over 60 lines is cut to error lines + last 30. |
| `statusline.py` | Statusline: `model \| ctx % \| $cost`. Terminal CLI only (not shown in the iOS/web app). |
| `install.ps1` | Windows installer: copies both to `~/.claude/hooks`, merges into `~/.claude/settings.json` (backs it up first). |

Requires a Claude Code build that supports `updatedToolOutput` in PostToolUse hooks
(verified on 2.1.x in cloud sessions). If your PC build is older, the hook is a harmless no-op.

Tune in `trim_output.py`: `TAIL`, `MIN_LINES`, `MAX_ERR`, and the `NOISY` command regex.
Commands you want full output from (e.g. a single failing test): run them without the
tool name the regex matches, or temporarily raise `MIN_LINES`.
