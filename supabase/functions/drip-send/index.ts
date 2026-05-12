import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const CLICKSEND_USERNAME = Deno.env.get("CLICKSEND_USERNAME") ?? "";
const CLICKSEND_API_KEY = Deno.env.get("CLICKSEND_API_KEY") ?? "";
const CLICKSEND_FROM = Deno.env.get("CLICKSEND_FROM") ?? "FluentISH";

// Working hours: 08:00–21:00 UK time.
// UK is UTC+1 (BST, late March–late October) or UTC+0 (GMT, otherwise).
// We approximate by using UTC+1 year-round — safe because it means we
// might wait one extra hour in winter (09:00 GMT instead of 08:00), never
// send too early.
const UK_OFFSET_HOURS = 1;
const WINDOW_START = 8;  // 08:00 UK
const WINDOW_END   = 21; // 21:00 UK

function db() {
  return createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
}

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

// Returns the earliest UTC timestamp at which a follow-up may be sent,
// given a base time and an offset in hours.
// If base+offset falls within the working window, returns base+offset.
// Otherwise returns the start of the next working window (next 08:00 UK).
function sendAfterUtc(baseUtc: Date, offsetHours: number): Date {
  const candidate = new Date(baseUtc.getTime() + offsetHours * 3_600_000);
  const ukHour = candidate.getUTCHours() + UK_OFFSET_HOURS;

  if (ukHour >= WINDOW_START && ukHour < WINDOW_END) {
    return candidate;
  }

  // Advance to the next 08:00 UK = 07:00 UTC
  const next = new Date(candidate);
  if (ukHour < WINDOW_START) {
    // Same day, just set to window start
    next.setUTCHours(WINDOW_START - UK_OFFSET_HOURS, 0, 0, 0);
  } else {
    // Past window end — next day
    next.setUTCDate(next.getUTCDate() + 1);
    next.setUTCHours(WINDOW_START - UK_OFFSET_HOURS, 0, 0, 0);
  }
  return next;
}

Deno.serve(async () => {
  const supabase = db();
  const now = new Date();

  // Fetch leads eligible for automated follow-ups:
  // - Not replied (last_message_direction is not 'inbound')
  // - Not in a terminal or engaged status
  // - At least one follow-up not yet sent
  const { data: leads, error } = await supabase
    .from("leads")
    .select("id, name, phone, created_at, last_message_direction, status, sms2_sent_at, sms3_sent_at")
    .not("status", "in", "(interested,call_booked,enrolled,lost)")
    .or("last_message_direction.is.null,last_message_direction.eq.outbound");

  if (error) {
    console.error("drip-send: query error", error);
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }

  let sent = 0;

  for (const lead of (leads ?? [])) {
    const createdAt = new Date(lead.created_at);
    const firstName = lead.name.split(" ")[0];

    // ── Follow-up 1 (sms_2) ────────────────────────────────────────────
    if (!lead.sms2_sent_at) {
      const sendAt = sendAfterUtc(createdAt, 24);
      if (now >= sendAt) {
        // Load template from db
        const { data: tmpl } = await supabase
          .from("templates")
          .select("body")
          .eq("key", "sms_2")
          .single();
        const body = (tmpl?.body ?? "Hi {name}, just checking in — have you had a chance to think about your French learning goals?")
          .replace("{name}", firstName);
        try {
          await sendSms(lead.phone, body);
          await supabase.from("messages").insert({ lead_id: lead.id, direction: "outbound", body });
          await supabase.from("leads").update({ sms2_sent_at: now.toISOString(), updated_at: now.toISOString() }).eq("id", lead.id);
          console.log(`drip-send: follow-up 1 → ${lead.name} (${lead.phone})`);
          sent++;
        } catch (e) {
          console.error(`drip-send: follow-up 1 failed for ${lead.name}:`, e);
        }
        // Only one follow-up per lead per run
        continue;
      }
    }

    // ── Follow-up 2 (sms_3) ────────────────────────────────────────────
    if (lead.sms2_sent_at && !lead.sms3_sent_at) {
      const sendAt = sendAfterUtc(createdAt, 48);
      if (now >= sendAt) {
        const { data: tmpl } = await supabase
          .from("templates")
          .select("body")
          .eq("key", "sms_3")
          .single();
        const body = (tmpl?.body ?? "Hi {name}, I have some availability this week if you'd like to book a free 15-minute discovery call!")
          .replace("{name}", firstName);
        try {
          await sendSms(lead.phone, body);
          await supabase.from("messages").insert({ lead_id: lead.id, direction: "outbound", body });
          await supabase.from("leads").update({ sms3_sent_at: now.toISOString(), updated_at: now.toISOString() }).eq("id", lead.id);
          console.log(`drip-send: follow-up 2 → ${lead.name} (${lead.phone})`);
          sent++;
        } catch (e) {
          console.error(`drip-send: follow-up 2 failed for ${lead.name}:`, e);
        }
      }
    }
  }

  console.log(`drip-send: run complete. ${sent} message(s) sent.`);
  return new Response(JSON.stringify({ sent }), {
    headers: { "Content-Type": "application/json" },
  });
});
