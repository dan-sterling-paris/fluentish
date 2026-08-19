#!/usr/bin/env python3
"""
FluentISH Marketing Data Report

Fetches data from PageSpeed Insights, Meta Ads, and Google Analytics 4,
then prints a consolidated report and saves it as JSON.

Prerequisites:
  1. pip install -r scripts/requirements.txt
  2. Copy .env.example to .env and fill in your credentials
  3. For GA4: grant the service account Viewer access on the GA4 property
     (Admin > Property Access Management) and enable the Google Analytics
     Data API in the Google Cloud project
  4. For Meta Ads: the access token needs ads_read permission
"""

import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PAGESPEED_URLS = [
    "https://fluentish.co.uk/",
    "https://fluentish.co.uk/free-chat",
    "https://fluentish.co.uk/about.html",
    "https://fluentish.co.uk/pricing.html",
]

PAGESPEED_STRATEGIES = ["mobile", "desktop"]

META_DATE_PRESETS = ["today", "last_7d", "last_30d"]

GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# PageSpeed Insights
# ---------------------------------------------------------------------------


def fetch_pagespeed(api_key=None):
    results = {}
    first = True
    for url in PAGESPEED_URLS:
        results[url] = {}
        for strategy in PAGESPEED_STRATEGIES:
            if not first:
                time.sleep(5)
            first = False
            params = {
                "url": url,
                "strategy": strategy,
                "category": "performance",
            }
            if api_key:
                params["key"] = api_key

            try:
                resp = requests.get(
                    "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                    params=params,
                    timeout=60,
                )
                if not resp.ok:
                    print(f"  [!] PageSpeed error for {url} ({strategy}): {resp.status_code}")
                    results[url][strategy] = {"error": resp.text[:200]}
                    continue

                data = resp.json()
                lh = data.get("lighthouseResult", {})
                audits = lh.get("audits", {})
                cat = lh.get("categories", {}).get("performance", {})

                results[url][strategy] = {
                    "performance_score": round((cat.get("score") or 0) * 100),
                    "fcp_ms": audits.get("first-contentful-paint", {}).get("numericValue"),
                    "lcp_ms": audits.get("largest-contentful-paint", {}).get("numericValue"),
                    "cls": audits.get("cumulative-layout-shift", {}).get("numericValue"),
                    "tbt_ms": audits.get("total-blocking-time", {}).get("numericValue"),
                    "speed_index_ms": audits.get("speed-index", {}).get("numericValue"),
                }
            except requests.RequestException as e:
                print(f"  [!] PageSpeed request failed for {url} ({strategy}): {e}")
                results[url][strategy] = {"error": str(e)}

    return results


# ---------------------------------------------------------------------------
# Meta Ads
# ---------------------------------------------------------------------------


def fetch_meta_ads(account_id, access_token):
    fields = "spend,impressions,reach,clicks,ctr,actions,cost_per_action_type"
    base_url = f"https://graph.facebook.com/v21.0/{account_id}/insights"

    overview = {}
    for preset in META_DATE_PRESETS:
        try:
            resp = requests.get(
                base_url,
                params={
                    "fields": fields,
                    "date_preset": preset,
                    "access_token": access_token,
                },
                timeout=30,
            )
            data = resp.json()
            if not resp.ok or "error" in data:
                msg = data.get("error", {}).get("message", resp.text[:200])
                print(f"  [!] Meta Ads error ({preset}): {msg}")
                overview[preset] = {"error": msg}
                continue

            rows = data.get("data", [])
            if not rows:
                overview[preset] = _empty_meta_row(preset)
                continue

            overview[preset] = _parse_meta_row(rows[0], preset)
        except requests.RequestException as e:
            print(f"  [!] Meta Ads request failed ({preset}): {e}")
            overview[preset] = {"error": str(e)}

    # Campaign-level breakdown (last 30 days)
    campaigns = []
    try:
        resp = requests.get(
            base_url,
            params={
                "fields": f"campaign_name,{fields}",
                "date_preset": "last_30d",
                "level": "campaign",
                "access_token": access_token,
            },
            timeout=30,
        )
        data = resp.json()
        if resp.ok and "data" in data:
            for row in data["data"]:
                campaigns.append({
                    "campaign_name": row.get("campaign_name", "Unknown"),
                    **_parse_meta_row(row, "last_30d"),
                })
    except requests.RequestException as e:
        print(f"  [!] Meta Ads campaign fetch failed: {e}")

    return {"overview": overview, "campaigns": campaigns}


def _parse_meta_row(row, preset):
    actions = row.get("actions") or []
    lead_action = next((a for a in actions if a["action_type"] == "lead"), None)
    leads = lead_action["value"] if lead_action else "0"

    cpa = row.get("cost_per_action_type") or []
    cpl_action = next((a for a in cpa if a["action_type"] == "lead"), None)
    cost_per_lead = cpl_action["value"] if cpl_action else None

    return {
        "date_preset": preset,
        "spend": row.get("spend", "0.00"),
        "impressions": row.get("impressions", "0"),
        "reach": row.get("reach", "0"),
        "clicks": row.get("clicks", "0"),
        "ctr": f"{float(row.get('ctr', 0)):.2f}",
        "leads": leads,
        "cost_per_lead": cost_per_lead,
    }


def _empty_meta_row(preset):
    return {
        "date_preset": preset,
        "spend": "0.00",
        "impressions": "0",
        "reach": "0",
        "clicks": "0",
        "ctr": "0.00",
        "leads": "0",
        "cost_per_lead": None,
    }


# ---------------------------------------------------------------------------
# Google Analytics 4
# ---------------------------------------------------------------------------


def fetch_ga4(property_id, sa_json_path):
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(sa_json_path, scopes=GA4_SCOPES)
    creds.refresh(Request())

    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }
    api_url = f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"

    today = date.today()
    start_7d = (today - timedelta(days=7)).isoformat()
    start_30d = (today - timedelta(days=30)).isoformat()
    end = today.isoformat()

    result = {}

    # 1. Traffic overview (7d and 30d)
    overview_metrics = [
        {"name": "sessions"},
        {"name": "totalUsers"},
        {"name": "newUsers"},
        {"name": "screenPageViews"},
        {"name": "averageSessionDuration"},
        {"name": "bounceRate"},
        {"name": "conversions"},
    ]

    for label, start in [("last_7d", start_7d), ("last_30d", start_30d)]:
        data = _ga4_report(api_url, headers, {
            "dateRanges": [{"startDate": start, "endDate": end}],
            "metrics": overview_metrics,
        })
        if data:
            row = data["rows"][0] if data.get("rows") else None
            if row:
                vals = [v.get("value", "0") for v in row.get("metricValues", [])]
                result[f"overview_{label}"] = {
                    "sessions": vals[0],
                    "users": vals[1],
                    "new_users": vals[2],
                    "pageviews": vals[3],
                    "avg_session_duration_s": f"{float(vals[4]):.1f}",
                    "bounce_rate": f"{float(vals[5]) * 100:.1f}",
                    "conversions": vals[6],
                }
            else:
                result[f"overview_{label}"] = {"note": "No data"}
        else:
            result[f"overview_{label}"] = {"error": "API call failed"}

    # 2. Top pages (30d)
    data = _ga4_report(api_url, headers, {
        "dateRanges": [{"startDate": start_30d, "endDate": end}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [
            {"name": "screenPageViews"},
            {"name": "sessions"},
        ],
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": 15,
    })
    result["top_pages"] = _parse_ga4_dim_report(data, "pagePath", ["pageviews", "sessions"])

    # 3. Traffic sources (30d)
    data = _ga4_report(api_url, headers, {
        "dateRanges": [{"startDate": start_30d, "endDate": end}],
        "dimensions": [{"name": "sessionSourceMedium"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "conversions"},
        ],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 10,
    })
    result["traffic_sources"] = _parse_ga4_dim_report(
        data, "sessionSourceMedium", ["sessions", "users", "conversions"]
    )

    # 4. Device breakdown (30d)
    data = _ga4_report(api_url, headers, {
        "dateRanges": [{"startDate": start_30d, "endDate": end}],
        "dimensions": [{"name": "deviceCategory"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
        ],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
    })
    result["devices"] = _parse_ga4_dim_report(data, "deviceCategory", ["sessions", "users"])

    return result


def _ga4_report(api_url, headers, body):
    try:
        resp = requests.post(api_url, headers=headers, json=body, timeout=30)
        if not resp.ok:
            print(f"  [!] GA4 API error: {resp.status_code} {resp.text[:200]}")
            return None
        return resp.json()
    except requests.RequestException as e:
        print(f"  [!] GA4 request failed: {e}")
        return None


def _parse_ga4_dim_report(data, dim_name, metric_names):
    if not data or not data.get("rows"):
        return []
    rows = []
    for row in data["rows"]:
        dim_val = row["dimensionValues"][0]["value"]
        entry = {dim_name: dim_val}
        for i, name in enumerate(metric_names):
            entry[name] = row["metricValues"][i]["value"]
        rows.append(entry)
    return rows


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def fmt_ms(ms):
    if ms is None:
        return "n/a"
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms:.0f}ms"


def fmt_num(val):
    try:
        n = int(val)
        return f"{n:,}"
    except (ValueError, TypeError):
        return str(val)


def print_report(report):
    today_str = date.today().isoformat()
    print(f"\n{'=' * 60}")
    print(f"  FLUENTISH MARKETING REPORT ({today_str})")
    print(f"{'=' * 60}")

    # PageSpeed
    ps = report.get("pagespeed")
    if ps:
        print(f"\n--- PAGESPEED INSIGHTS ---")
        for url, strategies in ps.items():
            short = url.replace("https://fluentish.co.uk", "") or "/"
            print(f"\n  {short}")
            for strategy, metrics in strategies.items():
                if "error" in metrics:
                    print(f"    {strategy.title():8s}: Error")
                    continue
                print(
                    f"    {strategy.title():8s}: "
                    f"Score {metrics['performance_score']:3d} | "
                    f"FCP {fmt_ms(metrics['fcp_ms'])} | "
                    f"LCP {fmt_ms(metrics['lcp_ms'])} | "
                    f"CLS {metrics['cls']:.3f} | "
                    f"TBT {fmt_ms(metrics['tbt_ms'])}"
                )
    else:
        print("\n--- PAGESPEED INSIGHTS ---\n  Skipped (no errors)")

    # Meta Ads
    meta = report.get("meta_ads")
    if meta:
        print(f"\n--- META ADS ---")
        overview = meta.get("overview", {})
        labels = {"today": "Today", "last_7d": "Last 7d", "last_30d": "Last 30d"}
        for preset, label in labels.items():
            row = overview.get(preset, {})
            if "error" in row:
                print(f"  {label:10s}: Error - {row['error'][:60]}")
                continue
            cpl = f"CPL £{float(row['cost_per_lead']):.2f}" if row.get("cost_per_lead") else "CPL n/a"
            print(
                f"  {label:10s}: "
                f"Spend £{float(row['spend']):.2f} | "
                f"Impr {fmt_num(row['impressions'])} | "
                f"Clicks {fmt_num(row['clicks'])} | "
                f"CTR {row['ctr']}% | "
                f"Leads {row['leads']} | "
                f"{cpl}"
            )

        campaigns = meta.get("campaigns", [])
        if campaigns:
            print(f"\n  Campaigns (last 30d):")
            for c in campaigns:
                cpl = f"CPL £{float(c['cost_per_lead']):.2f}" if c.get("cost_per_lead") else "CPL n/a"
                print(
                    f"    \"{c['campaign_name']}\"  "
                    f"Spend £{float(c['spend']):.2f} | "
                    f"Leads {c['leads']} | {cpl}"
                )
    else:
        print("\n--- META ADS ---\n  Skipped (credentials not configured)")

    # GA4
    ga = report.get("ga4")
    if ga:
        print(f"\n--- GOOGLE ANALYTICS ---")
        for label, key in [("Last 7 days", "overview_last_7d"), ("Last 30 days", "overview_last_30d")]:
            ov = ga.get(key, {})
            if "error" in ov or "note" in ov:
                print(f"  {label:14s}: {ov.get('error') or ov.get('note')}")
                continue
            print(
                f"  {label:14s}: "
                f"Sessions {fmt_num(ov['sessions'])} | "
                f"Users {fmt_num(ov['users'])} | "
                f"Pageviews {fmt_num(ov['pageviews'])} | "
                f"Bounce {ov['bounce_rate']}% | "
                f"Conversions {fmt_num(ov['conversions'])}"
            )

        pages = ga.get("top_pages", [])
        if pages:
            print(f"\n  Top Pages (30d):")
            for p in pages:
                print(f"    {p['pagePath']:30s} {fmt_num(p['pageviews']):>8s} views | {fmt_num(p['sessions']):>6s} sessions")

        sources = ga.get("traffic_sources", [])
        if sources:
            print(f"\n  Traffic Sources (30d):")
            for s in sources:
                print(
                    f"    {s['sessionSourceMedium']:30s} "
                    f"{fmt_num(s['sessions']):>6s} sessions | "
                    f"{fmt_num(s['conversions']):>4s} conversions"
                )

        devices = ga.get("devices", [])
        if devices:
            total_sessions = sum(int(d["sessions"]) for d in devices)
            print(f"\n  Devices (30d):")
            for d in devices:
                sess = int(d["sessions"])
                pct = (sess / total_sessions * 100) if total_sessions else 0
                print(f"    {d['deviceCategory']:10s} {fmt_num(sess):>6s} sessions ({pct:.1f}%)")
    else:
        print("\n--- GOOGLE ANALYTICS ---\n  Skipped (credentials not configured)")

    print()


def save_json(report):
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    filepath = reports_dir / f"marketing-data-{date.today().isoformat()}.json"
    with open(filepath, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Report saved to {filepath.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    load_dotenv(PROJECT_ROOT / ".env")

    report = {"date": date.today().isoformat()}

    # PageSpeed Insights
    print("\nFetching PageSpeed Insights...")
    api_key = os.getenv("PAGESPEED_API_KEY") or None
    report["pagespeed"] = fetch_pagespeed(api_key)

    # Meta Ads
    meta_account = os.getenv("META_AD_ACCOUNT_ID", "").strip()
    meta_token = os.getenv("META_ADS_ACCESS_TOKEN", "").strip()
    if meta_account and meta_token:
        print("Fetching Meta Ads data...")
        report["meta_ads"] = fetch_meta_ads(meta_account, meta_token)
    else:
        print("Skipping Meta Ads (META_AD_ACCOUNT_ID / META_ADS_ACCESS_TOKEN not set)")
        report["meta_ads"] = None

    # Google Analytics 4
    ga4_property = os.getenv("GA4_PROPERTY_ID", "").strip()
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH", "").strip()
    if ga4_property and sa_path and Path(sa_path).is_file():
        print("Fetching Google Analytics data...")
        try:
            report["ga4"] = fetch_ga4(ga4_property, sa_path)
        except Exception as e:
            print(f"  [!] GA4 failed: {e}")
            report["ga4"] = {"error": str(e)}
    else:
        missing = []
        if not ga4_property:
            missing.append("GA4_PROPERTY_ID")
        if not sa_path:
            missing.append("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")
        elif not Path(sa_path).is_file():
            missing.append(f"file not found: {sa_path}")
        print(f"Skipping Google Analytics ({', '.join(missing)})")
        report["ga4"] = None

    print_report(report)
    save_json(report)


if __name__ == "__main__":
    main()
