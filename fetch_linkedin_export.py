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


def read_sheet_h0(path, name):
    try:
        return pd.read_excel(path, sheet_name=name, header=0)
    except Exception:
        return None


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
audience, visitor_audience, competitors, has = {}, {}, None, {"content": False, "followers": False, "visitors": False}

# LinkedIn gives locations as metro areas ("Greater Toronto Area, Canada, Canada").
# The country is the last part; US metros carry no country at all.
def country_of(loc):
    loc = str(loc).strip()
    if loc in ("Singapore", "Hong Kong"):
        return loc
    if loc.startswith("Hong Kong"):
        return "Hong Kong"
    last = loc.split(",")[-1].strip() if "," in loc else ""
    # no country part, or a US state/metro in that position ("Austin, Texas Metropolitan Area")
    if not last or any(w in last for w in ("Area", "Metro", "Region")):
        return "United States"
    return last


def demo_lists(path, kind):
    """Location / Job function / Seniority / Industry / Company size sheets."""
    out = {}
    for sheet, key in [("Location", "locations"), ("Job function", "jobFunction"), ("Seniority", "seniority"),
                       ("Industry", "industry"), ("Company size", "companySize")]:
        try:
            df = pd.read_excel(path, sheet_name=sheet)
        except Exception:
            continue
        rows = [{"label": str(r.iloc[0]).strip(), kind: int(num(r.iloc[1]))} for _, r in df.iterrows() if not pd.isna(r.iloc[0])]
        out[key] = sorted(rows, key=lambda x: -x[kind])
    if "locations" in out:
        by_country = {}
        for r in out["locations"]:
            c = country_of(r["label"])
            by_country[c] = by_country.get(c, 0) + r[kind]
        out["countries"] = sorted(({"country": c, kind: v} for c, v in by_country.items()), key=lambda x: -x[kind])
    if "companySize" in out:  # employee bands read better small to large
        order = ["1", "2-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"]
        out["companySize"].sort(key=lambda x: order.index(x["label"]) if x["label"] in order else 99)
    return out
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
        has["content"] = True
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
    # ---- Followers export: "New followers" (per day) plus follower demographics ----
    nf = read_sheet_h0(path, "New followers")
    if nf is not None and "Total followers" in nf.columns:
        for _, r in nf.iterrows():
            if pd.isna(r.get("Date")):
                continue
            day = d(r["Date"])
            daily.setdefault(day, {"date": day})["newFollowers"] = int(num(r.get("Total followers")))
        audience = demo_lists(path, "followers")
        has["followers"] = True
    # ---- Visitors export: "Visitor metrics" (per day) plus visitor demographics ----
    vm = read_sheet_h0(path, "Visitor metrics")
    if vm is not None and "Total page views (total)" in vm.columns:
        for _, r in vm.iterrows():
            if pd.isna(r.get("Date")):
                continue
            day = d(r["Date"])
            row = daily.setdefault(day, {"date": day})
            tot = int(num(r.get("Total page views (total)")))
            ov, life, jobs = (int(num(r.get(f"{s} page views (total)"))) for s in ("Overview", "Life", "Jobs"))
            row.update({"pageViews": tot, "uniqueVisitors": int(num(r.get("Total unique visitors (total)"))),
                        "pvDesktop": int(num(r.get("Total page views (desktop)"))), "pvMobile": int(num(r.get("Total page views (mobile)"))),
                        "pvOverview": ov, "pvLife": life, "pvJobs": jobs, "pvOther": max(0, tot - ov - life - jobs)})
        visitor_audience = demo_lists(path, "views")
        has["visitors"] = True
    # ---- Competitor analytics export (one snapshot for a date range) ----
    try:
        cp = pd.read_excel(path, sheet_name="COMPETITORS", header=None)
        start_c, end_c = d(cp.iloc[0, 0]), d(cp.iloc[0, 1])
        cols = [str(c).strip() for c in cp.iloc[1]]
        competitors = {"from": start_c, "to": end_c, "pages": [
            {cols[i]: (str(v).strip() if i == 0 else num(v)) for i, v in enumerate(r)} for _, r in cp.iloc[2:].iterrows() if not pd.isna(r.iloc[0])]}
    except Exception:
        pass

days = [daily[k] for k in sorted(daily)]
post_list = sorted(posts.values(), key=lambda x: x["date"])
last = date.fromisoformat(days[-1]["date"])
first = date.fromisoformat(days[0]["date"])

ADD = ["impressions", "clicks", "reactions", "comments", "reposts", "newFollowers", "pageViews", "uniqueVisitors",
       "pvDesktop", "pvMobile", "pvOverview", "pvLife", "pvJobs", "pvOther"]

# The exports give new followers per day but not the total, so the total comes from
# linkedin-exports/page-settings.json ({"followers": 1950, "followersAsOf": "2026-10-28"}).
settings_path = os.path.join(FOLDER, "page-settings.json")
settings = json.load(open(settings_path)) if os.path.exists(settings_path) else {}
F, F_AS_OF = settings.get("followers"), settings.get("followersAsOf")
if F and has["followers"]:
    # walk backwards from the known total: followers at the end of each day
    running = F - sum(r.get("newFollowers", 0) for r in days if r["date"] > (F_AS_OF or "9999"))
    for r in reversed(days):
        r["followers"] = running
        running -= r.get("newFollowers", 0)


def window(n):
    """(start, end) of the last n days of data; n=None means everything."""
    return (first if n is None else last - timedelta(days=n - 1)), last


def totals(start, end):
    rows = [r for r in days if start.isoformat() <= r["date"] <= end.isoformat()]
    out = {k: sum(r.get(k, 0) for r in rows) for k in ADD}
    out["posts"] = sum(1 for x in post_list if start.isoformat() <= x["date"] <= end.isoformat())
    out["days"] = len(rows)
    if rows and "followers" in rows[-1]:
        out["followers"] = rows[-1]["followers"]
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
        "sections": [{"section": s, "views": cur[k]} for s, k in [("Overview", "pvOverview"), ("Jobs", "pvJobs"), ("Life", "pvLife"),
                     ("Other tabs (About, People, Posts…)", "pvOther")] if cur[k]],
        "devices": [{"device": "Desktop", "views": cur["pvDesktop"]}, {"device": "Mobile", "views": cur["pvMobile"]}],
    }

out = {
    "updated": (datetime.combine(last + timedelta(days=1), datetime.min.time()).replace(hour=12, tzinfo=timezone.utc)).isoformat(),
    "source": "export", "dataThrough": last.isoformat(), "dataFrom": first.isoformat(),
    "has": {**has, "followersTotal": bool(F and has["followers"])},
    "daily": days, "ranges": ranges, "posts": len(post_list), "audience": audience, "visitorAudience": visitor_audience,
    "competitors": competitors, "followersAsOf": F_AS_OF,
}
os.makedirs("data", exist_ok=True)
json.dump(out, open(OUT, "w"), separators=(",", ":"), ensure_ascii=False)
print(f"Saved {OUT}: {len(days)} days ({first} to {last}), {len(post_list)} posts from {len(files)} file(s)")
