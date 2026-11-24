# CLAUDE.md

## Token guard
- Be concise. Lead with the answer; no preamble, no recap of what you just did.
- Route BULK mechanical work (rename/format across many files, summarize long docs,
  scrape many pages) to a sub-agent with `model: haiku`. Do small one-off edits inline:
  a sub-agent cold-starts with its own preload and costs more than a 3-line change.
- Never suggest /compact as a cost-saving measure. It rewrites the cached prefix and
  forces a full-price cache rebuild. Suggest /clear between unrelated jobs instead.
- Don't switch models or effort mid-session.
- Don't re-read files already in context; read only the line ranges you need.

## Repo
- `apple-calendar-mcp/` — Apple iCloud Calendar MCP server (CalDAV, stdio + remote HTTP).
- `claude-kit/` — portable Claude Code token-efficiency kit (hooks, statusline, installer).
