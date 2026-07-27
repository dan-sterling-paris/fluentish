const DASHBOARD_TOKEN = Deno.env.get("DASHBOARD_TOKEN") ?? "";
const META_TOKEN = Deno.env.get("META_CAPI_TOKEN") ?? "";
const GRAPH = "https://graph.facebook.com/v21.0";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

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

  const days = Math.min(90, Math.max(7, parseInt(url.searchParams.get("days") ?? "14")));

  try {
    const acctRes = await fetch(
      `${GRAPH}/me/adaccounts?fields=id,name&limit=5&access_token=${META_TOKEN}`
    );
    const acctJson = await acctRes.json();
    if (acctJson.error) throw new Error(acctJson.error.message);

    const account = acctJson.data?.find((a: { id: string; name: string }) =>
      a.name?.toLowerCase().includes("fluent")
    ) ?? acctJson.data?.[0];
    if (!account) throw new Error("No ad account found");

    const preset =
      days <= 7 ? "last_7d" : days <= 14 ? "last_14d" : days <= 28 ? "last_28d" : "last_90d";

    const fields = [
      "date_start",
      "spend",
      "impressions",
      "reach",
      "clicks",
      "cpm",
      "cpc",
      "ctr",
      "actions",
    ].join(",");

    const insightRes = await fetch(
      `${GRAPH}/${account.id}/insights?fields=${encodeURIComponent(fields)}&time_increment=1&date_preset=${preset}&access_token=${META_TOKEN}`
    );
    const insightJson = await insightRes.json();
    if (insightJson.error) throw new Error(insightJson.error.message);

    return new Response(
      JSON.stringify({ ok: true, rows: insightJson.data ?? [], account: account.name }),
      { headers: { ...CORS, "Content-Type": "application/json", "Cache-Control": "no-store" } }
    );
  } catch (e) {
    return new Response(JSON.stringify({ ok: false, error: String(e) }), {
      status: 500,
      headers: { ...CORS, "Content-Type": "application/json" },
    });
  }
});
