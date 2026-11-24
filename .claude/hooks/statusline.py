#!/usr/bin/env python3
"""Statusline: model | context % | session cost. Reads Claude Code's statusline JSON on stdin."""
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("statusline: no data"); sys.exit(0)
model = (d.get("model") or {}).get("display_name") or (d.get("model") or {}).get("id", "?")
ctx = (d.get("context_window") or {}).get("used_percentage")
cost = (d.get("cost") or {}).get("total_cost_usd")
ctx_s = f"{ctx:.0f}%" if isinstance(ctx, (int, float)) else "--"
cost_s = f"${cost:.2f}" if isinstance(cost, (int, float)) else "$--"
print(f"{model} | ctx {ctx_s} | {cost_s}")
