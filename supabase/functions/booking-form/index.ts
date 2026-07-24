import { createClient } from "npm:@supabase/supabase-js@2";
import { GoogleAuth } from "npm:google-auth-library@9";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const GOOGLE_SERVICE_ACCOUNT_JSON = Deno.env.get("GOOGLE_SERVICE_ACCOUNT_JSON") ?? "";
const GOOGLE_CALENDAR_ID = Deno.env.get("GOOGLE_CALENDAR_ID") ?? "";
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";

// Discovery call availability: 10:00-13:00 UK time, Mon-Fri
const SLOT_START_HOUR = 10;
const SLOT_END_HOUR = 12;
const SLOT_DURATION_MINS = 15;
const BUFFER_MINS = 30; // min gap required before/after any other appointment
const MAX_SLOTS = 10;
const MAX_DAYS_AHEAD = 20;

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
  });
}

function err(message: string, status: number) {
  return json({ ok: false, error: message }, status);
}

// ── Google Calendar helpers ──────────────────────────────────────────────────

async function getGoogleAccessToken(): Promise<string> {
  const keyFile = JSON.parse(GOOGLE_SERVICE_ACCOUNT_JSON);
  const auth = new GoogleAuth({
    credentials: keyFile,
    clientOptions: { subject: "dan@sterlingparis.com" },
    scopes: [
      "https://www.googleapis.com/auth/calendar",
      "https://www.googleapis.com/auth/calendar.events",
    ],
  });
  const client = await auth.getClient();
  const token = await client.getAccessToken();
  if (!token.token) throw new Error("Failed to obtain Google access token");
  return token.token;
}

// Returns busy intervals for a given time range
async function getBusyPeriods(
  accessToken: string,
  timeMin: string,
  timeMax: string
): Promise<Array<{ start: string; end: string }>> {
  const resp = await fetch(
    "https://www.googleapis.com/calendar/v3/freeBusy",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        timeMin,
        timeMax,
        items: [{ id: GOOGLE_CALENDAR_ID }],
      }),
    }
  );
  if (!resp.ok) throw new Error(`Calendar freebusy error ${resp.status}`);
  const data = await resp.json();
  return data.calendars?.[GOOGLE_CALENDAR_ID]?.busy ?? [];
}

// Create a calendar event and return the event ID
async function createCalendarEvent(
  accessToken: string,
  summary: string,
  description: string,
  startIso: string,
  attendeeEmail: string
): Promise<string> {
  const start = new Date(startIso);
  const end = new Date(start.getTime() + 15 * 60 * 1000); // 15-min call
  const resp = await fetch(
    `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(GOOGLE_CALENDAR_ID)}/events?conferenceDataVersion=1&sendUpdates=all`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        summary,
        description,
        start: { dateTime: start.toISOString() },
        end: { dateTime: end.toISOString() },
        attendees: [{ email: attendeeEmail }],
        conferenceData: {
          createRequest: {
            requestId: crypto.randomUUID(),
            conferenceSolutionKey: { type: "hangoutsMeet" },
          },
        },
        reminders: { useDefault: true },
      }),
    }
  );
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Calendar event create error ${resp.status}: ${body}`);
  }
  const event = await resp.json();
  return event.id;
}

// ── Slot calculation ─────────────────────────────────────────────────────────

interface Slot {
  date: string;   // "2026-07-24"
  day: string;    // "Thu 24 Jul"
  time: string;   // "10:00"
  iso: string;    // "2026-07-24T09:00:00Z" (UTC)
}

function generateSlotsForDay(
  dateStr: string,
  busyPeriods: Array<{ start: string; end: string }>
): Slot[] {
  const slots: Slot[] = [];
  const d = new Date(dateStr + "T00:00:00Z");

  // Format day label
  const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const dayLabel = `${dayNames[d.getUTCDay()]} ${d.getUTCDate()} ${monthNames[d.getUTCMonth()]}`;

  // Calculate UK offset for this date
  const ukOffset = getUkOffsetHours(d);

  for (let h = SLOT_START_HOUR; h < SLOT_END_HOUR; h++) {
    for (let m = 0; m < 60; m += SLOT_DURATION_MINS) {
      // Slot in UTC
      const slotStartUtc = new Date(Date.UTC(
        d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(),
        h - ukOffset, m
      ));
      const slotEndUtc = new Date(slotStartUtc.getTime() + SLOT_DURATION_MINS * 60 * 1000);

      // Check if slot overlaps with any busy period (including 30-min buffer)
      const bufferMs = BUFFER_MINS * 60 * 1000;
      const isBusy = busyPeriods.some((bp) => {
        const bStart = new Date(bp.start).getTime() - bufferMs;
        const bEnd = new Date(bp.end).getTime() + bufferMs;
        return slotStartUtc.getTime() < bEnd && slotEndUtc.getTime() > bStart;
      });

      if (!isBusy) {
        const timeStr = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
        slots.push({
          date: dateStr,
          day: dayLabel,
          time: timeStr,
          iso: slotStartUtc.toISOString(),
        });
      }
    }
  }
  return slots;
}

// Get UK offset in hours for a given date (handles BST/GMT)
function getUkOffsetHours(date: Date): number {
  // Create a date string in UK timezone and compare with UTC
  const ukStr = date.toLocaleString("en-GB", { timeZone: "Europe/London", hour12: false });
  const ukParts = ukStr.split(", ")[1]?.split(":") ?? [];
  const ukHour = parseInt(ukParts[0] ?? "0", 10);
  const utcHour = date.getUTCHours();
  let offset = ukHour - utcHour;
  if (offset < 0) offset += 24;
  if (offset > 12) offset -= 24;
  return offset;
}

// ── Email helpers ────────────────────────────────────────────────────────────

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

function confirmationEmailHtml(name: string, day: string, time: string): string {
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
      <p style="margin:0 0 16px;font-size:16px;color:#003359;font-weight:600;">Thanks ${name}!</p>
      <p style="margin:0 0 20px;font-size:15px;color:#374151;line-height:1.6;">
        Your free 15-minute chat is confirmed:
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

function notificationEmailHtml(
  name: string,
  surname: string,
  email: string,
  phone: string,
  day: string,
  time: string,
  variant: string,
  iso: string
): string {
  return `
<h2>New discovery call booking</h2>
<table style="border-collapse:collapse;font-family:sans-serif;font-size:14px;">
  <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Name</td><td>${name} ${surname}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Email</td><td><a href="mailto:${email}">${email}</a></td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Phone</td><td>${phone}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Slot</td><td>${day} at ${time} UK</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Variant</td><td>${variant}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:600;">ISO</td><td>${iso}</td></tr>
  <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Submitted</td><td>${new Date().toISOString()}</td></tr>
</table>`;
}

// ── Main handler ─────────────────────────────────────────────────────────────

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  try {
    if (req.method === "GET") {
      return await handleGetSlots();
    }
    if (req.method === "POST") {
      return await handleBooking(req);
    }
    return err("Method not allowed", 405);
  } catch (e) {
    console.error("Unhandled error:", e);
    return err("Internal error", 500);
  }
});

// ── GET: return next 10 available slots ──────────────────────────────────────

async function handleGetSlots(): Promise<Response> {
  const accessToken = await getGoogleAccessToken();
  const collected: Slot[] = [];

  // Start from tomorrow (next working day)
  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);

  for (let i = 0; i < MAX_DAYS_AHEAD && collected.length < MAX_SLOTS; i++) {
    const candidate = new Date(tomorrow);
    candidate.setUTCDate(candidate.getUTCDate() + i);

    // Skip weekends
    const dow = candidate.getUTCDay();
    if (dow === 0 || dow === 6) continue;

    const dateStr = candidate.toISOString().slice(0, 10);
    const ukOffset = getUkOffsetHours(candidate);

    // Query window: slot range +/- buffer to catch nearby appointments
    const dayStartUtc = new Date(Date.UTC(
      candidate.getUTCFullYear(), candidate.getUTCMonth(), candidate.getUTCDate(),
      SLOT_START_HOUR - ukOffset, -BUFFER_MINS
    ));
    const dayEndUtc = new Date(Date.UTC(
      candidate.getUTCFullYear(), candidate.getUTCMonth(), candidate.getUTCDate(),
      SLOT_END_HOUR - ukOffset, BUFFER_MINS
    ));

    const busy = await getBusyPeriods(
      accessToken,
      dayStartUtc.toISOString(),
      dayEndUtc.toISOString()
    );

    const daySlots = generateSlotsForDay(dateStr, busy);
    for (const s of daySlots) {
      if (collected.length >= MAX_SLOTS) break;
      collected.push(s);
    }
  }

  return json({ slots: collected });
}

// ── POST: book a slot ────────────────────────────────────────────────────────

async function handleBooking(req: Request): Promise<Response> {
  const body = await req.json();
  const { name, surname, email, phone, age_consent, slot_start, variant, visitor_id, honeypot } = body;

  // Honeypot: silently accept
  if (honeypot) return json({ ok: true });

  // Validate
  const trimName = (name ?? "").trim();
  const trimSurname = (surname ?? "").trim();
  const trimEmail = (email ?? "").trim();
  const trimPhone = (phone ?? "").trim();
  if (!trimName || trimName.length > 100) return err("Please enter your first name.", 400);
  if (!trimSurname || trimSurname.length > 100) return err("Please enter your surname.", 400);
  if (!trimEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimEmail)) {
    return err("Please enter a valid email address.", 400);
  }
  if (!trimPhone || trimPhone.length < 6) return err("Please enter your phone number.", 400);
  if (!age_consent) return err("You must confirm you are 18 or over.", 400);
  if (!slot_start) return err("Please select a time slot.", 400);
  if (!["A", "B"].includes(variant)) return err("Invalid variant.", 400);

  const slotDate = new Date(slot_start);
  if (isNaN(slotDate.getTime())) return err("Invalid slot time.", 400);

  // Re-check availability (race condition prevention, including 30-min buffer)
  const accessToken = await getGoogleAccessToken();
  const bufferMs = BUFFER_MINS * 60 * 1000;
  const checkStart = new Date(slotDate.getTime() - bufferMs);
  const checkEnd = new Date(slotDate.getTime() + SLOT_DURATION_MINS * 60 * 1000 + bufferMs);
  const busy = await getBusyPeriods(
    accessToken,
    checkStart.toISOString(),
    checkEnd.toISOString()
  );

  if (busy.length > 0) {
    return json({ ok: false, error: "slot_taken" }, 409);
  }

  // Format for display
  const dayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const ukOffset = getUkOffsetHours(slotDate);
  const ukHour = slotDate.getUTCHours() + ukOffset;
  const ukMin = slotDate.getUTCMinutes();
  const timeStr = `${String(ukHour).padStart(2, "0")}:${String(ukMin).padStart(2, "0")}`;

  // For the day label, use the date in UK timezone
  const ukDate = new Date(slotDate.getTime() + ukOffset * 3600 * 1000);
  const dayLabel = `${dayNames[ukDate.getUTCDay()]} ${ukDate.getUTCDate()} ${monthNames[ukDate.getUTCMonth()]}`;

  // Create Google Calendar event
  const fullName = `${trimName} ${trimSurname}`;
  const eventId = await createCalendarEvent(
    accessToken,
    `FluentISH Discovery Call - ${fullName}`,
    `Free 15-minute discovery call.\nName: ${fullName}\nEmail: ${trimEmail}\nPhone: ${trimPhone}`,
    slot_start,
    trimEmail
  );

  // Insert into database
  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

  await supabase.from("booking_requests").insert({
    name: trimName,
    surname: trimSurname,
    email: trimEmail,
    phone: trimPhone,
    age_consent: true,
    slot_start,
    variant,
    calendar_event_id: eventId,
  });

  // Track in ab_events
  if (visitor_id) {
    await supabase.from("ab_events").insert({
      visitor_id,
      variant,
      event_type: "booking",
    });
  }

  // Send emails (don't block on failure)
  try {
    await Promise.all([
      sendEmail(
        trimEmail,
        `Thanks for booking, ${trimName}! Here's what happens next`,
        confirmationEmailHtml(trimName, dayLabel, timeStr)
      ),
      sendEmail(
        "bonjour@fluentish.co.uk",
        `New booking request from ${trimName}`,
        notificationEmailHtml(trimName, trimSurname, trimEmail, trimPhone, dayLabel, timeStr, variant, slot_start)
      ),
    ]);
  } catch (e) {
    console.error("Email send error (booking still saved):", e);
  }

  return json({ ok: true, date: dayLabel, time: timeStr });
}
