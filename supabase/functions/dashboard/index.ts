const DASHBOARD_TOKEN = Deno.env.get("DASHBOARD_TOKEN") ?? "";
const META_TOKEN = Deno.env.get("META_CAPI_TOKEN") ?? "";
const GRAPH = "https://graph.facebook.com/v21.0";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

// Follow Graph API cursor pagination. Campaign-level rows are
// (campaigns x days), so a single page is rarely enough.
async function fetchAllPages(url: string, maxPages = 25) {
  const out: unknown[] = [];
  let next: string | null = url;
  for (let page = 0; page < maxPages && next; page++) {
    const res = await fetch(next);
    const json = await res.json();
    if (json.error) throw new Error(json.error.message);
    if (Array.isArray(json.data)) out.push(...json.data);
    next = json.paging?.next ?? null;
  }
  return out;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS });
  }

  const url = new URL(req.url);
  const token = url.searchParams.get("t") ?? "";

  if (!DASHBOARD_TOKEN || token !== DASHBOARD_TOKEN) {
    return new Response(JSON.stringify({ ok: false, error: "Unauthorized" }), {
      status: 401,
      headers: { ...CORS, "Content-Type": "application/json" },
    });
  }

  try {
    const acctRes = await fetch(
      `${GRAPH}/me/adaccounts?fields=id,name&limit=5&access_token=${META_TOKEN}`
    );
    const acctJson = await acctRes.json();
    if (acctJson.error) throw new Error(acctJson.error.message);

    const account =
      acctJson.data?.find((a: { id: string; name: string }) =>
        a.name?.toLowerCase().includes("fluent")
      ) ?? acctJson.data?.[0];
    if (!account) throw new Error("No ad account found");

    // Always fetch 60 days including today
    const until = new Date().toISOString().slice(0, 10);
    const sinceDate = new Date(Date.now() - 60 * 86400000);
    const since = sinceDate.toISOString().slice(0, 10);
    const timeRange = JSON.stringify({ since, until });

    const baseFields = [
      "date_start",
      "spend",
      "impressions",
      "reach",
      "clicks",
      "cpm",
      "cpc",
      "ctr",
      "actions",
    ];

    const common =
      `&time_increment=1&time_range=${encodeURIComponent(timeRange)}` +
      `&access_token=${META_TOKEN}`;

    // Account-level rows power the "All campaigns" view. They are kept
    // separate from the campaign rows because reach is de-duplicated
    // across campaigns and so is NOT the sum of the per-campaign values.
    const accountUrl =
      `${GRAPH}/${account.id}/insights` +
      `?fields=${encodeURIComponent(baseFields.join(","))}` +
      `&limit=100${common}`;

    // Campaign-level rows power the per-campaign filter.
    const campaignFields = [...baseFields, "campaign_id", "campaign_name"];
    const campaignUrl =
      `${GRAPH}/${account.id}/insights` +
      `?fields=${encodeURIComponent(campaignFields.join(","))}` +
      `&level=campaign&limit=500${common}`;

    const [rows, campaigns] = await Promise.all([
      fetchAllPages(accountUrl),
      fetchAllPages(campaignUrl),
    ]);

    return new Response(
      JSON.stringify({ ok: true, rows, campaigns, account: account.name }),
      {
        headers: {
          ...CORS,
          "Content-Type": "application/json",
          "Cache-Control": "no-store",
        },
      }
    );
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: String(e) }), {
      status: 500,
      headers: { ...CORS, "Content-Type": "application/json" },
    });
  }
});
