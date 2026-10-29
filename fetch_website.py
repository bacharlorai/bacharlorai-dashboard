"""
Pulls BacharLorai website analytics from Google Analytics 4
and saves them to data/website.json for the dashboard.

Runs every morning via GitHub Actions. Needs two secrets:
  GA4_CREDENTIALS  - the full contents of the service account .json key
  GA4_PROPERTY_ID  - the GA4 property number (561298290)
"""

import json
import os
from datetime import datetime, timezone

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunReportRequest,
)
from google.oauth2 import service_account

PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "561298290")
creds = service_account.Credentials.from_service_account_info(
    json.loads(os.environ["GA4_CREDENTIALS"]),
    scopes=["https://www.googleapis.com/auth/analytics.readonly"],
)
client = BetaAnalyticsDataClient(credentials=creds)
PROPERTY = f"properties/{PROPERTY_ID}"


def run(dimensions, metrics, date_ranges, order_metric=None, limit=None):
    req = RunReportRequest(
        property=PROPERTY,
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=date_ranges,
    )
    if order_metric:
        req.order_bys = [OrderBy(metric=OrderBy.MetricOrderBy(metric_name=order_metric), desc=True)]
    if limit:
        req.limit = limit
    resp = client.run_report(req)
    dim_names = [h.name for h in resp.dimension_headers]
    met_names = [h.name for h in resp.metric_headers]
    rows = []
    for r in resp.rows:
        row = {n: v.value for n, v in zip(dim_names, r.dimension_values)}
        for n, v in zip(met_names, r.metric_values):
            row[n] = float(v.value)
        rows.append(row)
    return rows


KPI_METRICS = ["activeUsers", "newUsers", "sessions", "screenPageViews",
               "engagementRate", "averageSessionDuration", "bounceRate"]
blank = {m: 0.0 for m in KPI_METRICS}
FIRST_DAY = "2015-08-14"  # earliest date GA4 accepts = "all time"

# Time frames the dashboard can switch between (days back; None = all time)
RANGES = {"7d": 7, "30d": 30, "90d": 90, "365d": 365, "all": None}


def totals(date_range):
    rows = run([], KPI_METRICS, [date_range])
    return rows[0] if rows else dict(blank)


def frame(days):
    if days:
        cur = DateRange(start_date=f"{days}daysAgo", end_date="yesterday")
        prev = DateRange(start_date=f"{days * 2}daysAgo", end_date=f"{days + 1}daysAgo")
        kpis = {"current": totals(cur), "previous": totals(prev)}
    else:
        cur = DateRange(start_date=FIRST_DAY, end_date="yesterday")
        kpis = {"current": totals(cur), "previous": None}
    return {
        "kpis": kpis,
        "topPages": run(["pagePath", "pageTitle"], ["screenPageViews", "activeUsers"],
                        [cur], order_metric="screenPageViews", limit=10),
        "channels": run(["sessionDefaultChannelGroup"], ["sessions"], [cur],
                        order_metric="sessions", limit=8),
        "countries": run(["country"], ["activeUsers", "sessions"], [cur],
                         order_metric="activeUsers", limit=100),
        "devices": run(["deviceCategory"], ["activeUsers", "sessions"], [cur],
                       order_metric="activeUsers"),
        "sources": run(["sessionSource"], ["sessions"], [cur],
                       order_metric="sessions", limit=10),
    }


# Daily trend for the whole history; the page trims it to the chosen time frame
daily = run(["date"], ["activeUsers", "sessions", "screenPageViews", "bounceRate"],
            [DateRange(start_date=FIRST_DAY, end_date="yesterday")])
daily.sort(key=lambda r: r["date"])
for r in daily:
    r["date"] = f'{r["date"][:4]}-{r["date"][4:6]}-{r["date"][6:]}'

out = {
    "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
    "propertyId": PROPERTY_ID,
    "daily": daily,
    "ranges": {key: frame(days) for key, days in RANGES.items()},
}

os.makedirs("data", exist_ok=True)
with open("data/website.json", "w") as f:
    json.dump(out, f, indent=1)
print(f"Saved data/website.json ({len(daily)} days of trend data, {len(RANGES)} time frames)")
