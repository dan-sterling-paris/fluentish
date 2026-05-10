import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const META_AD_ACCOUNT_ID = Deno.env.get("META_AD_ACCOUNT_ID") ?? "";
const META_ADS_ACCESS_TOKEN = Deno.env.get("META_ADS_ACCESS_TOKEN") ?? "";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}

function err(message: string, status: number) {
  return json({ error: message }, status);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS_HEADERS });

  // Verify JWT
  const auth = req.headers.get("Authorization") ?? "";
  const token = auth.replace("Bearer ", "");
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
  const { error: authError } = await supabase.auth.getUser(token);
  if (authError) return err("Unauthorized", 401);

  const url = new URL(req.url);
  const datePreset = url.searchParams.get("date_preset") ?? "last_7d";

  if (!["today", "last_7d", "last_30d"].includes(datePreset)) {
    return err("Invalid date_preset", 400);
  }

  if (!META_AD_ACCOUNT_ID || !META_ADS_ACCESS_TOKEN) {
    return err("Meta ads not configured", 503);
  }

  const fields = "spend,impressions,reach,clicks,ctr,actions,cost_per_action_type";
  const metaUrl = `https://graph.facebook.com/v21.0/${META_AD_ACCOUNT_ID}/insights?fields=${encodeURIComponent(fields)}&date_preset=${datePreset}&access_token=${META_ADS_ACCESS_TOKEN}`;

  let metaData: Record<string, unknown>;
  try {
    const metaRes = await fetch(metaUrl);
    metaData = await metaRes.json();
    if (!metaRes.ok || (metaData as { error?: unknown }).error) {
      console.error("Meta API error:", metaData);
      return err(
        ((metaData as { error?: { message?: string } }).error?.message) ?? "Meta API error",
        502,
      );
    }
  } catch (e) {
    console.error("Meta fetch failed:", e);
    return err("Failed to reach Meta API", 502);
  }

  const rows = (metaData as { data?: Record<string, unknown>[] }).data ?? [];
  if (rows.length === 0) {
    return json({
      spend: "0.00",
      impressions: "0",
      reach: "0",
      clicks: "0",
      ctr: "0.00",
      leads: "0",
      cost_per_lead: null,
      date_preset: datePreset,
    });
  }

  const row = rows[0];

  const actions = (row.actions ?? []) as Array<{ action_type: string; value: string }>;
  const leadAction = actions.find((a) => a.action_type === "lead");
  const leads = leadAction?.value ?? "0";

  const costPerAction = (row.cost_per_action_type ?? []) as Array<{ action_type: string; value: string }>;
  const cplAction = costPerAction.find((a) => a.action_type === "lead");
  const costPerLead = cplAction?.value ?? null;

  return json({
    spend: row.spend ?? "0.00",
    impressions: row.impressions ?? "0",
    reach: row.reach ?? "0",
    clicks: row.clicks ?? "0",
    ctr: row.ctr ? parseFloat(row.ctr as string).toFixed(2) : "0.00",
    leads,
    cost_per_lead: costPerLead,
    date_preset: datePreset,
  });
});
