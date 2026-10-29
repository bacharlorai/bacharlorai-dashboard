"""
Builds data/linkedin.json from the LinkedIn Page analytics exports you
download by hand (Analytics -> Content / Followers / Visitors -> Export).

Put the .xls files in the  linkedin-exports/  folder of the repository.
Every run reads all of them, so you can keep adding newer exports:
for days that appear in more than one file, the newest file wins.

Until LinkedIn approves API access this is how the LinkedIn tab stays
up to date. It runs as part of the daily refresh.
"""

import glob
import json
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

FOLDER = "linkedin-exports"
OUT = "data/linkedin.json"


def d(v):
    """LinkedIn dates come as MM/DD/YYYY text (UTC)."""
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.date().isoformat()
    return datetime.strptime(str(v).strip(), "%m/%d/%Y").date().isoformat()


def num(v):
    try:
        f = float(v)
        return 0.0 if f != f else f  # NaN -> 0
    except (TypeError, ValueError):
        return 0.0


def read_sheet(path, name):
    try:
        return pd.read_excel(path, sheet_name=name, header=1)
    except Exception:
        return None


# LinkedIn puts a timestamp in each file name, so name order is age order (newest last)
files = sorted(glob.glob(os.path.join(FOLDER, "*.xls*")))
if not files:
    print("No LinkedIn exports found; nothing to do.")
    raise SystemExit(0)

daily, posts, export_date = {}, {}, None
for path in files:
    # ---- Content export: "Metrics" (per day) and "All posts" (per post) ----
    m = read_sheet(path, "Metrics")
    if m is not None and "Impressions (total)" in m.columns:
        for _, r in m.iterrows():
            if pd.isna(r.get("Date")):
                continue
            day = d(r["Date"])
            row = daily.setdefault(day, {"date": day})
            row.update({
                "impressions": int(num(r.get("Impressions (total)"))),
                "uniqueImpressions": int(num(r.get("Unique impressions (organic)"))),
                "clicks": int(num(r.get("Clicks (total)"))),
                "reactions": int(num(r.get("Reactions (total)"))),
                "comments": int(num(r.get("Comments (total)"))),
                "reposts": int(num(r.get("Reposts (total)"))),
            })
            export_date = max(export_date or day, day)
    p = read_sheet(path, "All posts")
    if p is not None and "Post link" in p.columns:
        for _, r in p.iterrows():
            if pd.isna(r.get("Post link")):
                continue
            text = " ".join(str(r.get("Post title") or "").split())
            posts[r["Post link"]] = {
                "text": text[:140] + ("…" if len(text) > 140 else ""),
                "url": r["Post link"], "date": d(r["Created date"]),
                "impressions": int(num(r.get("Impressions"))), "clicks": int(num(r.get("Clicks"))),
                "reactions": int(num(r.get("Likes"))), "comments": int(num(r.get("Comments"))),
                "reposts": int(num(r.get("Reposts"))),
            }
    # Followers and Visitors exports are added here once we have a sample of each.

days = [daily[k] for k in sorted(daily)]
post_list = sorted(posts.values(), key=lambda x: x["date"])
last = date.fromisoformat(days[-1]["date"])
first = date.fromisoformat(days[0]["date"])

ADD = ["impressions", "clicks", "reactions", "comments", "reposts"]


def window(n):
    """(start, end) of the last n days of data; n=None means everything."""
    return (first if n is None else last - timedelta(days=n - 1)), last


def totals(start, end):
    rows = [r for r in days if start.isoformat() <= r["date"] <= end.isoformat()]
    out = {k: sum(r.get(k, 0) for r in rows) for k in ADD}
    out["posts"] = sum(1 for x in post_list if start.isoformat() <= x["date"] <= end.isoformat())
    out["days"] = len(rows)
    return out


ranges = {}
for key, n in {"7d": 7, "30d": 30, "90d": 90, "365d": 365, "all": None}.items():
    start, end = window(n)
    cur = totals(start, end)
    prev = None
    if n:
        ps, pe = start - timedelta(days=n), start - timedelta(days=1)
        if ps >= first:
            prev = totals(ps, pe)
    in_range = [x for x in post_list if start.isoformat() <= x["date"] <= end.isoformat()]
    ranges[key] = {
        "kpis": {"current": cur, "previous": prev},
        "engagementTypes": [{"type": t.capitalize(), "value": cur[t]} for t in ["clicks", "reactions", "comments", "reposts"]],
        "topPosts": sorted(in_range, key=lambda x: -x["impressions"])[:8],
    }

out = {
    "updated": (datetime.combine(last + timedelta(days=1), datetime.min.time()).replace(hour=12, tzinfo=timezone.utc)).isoformat(),
    "source": "export", "dataThrough": last.isoformat(), "dataFrom": first.isoformat(),
    "has": {"content": True, "followers": False, "visitors": False},
    "daily": days, "ranges": ranges, "posts": len(post_list), "audience": {},
}
os.makedirs("data", exist_ok=True)
json.dump(out, open(OUT, "w"), separators=(",", ":"), ensure_ascii=False)
print(f"Saved {OUT}: {len(days)} days ({first} to {last}), {len(post_list)} posts from {len(files)} file(s)")
