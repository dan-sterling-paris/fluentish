import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const CLICKSEND_USERNAME = Deno.env.get("CLICKSEND_USERNAME") ?? "";
const CLICKSEND_API_KEY = Deno.env.get("CLICKSEND_API_KEY") ?? "";
const CLICKSEND_FROM = Deno.env.get("CLICKSEND_FROM") ?? "FluentISH";
const TEMPLATE_1 = Deno.env.get("TEMPLATE_1") ?? "Hi {name}, thanks for your interest in French lessons! Are you looking for in-person or online classes?";
const TEMPLATE_2 = Deno.env.get("TEMPLATE_2") ?? "Hi {name}, just checking in — have you had a chance to think about your French learning goals?";
const TEMPLATE_3 = Deno.env.get("TEMPLATE_3") ?? "Hi {name}, I have some availability this week if you'd like to book a free 15-minute discovery call!";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function db() {
  return createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
}

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}

function err(message: string, status: number) {
  return json({ error: message }, status);
}

// ── ClickSend ─────────────────────────────────────────────────────────────────

async function sendSms(phone: string, body: string) {
  const token = btoa(`${CLICKSEND_USERNAME}:${CLICKSEND_API_KEY}`);
  const resp = await fetch("https://rest.clicksend.com/v3/sms/send", {
    method: "POST",
    headers: {
      Authorization: `Basic ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messages: [{ source: "sdk", from: CLICKSEND_FROM, to: phone, body }],
    }),
  });
  if (!resp.ok) throw new Error(`ClickSend error ${resp.status}`);
  return resp.json();
}

// ── Route handlers ────────────────────────────────────────────────────────────

async function handleConfig() {
  return json({ template_2: TEMPLATE_2, template_3: TEMPLATE_3 });
}

async function handleListLeads(url: URL) {
  const supabase = db();
  const status = url.searchParams.get("status");
  let query = supabase.from("leads").select("*").order("updated_at", { ascending: false });
  if (status && status !== "all") query = query.eq("status", status);
  const { data, error } = await query;
  if (error) return err(error.message, 500);
  return json(data);
}

async function handleGetMessages(leadId: string) {
  const supabase = db();
  const { data, error } = await supabase
    .from("messages")
    .select("*")
    .eq("lead_id", leadId)
    .order("sent_at", { ascending: true });
  if (error) return err(error.message, 500);
  return json(data);
}

async function handleSendMessage(leadId: string, req: Request) {
  const supabase = db();
  const { body: msgBody } = await req.json();
  if (!msgBody?.trim()) return err("Message body cannot be empty", 400);

  const { data: lead, error: leadErr } = await supabase
    .from("leads").select("*").eq("id", leadId).single();
  if (leadErr || !lead) return err("Lead not found", 404);

  await sendSms(lead.phone, msgBody);

  const { data: msg, error: msgErr } = await supabase
    .from("messages").insert({ lead_id: leadId, direction: "outbound", body: msgBody }).select().single();
  if (msgErr) return err(msgErr.message, 500);

  return json({ ok: true, message: msg });
}

async function handleSendTemplate(leadId: string, templateNum: string, req: Request) {
  const supabase = db();
  const n = parseInt(templateNum, 10);
  const tmpl = n === 2 ? TEMPLATE_2 : n === 3 ? TEMPLATE_3 : null;
  if (!tmpl) return err("Invalid template number (use 2 or 3)", 400);

  const { data: lead, error: leadErr } = await supabase
    .from("leads").select("*").eq("id", leadId).single();
  if (leadErr || !lead) return err("Lead not found", 404);

  const body = tmpl.replace("{name}", lead.name);
  await sendSms(lead.phone, body);

  const { data: msg, error: msgErr } = await supabase
    .from("messages").insert({ lead_id: leadId, direction: "outbound", body }).select().single();
  if (msgErr) return err(msgErr.message, 500);

  if (lead.status === "new") {
    await supabase.from("leads")
      .update({ status: "auto_contacted", updated_at: new Date().toISOString() })
      .eq("id", leadId);
  }

  return json({ ok: true, message: msg });
}

async function handleUpdateStatus(leadId: string, req: Request) {
  const supabase = db();
  const { status } = await req.json();
  const valid = ["new", "auto_contacted", "replied", "booked"];
  if (!valid.includes(status)) return err("Invalid status", 400);

  const { error } = await supabase
    .from("leads")
    .update({ status, updated_at: new Date().toISOString() })
    .eq("id", leadId);
  if (error) return err(error.message, 500);

  return json({ ok: true });
}

// ── Router ────────────────────────────────────────────────────────────────────

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const url = new URL(req.url);
  // Strip the function prefix: /functions/v1/crm-api/...
  const path = url.pathname.replace(/^\/functions\/v1\/crm-api/, "").replace(/\/$/, "") || "/";

  // GET /config
  if (req.method === "GET" && path === "/config") return handleConfig();

  // GET /leads
  if (req.method === "GET" && path === "/leads") return handleListLeads(url);

  // GET /leads/:id/messages
  const msgMatch = path.match(/^\/leads\/(\d+)\/messages$/);
  if (req.method === "GET" && msgMatch) return handleGetMessages(msgMatch[1]);

  // POST /leads/:id/send
  const sendMatch = path.match(/^\/leads\/(\d+)\/send$/);
  if (req.method === "POST" && sendMatch) return handleSendMessage(sendMatch[1], req);

  // POST /leads/:id/template/:n
  const tmplMatch = path.match(/^\/leads\/(\d+)\/template\/(\d+)$/);
  if (req.method === "POST" && tmplMatch) return handleSendTemplate(tmplMatch[1], tmplMatch[2], req);

  // PATCH /leads/:id/status
  const statusMatch = path.match(/^\/leads\/(\d+)\/status$/);
  if (req.method === "PATCH" && statusMatch) return handleUpdateStatus(statusMatch[1], req);

  return err("Not found", 404);
});
