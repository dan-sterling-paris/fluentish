// Remote MCP server exposing Meta Ads + GA4 performance as tools, meant to be
// added as a Claude custom connector so ad performance can be asked about
// from any Claude surface (including the phone app), not just Claude Code.
//
// This has to be a real MCP server (not a Skill with bundled scripts)
// because Claude's regular chat surfaces run code in a sandbox with no
// internet access — only server-side MCP tool calls can reach an external
// API like the Meta Graph API or the GA4 Data API from there.
//
// Auth is a static bearer token (MCP_ACCESS_TOKEN), not a Supabase user JWT,
// since the caller is Claude's connector infrastructure, not a logged-in
// dashboard user. See README.md in this directory for full setup steps.
import 'jsr:@supabase/functions-js/edge-runtime.d.ts'

import { McpServer } from 'npm:@modelcontextprotocol/sdk@1.25.3/server/mcp.js'
import { WebStandardStreamableHTTPServerTransport } from 'npm:@modelcontextprotocol/sdk@1.25.3/server/webStandardStreamableHttp.js'
import { Hono } from 'npm:hono@^4.9.7'
import { z } from 'npm:zod@^4.1.13'

const MCP_ACCESS_TOKEN = Deno.env.get('MCP_ACCESS_TOKEN') ?? ''
const META_AD_ACCOUNT_ID = Deno.env.get('META_AD_ACCOUNT_ID') ?? ''
const META_ADS_ACCESS_TOKEN = Deno.env.get('META_ADS_ACCESS_TOKEN') ?? ''
const GA4_PROPERTY_ID = Deno.env.get('GA4_PROPERTY_ID') ?? ''
const GA4_SERVICE_ACCOUNT_JSON = Deno.env.get('GA4_SERVICE_ACCOUNT_JSON') ?? ''

const DATE_PRESETS = ['today', 'yesterday', 'last_7d', 'last_14d', 'last_30d'] as const
type DatePreset = (typeof DATE_PRESETS)[number]

// GA4's Data API takes relative date strings directly rather than named
// presets, so each preset is mapped to GA4's own equivalent rather than
// computed by hand — that avoids timezone/boundary bugs from re-deriving
// "today" ourselves, at the cost of the two platforms' windows not being
// bit-for-bit identical (Meta's own "last_7d" excludes today; GA4's here
// runs through today). Close enough for a daily gut-check, called out in
// the tool description rather than silently assumed.
const GA4_RANGE_FOR_PRESET: Record<DatePreset, { startDate: string; endDate: string }> = {
  today: { startDate: 'today', endDate: 'today' },
  yesterday: { startDate: 'yesterday', endDate: 'yesterday' },
  last_7d: { startDate: '7daysAgo', endDate: 'today' },
  last_14d: { startDate: '14daysAgo', endDate: 'today' },
  last_30d: { startDate: '30daysAgo', endDate: 'today' },
}

function timingSafeEqual(a: string, b: string): boolean {
  const enc = new TextEncoder()
  const ab = enc.encode(a)
  const bb = enc.encode(b)
  if (ab.length !== bb.length) return false
  let diff = 0
  for (let i = 0; i < ab.length; i++) diff |= ab[i] ^ bb[i]
  return diff === 0
}

interface MetaDay {
  date: string
  spend: number
  impressions: number
  clicks: number
  leads: number
}

async function fetchMeta(params: { datePreset?: DatePreset; since?: string; until?: string }): Promise<MetaDay[]> {
  if (!META_AD_ACCOUNT_ID || !META_ADS_ACCESS_TOKEN) {
    throw new Error('META_AD_ACCOUNT_ID / META_ADS_ACCESS_TOKEN are not configured as function secrets.')
  }
  const fields = 'spend,impressions,clicks,actions,date_start'
  const query = new URLSearchParams({
    fields,
    time_increment: '1',
    access_token: META_ADS_ACCESS_TOKEN,
    limit: '500',
  })
  if (params.since && params.until) {
    query.set('time_range', JSON.stringify({ since: params.since, until: params.until }))
  } else {
    query.set('date_preset', params.datePreset ?? 'today')
  }

  const resp = await fetch(`https://graph.facebook.com/v21.0/${META_AD_ACCOUNT_ID}/insights?${query}`)
  const data = await resp.json()
  if (!resp.ok || data.error) {
    throw new Error(`Meta API error: ${data.error?.message ?? JSON.stringify(data)}`)
  }
  return ((data.data ?? []) as Record<string, unknown>[]).map((row) => {
    const actions = (row.actions ?? []) as Array<{ action_type: string; value: string }>
    const leads = actions.find((a) => a.action_type === 'lead')?.value ?? '0'
    return {
      date: String(row.date_start ?? ''),
      spend: Number(row.spend ?? 0),
      impressions: Number(row.impressions ?? 0),
      clicks: Number(row.clicks ?? 0),
      leads: Number(leads),
    }
  })
}

interface Ga4Day {
  date: string
  sessions: number
  active_users: number
  conversions: number
  engagement_rate: number
}

async function getGa4AccessToken(): Promise<string> {
  if (!GA4_SERVICE_ACCOUNT_JSON) {
    throw new Error('GA4_SERVICE_ACCOUNT_JSON is not configured as a function secret.')
  }
  const key = JSON.parse(GA4_SERVICE_ACCOUNT_JSON) as { client_email: string; private_key: string }

  const base64url = (input: string) =>
    btoa(input).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

  const now = Math.floor(Date.now() / 1000)
  const header = base64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
  const claims = base64url(
    JSON.stringify({
      iss: key.client_email,
      scope: 'https://www.googleapis.com/auth/analytics.readonly',
      aud: 'https://oauth2.googleapis.com/token',
      iat: now,
      exp: now + 3600,
    }),
  )
  const unsigned = `${header}.${claims}`

  const pemBody = key.private_key.replace(/-----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----|\s+/g, '')
  const derBytes = Uint8Array.from(atob(pemBody), (c) => c.charCodeAt(0))
  const cryptoKey = await crypto.subtle.importKey(
    'pkcs8',
    derBytes,
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
    false,
    ['sign'],
  )
  const signatureBytes = new Uint8Array(
    await crypto.subtle.sign('RSASSA-PKCS1-v1_5', cryptoKey, new TextEncoder().encode(unsigned)),
  )
  const signature = base64url(String.fromCharCode(...signatureBytes))
  const jwt = `${unsigned}.${signature}`

  const resp = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion: jwt,
    }),
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(`GA4 auth failed: ${data.error_description ?? data.error ?? JSON.stringify(data)}`)
  return data.access_token as string
}

async function fetchGa4(params: { datePreset?: DatePreset; since?: string; until?: string }): Promise<Ga4Day[]> {
  if (!GA4_PROPERTY_ID) {
    throw new Error('GA4_PROPERTY_ID is not configured as a function secret.')
  }
  const dateRange = params.since && params.until
    ? { startDate: params.since, endDate: params.until }
    : GA4_RANGE_FOR_PRESET[params.datePreset ?? 'today']

  const accessToken = await getGa4AccessToken()
  const resp = await fetch(
    `https://analyticsdata.googleapis.com/v1beta/properties/${GA4_PROPERTY_ID}:runReport`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dateRanges: [dateRange],
        dimensions: [{ name: 'date' }],
        metrics: [
          { name: 'sessions' },
          { name: 'activeUsers' },
          { name: 'conversions' },
          { name: 'engagementRate' },
        ],
        orderBys: [{ dimension: { dimensionName: 'date' } }],
      }),
    },
  )
  const data = await resp.json()
  if (!resp.ok) throw new Error(`GA4 API error: ${data.error?.message ?? JSON.stringify(data)}`)

  return ((data.rows ?? []) as Array<{ dimensionValues: { value: string }[]; metricValues: { value: string }[] }>).map(
    (row) => {
      const raw = row.dimensionValues[0].value // YYYYMMDD
      const date = `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`
      const [sessions, activeUsers, conversions, engagementRate] = row.metricValues.map((m) => Number(m.value))
      return { date, sessions, active_users: activeUsers, conversions, engagement_rate: engagementRate }
    },
  )
}

function sumBy<T>(rows: T[], pick: (row: T) => number): number {
  return rows.reduce((total, row) => total + pick(row), 0)
}

function formatMetaReport(rows: MetaDay[], label: string): string {
  if (rows.length === 0) return `No Meta Ads data for ${label}.`
  const spend = sumBy(rows, (r) => r.spend)
  const clicks = sumBy(rows, (r) => r.clicks)
  const leads = sumBy(rows, (r) => r.leads)
  const lines = [
    `**Meta Ads — ${label}**`,
    `Spend: ${spend.toFixed(2)} | Clicks: ${clicks} | Leads: ${leads}` +
      (leads ? ` | Cost per lead: ${(spend / leads).toFixed(2)}` : ''),
  ]
  if (rows.length > 1) {
    lines.push('', '| date | spend | clicks | leads |', '|---|---|---|---|')
    for (const r of rows) lines.push(`| ${r.date} | ${r.spend.toFixed(2)} | ${r.clicks} | ${r.leads} |`)
  }
  return lines.join('\n')
}

function formatGa4Report(rows: Ga4Day[], label: string): string {
  if (rows.length === 0) return `No GA4 data for ${label}.`
  const sessions = sumBy(rows, (r) => r.sessions)
  const conversions = sumBy(rows, (r) => r.conversions)
  const avgEngagement = sumBy(rows, (r) => r.engagement_rate) / rows.length
  const lines = [
    `**GA4 — ${label}**`,
    `Sessions: ${sessions} | Conversions: ${conversions} | Avg engagement rate: ${(avgEngagement * 100).toFixed(1)}%`,
  ]
  if (rows.length > 1) {
    lines.push('', '| date | sessions | conversions | engagement |', '|---|---|---|---|')
    for (const r of rows) {
      lines.push(`| ${r.date} | ${r.sessions} | ${r.conversions} | ${(r.engagement_rate * 100).toFixed(1)}% |`)
    }
  }
  return lines.join('\n')
}

function formatBlendedReport(meta: MetaDay[], ga4: Ga4Day[], label: string): string {
  if (meta.length === 0 && ga4.length === 0) return `No Meta Ads or GA4 data for ${label}.`

  const spend = sumBy(meta, (r) => r.spend)
  const clicks = sumBy(meta, (r) => r.clicks)
  const leads = sumBy(meta, (r) => r.leads)
  const sessions = sumBy(ga4, (r) => r.sessions)
  const conversions = sumBy(ga4, (r) => r.conversions)

  const lines = [`**Blended ad performance — ${label}**`, '']
  lines.push(`- Spend: ${spend.toFixed(2)}`)
  lines.push(`- Meta clicks: ${clicks} | Meta leads: ${leads}${leads ? ` (£${(spend / leads).toFixed(2)}/lead)` : ''}`)
  lines.push(`- GA4 sessions: ${sessions} | GA4 conversions: ${conversions}` +
    (sessions ? ` (£${(spend / sessions).toFixed(2)}/session)` : '') +
    (conversions ? `, £${(spend / conversions).toFixed(2)}/conversion` : ''))

  if (clicks > 0 && sessions > clicks * 3) {
    lines.push(
      '',
      `Note: GA4 sessions (${sessions}) are far higher than Meta link clicks (${clicks}) for the same window. ` +
        'That usually means this GA4 property/report reflects total site traffic rather than traffic scoped to ' +
        "this campaign, so the cost-per-session and cost-per-conversion figures above are likely diluted by " +
        'unrelated traffic — the cost-per-Meta-lead figure is the more reliable one to act on.',
    )
  }

  if (meta.length > 1 || ga4.length > 1) {
    const dates = Array.from(new Set([...meta.map((r) => r.date), ...ga4.map((r) => r.date)])).sort()
    lines.push('', '| date | spend | leads | sessions | ga4 conv. |', '|---|---|---|---|---|')
    for (const date of dates) {
      const m = meta.find((r) => r.date === date)
      const g = ga4.find((r) => r.date === date)
      lines.push(
        `| ${date} | ${(m?.spend ?? 0).toFixed(2)} | ${m?.leads ?? 0} | ${g?.sessions ?? 0} | ${g?.conversions ?? 0} |`,
      )
    }
  }

  return lines.join('\n')
}

function presetLabel(datePreset: DatePreset | undefined, since?: string, until?: string): string {
  if (since && until) return since === until ? since : `${since} to ${until}`
  return (datePreset ?? 'today').replace('_', ' ')
}

const dateArgs = {
  date_preset: z
    .enum(DATE_PRESETS)
    .optional()
    .describe('Relative window: today, yesterday, last_7d, last_14d, or last_30d. Defaults to today. Ignored if since/until are given.'),
  since: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe('Start date YYYY-MM-DD, overrides date_preset.'),
  until: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().describe('End date YYYY-MM-DD, overrides date_preset.'),
}

const server = new McpServer({ name: 'fluentish-ads-performance', version: '1.0.0' })

server.registerTool(
  'get_meta_ads_performance',
  {
    title: 'Meta Ads performance',
    description: 'Spend, clicks, and leads from the fluentish Meta (Facebook/Instagram) ad account for a given date range.',
    inputSchema: dateArgs,
  },
  async ({ date_preset, since, until }) => {
    const label = presetLabel(date_preset, since, until)
    try {
      const rows = await fetchMeta({ datePreset: date_preset, since, until })
      return { content: [{ type: 'text', text: formatMetaReport(rows, label) }] }
    } catch (e) {
      return { content: [{ type: 'text', text: `Error fetching Meta Ads data: ${(e as Error).message}` }], isError: true }
    }
  },
)

server.registerTool(
  'get_ga4_performance',
  {
    title: 'GA4 performance',
    description: 'Sessions, conversions, and engagement rate from the fluentish GA4 property for a given date range.',
    inputSchema: dateArgs,
  },
  async ({ date_preset, since, until }) => {
    const label = presetLabel(date_preset, since, until)
    try {
      const rows = await fetchGa4({ datePreset: date_preset, since, until })
      return { content: [{ type: 'text', text: formatGa4Report(rows, label) }] }
    } catch (e) {
      return { content: [{ type: 'text', text: `Error fetching GA4 data: ${(e as Error).message}` }], isError: true }
    }
  },
)

server.registerTool(
  'get_blended_ad_performance',
  {
    title: 'Blended Meta Ads + GA4 performance',
    description:
      "Combines fluentish's Meta Ads spend/leads with GA4 sessions/conversions for the same date range into one " +
      'blended view (cost per session, cost per lead, cost per conversion). This is the tool to use for a general ' +
      '"how are my ads doing" question — it calls both platforms and flags likely data issues (e.g. GA4 traffic ' +
      "not scoped to the ad channel) rather than just reporting raw numbers.",
    inputSchema: dateArgs,
  },
  async ({ date_preset, since, until }) => {
    const label = presetLabel(date_preset, since, until)
    try {
      const [meta, ga4] = await Promise.all([
        fetchMeta({ datePreset: date_preset, since, until }),
        fetchGa4({ datePreset: date_preset, since, until }),
      ])
      return { content: [{ type: 'text', text: formatBlendedReport(meta, ga4, label) }] }
    } catch (e) {
      return { content: [{ type: 'text', text: `Error fetching blended ad performance: ${(e as Error).message}` }], isError: true }
    }
  },
)

const app = new Hono()

app.use('*', async (c, next) => {
  if (!MCP_ACCESS_TOKEN) {
    return c.json({ error: 'Server misconfigured: MCP_ACCESS_TOKEN secret is not set.' }, 500)
  }
  // Accept the token either as a Bearer header (e.g. `claude mcp add --header`)
  // or a ?token= query param — claude.ai's "add custom connector" UI only takes
  // a bare URL with no way to attach a header, so the query param is what
  // makes the secret usable there.
  const headerToken = (c.req.header('Authorization') ?? '').replace(/^Bearer\s+/i, '')
  const queryToken = c.req.query('token') ?? ''
  if (!timingSafeEqual(headerToken, MCP_ACCESS_TOKEN) && !timingSafeEqual(queryToken, MCP_ACCESS_TOKEN)) {
    return c.json({ error: 'Unauthorized' }, 401)
  }
  await next()
})

// Stateless transport (no session id generator) — one instance for the
// life of the isolate, matching the SDK's own recommended pattern of
// connecting once rather than per-request.
const transport = new WebStandardStreamableHTTPServerTransport()
await server.connect(transport)

app.all('*', (c) => transport.handleRequest(c.req.raw))

Deno.serve(app.fetch)
