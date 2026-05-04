import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const WEBHOOK_SECRET = Deno.env.get("CLICKSEND_WEBHOOK_SECRET") ?? "";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function normalizePhone(raw: string): string {
  let digits = raw.replace(/[^\d+]/g, "");
  if (digits.startsWith("00")) {
    digits = "+" + digits.slice(2);
  } else if (digits.startsWith("07") && digits.length === 11) {
    digits = "+44" + digits.slice(1);
  } else if (digits.startsWith("7") && digits.length === 10) {
    digits = "+44" + digits;
  } else if (!digits.startsWith("+")) {
    digits = "+" + digits;
  }
  return digits;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405, headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  }

  // Validate shared secret if configured
  if (WEBHOOK_SECRET) {
    const url = new URL(req.url);
    const secret = url.searchParams.get("secret") ?? "";
    if (secret !== WEBHOOK_SECRET) {
      return new Response(JSON.stringify({ error: "Forbidden" }), {
        status: 403, headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }
  }

  let payload: { messages?: Array<{ from?: string; body?: string }> };
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
    });
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
  const messages = payload.messages ?? [];

  for (const msg of messages) {
    const fromPhone = normalizePhone(msg.from ?? "");
    const body = (msg.body ?? "").trim();
    if (!fromPhone || !body) continue;

    // Find or create lead by phone
    let { data: lead } = await supabase
      .from("leads").select("id").eq("phone", fromPhone).single();

    if (!lead) {
      const { data: newLead, error: createErr } = await supabase
        .from("leads")
        .insert({ name: fromPhone, phone: fromPhone })
        .select("id").single();
      if (createErr || !newLead) {
        console.error("Failed to create stub lead for", fromPhone, createErr);
        continue;
      }
      lead = newLead;
    }

    await supabase.from("leads")
      .update({ status: "replied", updated_at: new Date().toISOString() })
      .eq("id", lead.id);

    await supabase.from("messages")
      .insert({ lead_id: lead.id, direction: "inbound", body });
  }

  return new Response(JSON.stringify({ ok: true }), {
    status: 200, headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
});
