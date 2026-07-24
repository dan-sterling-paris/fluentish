import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const CRON_AUTH_TOKEN = Deno.env.get("CRON_AUTH_TOKEN") ?? "";

function db() {
  return createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
}

async function sendEmail(to: string, subject: string, html: string) {
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: "Dan at FluentISH <bonjour@fluentish.co.uk>",
      to,
      subject,
      html,
    }),
  });
  if (!resp.ok) {
    const body = await resp.text();
    console.error(`Resend error ${resp.status}: ${body}`);
  }
  return resp.ok;
}

function reminderEmailHtml(name: string, day: string, time: string): string {
  return `
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f7f4ef;">
  <div style="max-width:500px;margin:0 auto;padding:32px 24px;">
    <div style="background:#003359;color:#fff;padding:20px 24px;border-radius:12px 12px 0 0;text-align:center;">
      <h1 style="margin:0;font-size:20px;font-weight:700;letter-spacing:0.5px;">FluentISH</h1>
    </div>
    <div style="background:#fff;padding:28px 24px;border-radius:0 0 12px 12px;border:1px solid #e7e5e4;border-top:none;">
      <p style="margin:0 0 16px;font-size:16px;color:#003359;font-weight:600;">Hi ${name}, just a quick reminder!</p>
      <p style="margin:0 0 20px;font-size:15px;color:#374151;line-height:1.6;">
        Your free 15-minute chat is coming up in about an hour:
      </p>
      <div style="background:#f7f4ef;border-radius:8px;padding:16px 20px;margin:0 0 20px;text-align:center;">
        <p style="margin:0;font-size:18px;font-weight:700;color:#003359;">${day}</p>
        <p style="margin:4px 0 0;font-size:24px;font-weight:700;color:#C8102E;">${time}</p>
        <p style="margin:4px 0 0;font-size:13px;color:#6b7280;">UK time</p>
      </div>
      <p style="margin:0 0 16px;font-size:14px;color:#374151;line-height:1.6;">
        No preparation needed. We'll have a relaxed chat about your French goals and whether FluentISH is the right fit.
      </p>
      <p style="margin:0;font-size:14px;color:#374151;line-height:1.6;">
        A bientot!<br><strong>Dan</strong>
      </p>
    </div>
    <p style="text-align:center;margin:16px 0 0;font-size:12px;color:#9ca3af;">
      FluentISH &middot; <a href="mailto:bonjour@fluentish.co.uk" style="color:#9ca3af;">bonjour@fluentish.co.uk</a>
    </p>
  </div>
</body>
</html>`;
}

// Get UK offset in hours for a given date (handles BST/GMT)
function getUkOffsetHours(date: Date): number {
  const ukStr = date.toLocaleString("en-GB", { timeZone: "Europe/London", hour12: false });
  const ukParts = ukStr.split(", ")[1]?.split(":") ?? [];
  const ukHour = parseInt(ukParts[0] ?? "0", 10);
  const utcHour = date.getUTCHours();
  let offset = ukHour - utcHour;
  if (offset < 0) offset += 24;
  if (offset > 12) offset -= 24;
  return offset;
}

Deno.serve(async (req: Request) => {
  // Auth check (called by pg_cron)
  const auth = req.headers.get("Authorization")?.replace("Bearer ", "");
  if (CRON_AUTH_TOKEN && auth !== CRON_AUTH_TOKEN) {
    return new Response("Unauthorised", { status: 401 });
  }

  const now = new Date();
  // Find bookings starting between 55 and 65 minutes from now, not yet reminded
  const windowStart = new Date(now.getTime() + 55 * 60 * 1000);
  const windowEnd = new Date(now.getTime() + 65 * 60 * 1000);

  const supabase = db();
  const { data: bookings, error } = await supabase
    .from("booking_requests")
    .select("id, name, email, slot_start")
    .eq("status", "confirmed")
    .eq("reminder_sent", false)
    .gte("slot_start", windowStart.toISOString())
    .lte("slot_start", windowEnd.toISOString());

  if (error) {
    console.error("Query error:", error);
    return new Response(JSON.stringify({ error: error.message }), { status: 500 });
  }

  let sent = 0;
  for (const booking of bookings ?? []) {
    const slotDate = new Date(booking.slot_start);
    const ukOffset = getUkOffsetHours(slotDate);
    const ukHour = slotDate.getUTCHours() + ukOffset;
    const ukMin = slotDate.getUTCMinutes();
    const timeStr = `${String(ukHour).padStart(2, "0")}:${String(ukMin).padStart(2, "0")}`;

    const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const ukDate = new Date(slotDate.getTime() + ukOffset * 3600 * 1000);
    const dayLabel = `${dayNames[ukDate.getUTCDay()]} ${ukDate.getUTCDate()} ${monthNames[ukDate.getUTCMonth()]}`;

    const ok = await sendEmail(
      booking.email,
      `Reminder: your free chat is in 1 hour, ${booking.name}!`,
      reminderEmailHtml(booking.name, dayLabel, timeStr)
    );

    if (ok) {
      await supabase
        .from("booking_requests")
        .update({ reminder_sent: true })
        .eq("id", booking.id);
      sent++;
    }
  }

  return new Response(JSON.stringify({ ok: true, reminders_sent: sent }), {
    headers: { "Content-Type": "application/json" },
  });
});
