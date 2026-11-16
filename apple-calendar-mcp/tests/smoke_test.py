"""Smoke test against a local Radicale CalDAV server.

  pip install radicale
  echo "u:x" > users && python -m radicale --server-hosts 127.0.0.1:5232 \\
      --auth-type htpasswd --auth-htpasswd-filename users --auth-htpasswd-encryption plain
  python tests/smoke_test.py
"""
import os, sys, asyncio, functools, json
os.environ.update(CALDAV_URL="http://127.0.0.1:5232/", ICLOUD_USERNAME="u", ICLOUD_APP_PASSWORD="x")
import caldav
caldav.DAVClient.__init__ = functools.partialmethod(caldav.DAVClient.__init__, require_tls=False)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from apple_calendar_mcp import server as s
async def call(name, **kw):
    r = await s.mcp.call_tool(name, kw)
    print(f"--- {name} {kw}\n", r if not isinstance(r, tuple) else r[1], "\n")
    return r
async def main():
    p = s._get_principal()
    have = {c.get_display_name() for c in p.calendars()}
    for n in ("Work", "Home"):
        if n not in have:
            p.make_calendar(name=n)
    print([t.name for t in await s.mcp.list_tools()])
    await call("list_calendars")
    await call("create_event", title="Wellsite 12 commissioning", start="2026-11-18T08:00", end="2026-11-18T12:00", calendar="Work", location="Midland", alert_minutes_before=30)
    await call("create_event", title="Thanksgiving", start="2026-11-26", all_day=True, calendar="Home")
    # recurring via raw ical
    cal = s._find_calendar("Work")
    cal.save_event("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:rec1\nDTSTAMP:20261101T000000Z\nDTSTART;TZID=America/Chicago:20261116T070000\nDTEND;TZID=America/Chicago:20261116T071500\nRRULE:FREQ=DAILY;COUNT=5\nSUMMARY:Morning standup\nEND:VEVENT\nEND:VCALENDAR\n")
    r = await call("list_events", start="2026-11-16", end="2026-11-30")
    await call("search_events", query="wellsite")
    ev = s.search_events("wellsite")[0]
    await call("update_event", uid=ev["uid"], start="2026-11-19T09:00", title="Wellsite 12 commissioning (moved)")
    await call("delete_event", uid="rec1")
    await call("list_events", start="2026-11-16", end="2026-11-30")
asyncio.run(main())
