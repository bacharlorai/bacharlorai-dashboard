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


LAST_30 = DateRange(start_date="30daysAgo", end_date="yesterday", name="current")
PREV_30 = DateRange(start_date="60daysAgo", end_date="31daysAgo", name="previous")
LAST_90 = DateRange(start_date="90daysAgo", end_date="yesterday")

KPI_METRICS = ["activeUsers", "newUsers", "sessions", "screenPageViews",
               "engagementRate", "averageSessionDuration"]

# 1. Headline numbers: last 30 days vs the 30 days before
kpi_rows = run(["dateRange"], KPI_METRICS, [LAST_30, PREV_30])
blank = {m: 0.0 for m in KPI_METRICS}
kpis = {
    "current": next((r for r in kpi_rows if r["dateRange"] == "current"), blank),
    "previous": next((r for r in kpi_rows if r["dateRange"] == "previous"), blank),
}

# 2. Daily trend, last 90 days
daily = run(["date"], ["activeUsers", "sessions", "screenPageViews"], [LAST_90])
daily.sort(key=lambda r: r["date"])
for r in daily:
    r["date"] = f'{r["date"][:4]}-{r["date"][4:6]}-{r["date"][6:]}'

# 3. Breakdowns, last 30 days
top_pages = run(["pagePath", "pageTitle"], ["screenPageViews", "activeUsers"],
                [LAST_30], order_metric="screenPageViews", limit=10)
channels = run(["sessionDefaultChannelGroup"], ["sessions"], [LAST_30],
               order_metric="sessions", limit=8)
countries = run(["country"], ["activeUsers"], [LAST_30],
                order_metric="activeUsers", limit=10)
devices = run(["deviceCategory"], ["activeUsers"], [LAST_30],
              order_metric="activeUsers")
referrers = run(["sessionSource"], ["sessions"], [LAST_30],
                order_metric="sessions", limit=10)

out = {
    "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
    "propertyId": PROPERTY_ID,
    "kpis": kpis,
    "daily": daily,
    "topPages": top_pages,
    "channels": channels,
    "countries": countries,
    "devices": devices,
    "sources": referrers,
}

os.makedirs("data", exist_ok=True)
with open("data/website.json", "w") as f:
    json.dump(out, f, indent=1)
print(f"Saved data/website.json ({len(daily)} days of trend data)")
