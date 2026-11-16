# apple-calendar-mcp

MCP server that gives Claude read/write access to your **Apple iCloud Calendar** over CalDAV.
No Mac required; it runs on Windows, Linux, a Pi or a $5 VPS.

| Tool | What it does |
|---|---|
| `list_calendars` | Lists iCloud event calendars (Reminders lists are filtered out) |
| `list_events` | Events in a date range; recurring events are expanded to individual occurrences |
| `search_events` | Text search across title, location and notes |
| `create_event` | Timed or all-day events, with optional location, notes and alert |
| `update_event` | Changes only the fields you pass; moving the start keeps the duration |
| `delete_event` | Deletes an event (the whole series for recurring events) |

Set `CAL_READ_ONLY=1` and the three write tools aren't registered at all.

---

## 1. Get an app-specific password

Your normal Apple ID password won't work over CalDAV.

1. Go to **appleid.apple.com**, then **Sign-In and Security**, then **App-Specific Passwords**.
2. Generate one named `claude-calendar`.
3. Copy `.env.example` to `.env` and fill in `ICLOUD_USERNAME` and `ICLOUD_APP_PASSWORD`.

To revoke access later, delete that app-specific password. That cuts off the server immediately.

## 2. Install

```bash
cd apple-calendar-mcp
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e .
```

---

## Option A: Local (Claude Desktop / Claude Code)

**Windows, the fast way:** download this repo as a ZIP, extract it, and double-click
`apple-calendar-mcp\windows\install.cmd`. It installs Python if needed, builds a venv in
`%LOCALAPPDATA%\apple-calendar-mcp`, asks for your Apple ID and app password, tests the login,
adds the server to Claude Desktop's config (after making a backup), and restarts Claude Desktop.
Your credentials go in a `.env` file only your Windows user can read, never in the Claude config.
To remove everything, run `install.cmd -Uninstall`.

The manual steps follow.

Runs only while the PC is on. Takes about 5 minutes.

**Claude Desktop**: open Settings, then Developer, then Edit Config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "apple-calendar": {
      "command": "C:\\path\\to\\apple-calendar-mcp\\.venv\\Scripts\\apple-calendar-mcp.exe",
      "env": {
        "ICLOUD_USERNAME": "you@icloud.com",
        "ICLOUD_APP_PASSWORD": "xxxx-xxxx-xxxx-xxxx",
        "CAL_TIMEZONE": "America/Chicago"
      }
    }
  }
}
```

On macOS/Linux, the command path is `/path/to/apple-calendar-mcp/.venv/bin/apple-calendar-mcp`. Restart Claude Desktop afterward.

**Claude Code**:

```bash
claude mcp add apple-calendar \
  -e ICLOUD_USERNAME=you@icloud.com -e ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx \
  -- /path/to/.venv/bin/apple-calendar-mcp
```

## Option B: Remote connector (works from iPhone / iPad / claude.ai)

claude.ai custom connectors need a public HTTPS URL. The server runs in HTTP mode behind a
Cloudflare Tunnel, so you don't open any ports on your router.

```bash
# In .env, set both of these:
MCP_PATH_TOKEN=<output of: python -c "import secrets; print(secrets.token_urlsafe(32))">
MCP_PUBLIC_HOST=cal.yourdomain.com

apple-calendar-mcp --http --port 8000          # binds 127.0.0.1 only
cloudflared tunnel --url http://127.0.0.1:8000 # quick test; use a named tunnel for permanent
```

Then in claude.ai, go to **Settings**, then **Connectors**, then **Add custom connector**:

```
https://cal.yourdomain.com/<MCP_PATH_TOKEN>/mcp
```

The connector syncs to the Claude iOS app automatically.

**Security model:** the token in the URL is the only credential. Anyone who has that URL can use
your calendar, so treat it like a password. The server won't start in HTTP mode without a token
of at least 24 characters. Requests with any other `Host` header get a 421 (DNS-rebinding
protection). For stronger security, put Cloudflare Access in front of the tunnel, or set
`CAL_READ_ONLY=1` if you only need Claude to read.

For quick tunnels (`trycloudflare.com`, which gives a random hostname on every start), set
`MCP_PUBLIC_HOST` to that hostname each time. A named tunnel on your own domain avoids this.

---

## Config reference

| Var | Default | Notes |
|---|---|---|
| `ICLOUD_USERNAME` | (none) | Apple ID email |
| `ICLOUD_APP_PASSWORD` | (none) | App-specific password |
| `CALDAV_URL` | `https://caldav.icloud.com` | Any CalDAV server works (Fastmail, Nextcloud, Radicale) |
| `CAL_TIMEZONE` | `America/Chicago` | Times without an offset are read in this zone |
| `CAL_READ_ONLY` | `0` | `1` = read-only |
| `CAL_ALLOWED_CALENDARS` | all | Comma list, e.g. `Work,Family`; hides the rest from Claude |
| `MCP_PATH_TOKEN` | (none) | Required for `--http` |
| `MCP_PUBLIC_HOST` | (none) | Tunnel/proxy hostname |

## Known limits

- **Recurring events:** update and delete act on the **whole series**. Editing a single
  occurrence isn't implemented yet.
- **Shared calendars** owned by someone else show up if iCloud exposes them to your account.
  Whether you can write to them depends on the share permissions.
- **Invites:** attendees and RSVPs aren't handled.

## Test

`tests/smoke_test.py` runs every tool against a local Radicale CalDAV server. The instructions are
in the file header.
