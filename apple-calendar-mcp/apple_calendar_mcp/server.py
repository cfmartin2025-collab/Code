"""
Apple (iCloud) Calendar MCP server.

Talks to iCloud over CalDAV using an app-specific password, so it runs anywhere
(Linux box, Windows, Mac, small VPS) -- no macOS / EventKit dependency.

Transports:
  stdio            -> Claude Desktop / Claude Code (local)
  streamable-http  -> claude.ai custom connector (remote; works from iPhone/iPad)

Config (env vars or .env):
  ICLOUD_USERNAME        Apple ID email
  ICLOUD_APP_PASSWORD    app-specific password (appleid.apple.com -> Sign-In & Security)
  CALDAV_URL             default https://caldav.icloud.com
  CAL_TIMEZONE           default America/Chicago
  CAL_READ_ONLY          "1" disables create/update/delete tools
  CAL_ALLOWED_CALENDARS  optional comma list; restricts which calendars are visible
  MCP_PATH_TOKEN         (HTTP only) secret path segment -> https://host/<token>/mcp
  MCP_PUBLIC_HOST        (HTTP only) public hostname when behind a tunnel/proxy, e.g. cal.example.com
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import caldav
from icalendar import Calendar as ICal
from icalendar import Event as IEvent
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations


def _load_dotenv() -> None:
    """Minimal .env loader (no extra dependency).

    Search order: $APPLE_CAL_ENV_FILE, ./.env, then the project folder's .env
    (Claude Desktop does not launch the server from the install folder).
    """
    project_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    for path in (os.environ.get("APPLE_CAL_ENV_FILE", ""), os.path.join(os.getcwd(), ".env"), project_env):
        if path and os.path.isfile(path):
            break
    else:
        return
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

CALDAV_URL = os.environ.get("CALDAV_URL", "https://caldav.icloud.com")
USERNAME = os.environ.get("ICLOUD_USERNAME", "")
PASSWORD = os.environ.get("ICLOUD_APP_PASSWORD", "")
TZ = ZoneInfo(os.environ.get("CAL_TIMEZONE", "America/Chicago"))
READ_ONLY = os.environ.get("CAL_READ_ONLY", "0").lower() in ("1", "true", "yes")
ALLOWED = {c.strip().lower() for c in os.environ.get("CAL_ALLOWED_CALENDARS", "").split(",") if c.strip()}

mcp = MCPServer(
    name="apple-calendar",
    instructions=(
        "Access to the user's Apple iCloud calendars. Times are interpreted in "
        f"{TZ.key} unless an explicit offset is given. Always call list_events before "
        "update_event/delete_event to get the event uid. Confirm with the user before deleting."
    ),
)

# --------------------------------------------------------------------------- #
# CalDAV connection (lazy, cached, thread-safe)
# --------------------------------------------------------------------------- #
_lock = threading.Lock()
_principal: caldav.Principal | None = None


def _get_principal() -> caldav.Principal:
    global _principal
    with _lock:
        if _principal is None:
            if not USERNAME or not PASSWORD:
                raise RuntimeError("ICLOUD_USERNAME / ICLOUD_APP_PASSWORD not set")
            client = caldav.DAVClient(url=CALDAV_URL, username=USERNAME, password=PASSWORD, timeout=30)
            _principal = client.principal()
        return _principal


def _calendars() -> list[caldav.Calendar]:
    cals = []
    for c in _get_principal().calendars():
        # Skip reminder (VTODO-only) lists that iCloud exposes as calendars
        try:
            comps = c.get_supported_components()
            if comps and "VEVENT" not in comps:
                continue
        except Exception:
            pass
        name = c.get_display_name() or ""
        if ALLOWED and name.lower() not in ALLOWED:
            continue
        cals.append(c)
    return cals


def _find_calendar(name: str | None) -> caldav.Calendar:
    cals = _calendars()
    if not cals:
        raise ValueError("No event calendars found on this account")
    if not name:
        return cals[0]
    for c in cals:
        if (c.get_display_name() or "").lower() == name.lower():
            return c
    raise ValueError(f"Calendar '{name}' not found. Available: {[c.get_display_name() for c in cals]}")


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def _parse_dt(value: str) -> datetime:
    """Accept 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM[:SS]' (local TZ) or with offset/Z."""
    v = value.strip().replace("Z", "+00:00")
    if len(v) == 10:
        return datetime.combine(date.fromisoformat(v), time.min, TZ)
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def _fmt(v: Any) -> str:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=TZ)
        return v.astimezone(TZ).isoformat(timespec="minutes")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _event_to_dict(comp: IEvent, cal_name: str) -> dict[str, Any]:
    start = comp.get("dtstart").dt if comp.get("dtstart") else None
    end = comp.get("dtend").dt if comp.get("dtend") else None
    if end is None and start is not None and comp.get("duration"):
        end = start + comp.get("duration").dt
    all_day = isinstance(start, date) and not isinstance(start, datetime)
    out: dict[str, Any] = {
        "uid": str(comp.get("uid", "")),
        "calendar": cal_name,
        "title": str(comp.get("summary", "")),
        "start": _fmt(start) if start else None,
        "end": _fmt(end) if end else None,
        "all_day": all_day,
    }
    for key, field in (("location", "location"), ("notes", "description")):
        if comp.get(field):
            out[key] = str(comp.get(field))
    if comp.get("rrule") or comp.get("recurrence-id"):
        out["recurring"] = True
    return out


def _sort_key(e: dict) -> str:
    return e["start"] or ""


def _expanded_events(cal: caldav.Calendar, start: datetime, end: datetime) -> list[dict]:
    """Search a calendar and return individual (recurrence-expanded) occurrences."""
    name = cal.get_display_name() or ""
    results = cal.search(event=True, start=start, end=end, expand=True)
    out = []
    for obj in results:
        ical = ICal.from_ical(obj.data)
        for comp in ical.walk("VEVENT"):
            out.append(_event_to_dict(comp, name))
    return out


def _find_event_obj(uid: str, calendar: str | None) -> tuple[caldav.Calendar, caldav.Event]:
    cals = [_find_calendar(calendar)] if calendar else _calendars()
    for c in cals:
        try:
            return c, c.event_by_uid(uid)
        except caldav.lib.error.NotFoundError:
            continue
    raise ValueError(f"No event with uid '{uid}'")


def _require_write() -> None:
    if READ_ONLY:
        raise PermissionError("Server is in read-only mode (CAL_READ_ONLY=1)")


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
RO = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)


@mcp.tool(annotations=RO)
def list_calendars() -> list[dict]:
    """List the user's iCloud event calendars."""
    return [{"name": c.get_display_name(), "url": str(c.url)} for c in _calendars()]


@mcp.tool(annotations=RO)
def list_events(start: str | None = None, end: str | None = None, calendar: str | None = None) -> list[dict]:
    """List events (recurring events expanded) between start and end.

    start/end: ISO date or datetime ('2026-11-17' or '2026-11-17T08:00'). Defaults: today -> +7 days.
    calendar: calendar name; omit for all calendars.
    """
    s = _parse_dt(start) if start else datetime.combine(date.today(), time.min, TZ)
    e = _parse_dt(end) if end else s + timedelta(days=7)
    if e <= s:
        raise ValueError("end must be after start")
    if (e - s).days > 366:
        raise ValueError("Range too large; keep it to 1 year or less")
    cals = [_find_calendar(calendar)] if calendar else _calendars()
    events: list[dict] = []
    for c in cals:
        events.extend(_expanded_events(c, s, e))
    return sorted(events, key=_sort_key)


@mcp.tool(annotations=RO)
def search_events(query: str, start: str | None = None, end: str | None = None) -> list[dict]:
    """Case-insensitive text search over title, location and notes.

    Defaults to a window of 90 days back through 365 days forward.
    """
    today = datetime.combine(date.today(), time.min, TZ)
    s = _parse_dt(start) if start else today - timedelta(days=90)
    e = _parse_dt(end) if end else today + timedelta(days=365)
    q = query.lower()
    hits = []
    for c in _calendars():
        for ev in _expanded_events(c, s, e):
            blob = " ".join(str(ev.get(k, "")) for k in ("title", "location", "notes")).lower()
            if q in blob:
                hits.append(ev)
    return sorted(hits, key=_sort_key)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True))
def create_event(
    title: str,
    start: str,
    end: str | None = None,
    calendar: str | None = None,
    all_day: bool = False,
    location: str | None = None,
    notes: str | None = None,
    alert_minutes_before: int | None = None,
) -> dict:
    """Create an event.

    start/end: ISO datetime in local time unless offset given. end defaults to start + 1h
    (or +1 day for all_day). For all_day, pass dates ('2026-11-20'); end is exclusive.
    calendar: omit to use the first/default calendar.
    """
    _require_write()
    cal = _find_calendar(calendar)
    ev = IEvent()
    ev.add("uid", f"{uuid.uuid4()}@apple-calendar-mcp")
    ev.add("summary", title)
    ev.add("dtstamp", datetime.now(tz=ZoneInfo("UTC")))
    if all_day:
        s = date.fromisoformat(start[:10])
        e = date.fromisoformat(end[:10]) if end else s + timedelta(days=1)
    else:
        s = _parse_dt(start)
        e = _parse_dt(end) if end else s + timedelta(hours=1)
    if e <= s:
        raise ValueError("end must be after start")
    ev.add("dtstart", s)
    ev.add("dtend", e)
    if location:
        ev.add("location", location)
    if notes:
        ev.add("description", notes)
    if alert_minutes_before is not None:
        from icalendar import Alarm
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", title)
        alarm.add("trigger", timedelta(minutes=-abs(alert_minutes_before)))
        ev.add_component(alarm)
    ical = ICal()
    ical.add("prodid", "-//apple-calendar-mcp//EN")
    ical.add("version", "2.0")
    ical.add_component(ev)
    cal.save_event(ical.to_ical().decode())
    return _event_to_dict(ev, cal.get_display_name() or "")


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True))
def update_event(
    uid: str,
    calendar: str | None = None,
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> dict:
    """Update fields on an existing event (by uid from list_events). Only provided fields change.

    For a recurring event this edits the whole series. If only start is moved, duration is preserved.
    """
    _require_write()
    cal, obj = _find_event_obj(uid, calendar)
    ical = ICal.from_ical(obj.data)
    # Master VEVENT = the one without RECURRENCE-ID
    master = next(c for c in ical.walk("VEVENT") if not c.get("recurrence-id"))

    old_s = master.get("dtstart").dt
    old_e = master.get("dtend").dt if master.get("dtend") else None
    duration = (old_e - old_s) if old_e is not None else None

    def _set(key: str, val: Any) -> None:
        if key in master:
            del master[key]
        master.add(key, val)

    if title is not None:
        _set("summary", title)
    if location is not None:
        _set("location", location)
    if notes is not None:
        _set("description", notes)
    if start is not None:
        new_s = date.fromisoformat(start[:10]) if not isinstance(old_s, datetime) else _parse_dt(start)
        _set("dtstart", new_s)
        if end is None and duration is not None:
            _set("dtend", new_s + duration)
    if end is not None:
        cur_s = master.get("dtstart").dt
        new_e = date.fromisoformat(end[:10]) if not isinstance(cur_s, datetime) else _parse_dt(end)
        if new_e <= cur_s:
            raise ValueError("end must be after start")
        if "duration" in master:
            del master["duration"]
        _set("dtend", new_e)
    _set("dtstamp", datetime.now(tz=ZoneInfo("UTC")))
    seq = int(master.get("sequence", 0)) + 1
    _set("sequence", seq)

    obj.data = ical.to_ical().decode()
    obj.save()
    return _event_to_dict(master, cal.get_display_name() or "")


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True))
def delete_event(uid: str, calendar: str | None = None) -> dict:
    """Delete an event by uid. Deletes the entire series for recurring events. Confirm with user first."""
    _require_write()
    cal, obj = _find_event_obj(uid, calendar)
    obj.delete()
    return {"deleted": uid, "calendar": cal.get_display_name()}


if READ_ONLY:
    for _name in ("create_event", "update_event", "delete_event"):
        mcp.remove_tool(_name)


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(description="Apple iCloud Calendar MCP server")
    p.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    p.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    p.add_argument("--check", action="store_true", help="test iCloud login, list calendars, exit")
    args = p.parse_args()

    if args.check:
        sys.stdout.reconfigure(errors="replace")  # Windows console vs emoji calendar names
        try:
            cals = _calendars()
        except Exception as exc:  # noqa: BLE001 - show the user whatever went wrong
            print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"OK - logged in as {USERNAME}, {len(cals)} calendar(s):")
        for c in cals:
            print(f"  - {c.get_display_name()}")
        try:
            n = len(list_events())
            print(f"  {n} event(s) in the next 7 days")
        except Exception as exc:  # noqa: BLE001
            print(f"  (event read failed: {exc})", file=sys.stderr)
        sys.exit(0)

    if not args.http:
        mcp.run("stdio")
        return

    token = os.environ.get("MCP_PATH_TOKEN", "")
    if len(token) < 24:
        sys.exit(
            "Refusing to serve HTTP without MCP_PATH_TOKEN (>=24 chars). Your calendar would be public.\n"
            f"Generate one:  MCP_PATH_TOKEN={secrets.token_urlsafe(32)}"
        )
    path = f"/{token}/mcp"
    # DNS-rebinding protection: allow localhost plus the public hostname the tunnel/proxy forwards.
    from mcp.server.transport_security import TransportSecuritySettings
    hosts = ["127.0.0.1:*", "localhost:*", "127.0.0.1", "localhost"]
    public = os.environ.get("MCP_PUBLIC_HOST", "").strip()
    if public:
        hosts += [public, f"{public}:*"]
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[])
    print(f"Serving on http://{args.host}:{args.port}/<MCP_PATH_TOKEN>/mcp", file=sys.stderr)
    mcp.run("streamable-http", host=args.host, port=args.port, streamable_http_path=path, stateless_http=True,
            transport_security=security)


if __name__ == "__main__":
    main()
