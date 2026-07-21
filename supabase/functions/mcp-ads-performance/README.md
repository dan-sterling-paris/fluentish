# mcp-ads-performance

A remote MCP server exposing fluentish's Meta Ads + GA4 performance data as
tools, so you can ask any Claude surface — including the phone app — "how
are my ads doing today" and get a live answer.

This has to be a real server, not a Claude Skill with bundled scripts: the
regular Claude chat app runs code in a sandbox with no internet access, so
only a server-side MCP tool call (this function) can actually reach the Meta
Graph API and Google's GA4 Data API from there.

## Tools it exposes

- `get_meta_ads_performance` — spend, clicks, leads from Meta Ads
- `get_ga4_performance` — sessions, conversions, engagement rate from GA4
- `get_blended_ad_performance` — both together, with blended cost-per metrics
  and an automatic heads-up if GA4 traffic looks unscoped (see below) — this
  is the one to reach for on a general "how are my ads doing" question

All three take the same optional arguments: `date_preset` (`today`,
`yesterday`, `last_7d`, `last_14d`, `last_30d` — defaults to `today`), or an
explicit `since`/`until` (`YYYY-MM-DD`) to override it.

## One-time setup

### 1. Meta Ads credentials

If the dashboard's Ads panel (`dashboard/app.js`) already works, these are
already set as secrets on this project — nothing new to do here:
- `META_AD_ACCOUNT_ID` — e.g. `act_1234567890`
- `META_ADS_ACCESS_TOKEN` — needs `ads_read`; a long-lived or System User
  token, not the short-lived Graph API Explorer kind (those expire in ~1-2
  hours)

### 2. GA4 service account

Live GA4 access needs a service account, since there's no user sitting at a
browser to do an OAuth login:

1. In Google Cloud Console, enable the **Google Analytics Data API** on a
   project.
2. Create a **service account** (any name, no project-level role needed).
3. Create and download a **JSON key** for it. Treat this like a password —
   never commit it to the repo.
4. In GA4 Admin → Property Access Management, add the service account's
   email (`...@project.iam.gserviceaccount.com`) as a **Viewer**.
5. In GA4 Admin → Property Settings, note the numeric **property ID** (not
   the `G-XXXXXXX` measurement ID from the tracking snippet).

### 3. A secret for the MCP endpoint itself

This endpoint isn't a Supabase user route — it's hit directly by Claude's
connector infrastructure — so it checks its own bearer token rather than a
Supabase JWT. Generate one:

```bash
openssl rand -hex 32
```

### 4. Set the secrets and deploy

```bash
supabase secrets set \
  MCP_ACCESS_TOKEN=<output of openssl rand -hex 32> \
  GA4_PROPERTY_ID=<numeric property id> \
  GA4_SERVICE_ACCOUNT_JSON="$(cat path/to/service-account-key.json)"

supabase functions deploy mcp-ads-performance
```

(`META_AD_ACCOUNT_ID` / `META_ADS_ACCESS_TOKEN` only need setting too if
they aren't already, from the Meta Ads setup above.)

Your MCP server URL is:
```
https://<project-ref>.supabase.co/functions/v1/mcp-ads-performance
```

### 5. Add it to Claude

- **claude.ai / mobile app**: Settings → Connectors → Add custom connector.
  That UI takes a bare URL with no header field, so append the token as a
  query param: `https://<project-ref>.supabase.co/functions/v1/mcp-ads-performance?token=<your MCP_ACCESS_TOKEN>`
- **Claude Code**: `claude mcp add --transport http fluentish-ads https://<project-ref>.supabase.co/functions/v1/mcp-ads-performance --header "Authorization: Bearer <your MCP_ACCESS_TOKEN>"`

Once added, just ask — "how are my Meta ads doing today", "how's the free-chat
campaign done this week combining GA and ad spend" — and Claude will call
these tools directly.

## A caveat baked into the blended tool

If GA4 sessions for the window are much higher than Meta link clicks, the
tool adds a note: it almost always means the GA4 report/property being read
is total site traffic rather than something scoped to just this ad
channel/campaign, which dilutes cost-per-session and cost-per-conversion
into misleading numbers. The cost-per-Meta-lead figure is unaffected by that
and safe to act on regardless.
