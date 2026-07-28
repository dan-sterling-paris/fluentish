import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const GOOGLE_SERVICE_ACCOUNT_JSON = Deno.env.get("GOOGLE_SERVICE_ACCOUNT_JSON") ?? "";
const GOOGLE_CALENDAR_ID = Deno.env.get("GOOGLE_CALENDAR_ID") ?? "";
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const META_PIXEL_ID = Deno.env.get("META_PIXEL_ID") ?? "";
const META_CAPI_TOKEN = Deno.env.get("META_CAPI_TOKEN") ?? "";
// Optional. When set, CAPI events are routed to Events Manager > Test Events.
// Leave unset in production so real conversions are not flagged as test traffic.
const META_TEST_EVENT_CODE = Deno.env.get("META_TEST_EVENT_CODE") ?? "";

// Discovery call availability: 10:00-13:00 UK time, Mon-Fri.
// The window was 10:00-12:00, which excluded roughly 40% of the times people
// have historically booked (bookings ran through to 16:30 UK).
const SLOT_START_HOUR = 10;
const SLOT_END_HOUR = 13;
const SLOT_DURATION_MINS = 15;
const BUFFER_MINS = 30; // min gap required before/after any other appointment
// 12 slots/day at this window, so a cap of 10 would only ever show tomorrow.
const MAX_SLOTS = 18;
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

// ── Meta CAPI helpers ────────────────────────────────────────────────────────

async function sha256Hex(value: string): Promise<string> {
  const buf = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value.toLowerCase().trim())
  );
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

interface CAPIContext {
  fbc?: string;
  fbp?: string;
  client_ip?: string;
  client_ua?: string;
  source_url?: string;
}

async function sendMetaCAPI(
  eventName: string, eventId: string,
  email: string, phone: string,
  ctx?: CAPIContext
): Promise<{ status: number; body: string }> {
  if (!META_PIXEL_ID || !META_CAPI_TOKEN) {
    console.warn("Meta CAPI not configured (META_PIXEL_ID / META_CAPI_TOKEN missing)");
    return { status: 0, body: "not configured" };
  }

  const userData: Record<string, unknown> = { country: ["gb"] };

  if (email) {
    userData.em = [await sha256Hex(email)];
  }
  if (phone) {
    userData.ph = [await sha256Hex(phone.replace(/[^\d]/g, ""))];
  }
  if (ctx?.fbc) userData.fbc = ctx.fbc;
  if (ctx?.fbp) userData.fbp = ctx.fbp;
  if (ctx?.client_ip) userData.client_ip_address = ctx.client_ip;
  if (ctx?.client_ua) userData.client_user_agent = ctx.client_ua;

  const payload: Record<string, unknown> = {
    data: [{
      event_name: eventName,
      event_time: Math.floor(Date.now() / 1000),
      event_id: eventId,
      event_source_url: ctx?.source_url || "https://fluentish.co.uk/free-chat.html",
      action_source: "website",
      user_data: userData,
    }],
  };
  if (META_TEST_EVENT_CODE) payload.test_event_code = META_TEST_EVENT_CODE;

  const resp = await fetch(
    `https://graph.facebook.com/v21.0/${META_PIXEL_ID}/events?access_token=${META_CAPI_TOKEN}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
  );
  const respBody = await resp.text();
  if (!resp.ok) {
    console.error(`Meta CAPI error ${resp.status}: ${respBody}`);
  } else {
    console.log(`Meta CAPI ${eventName} sent (event_id=${eventId}): ${respBody}`);
  }
  return { status: resp.status, body: respBody };
}

// ── Google Calendar helpers ──────────────────────────────────────────────────

// Signed natively with Web Crypto rather than google-auth-library@9. That package
// drags a large Node dependency tree that Deno has to shim, and its cold-start boot
// is the most likely cause of this function intermittently dying before it could
// return a response - which surfaced as "Unable to load times" on the landing page.

function pemToPkcs8(pem: string): ArrayBuffer {
  const body = pem
    .replace(/-----BEGIN PRIVATE KEY-----/, "")
    .replace(/-----END PRIVATE KEY-----/, "")
    .replace(/\s+/g, "");
  const bin = atob(body);
  const buf = new ArrayBuffer(bin.length);
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return buf;
}

function b64url(input: string | Uint8Array): string {
  const bin = typeof input === "string"
    ? input
    : Array.from(input).map((b) => String.fromCharCode(b)).join("");
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Google access tokens last an hour; reuse within the worker's lifetime.
let cachedToken: { token: string; expiresAt: number } | null = null;

async function getGoogleAccessToken(): Promise<string> {
  if (cachedToken && Date.now() < cachedToken.expiresAt - 60_000) {
    return cachedToken.token;
  }

  const key = JSON.parse(GOOGLE_SERVICE_ACCOUNT_JSON);
  const now = Math.floor(Date.now() / 1000);

  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claim = b64url(JSON.stringify({
    iss: key.client_email,
    sub: "dan@sterlingparis.com", // domain-wide delegation, as before
    scope: "https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/calendar.events",
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  }));

  const cryptoKey = await crypto.subtle.importKey(
    "pkcs8",
    pemToPkcs8(key.private_key),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    cryptoKey,
    new TextEncoder().encode(`${header}.${claim}`),
  ));

  const resp = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: `${header}.${claim}.${b64url(signature)}`,
    }),
  });
  if (!resp.ok) {
    throw new Error(`Google token exchange failed ${resp.status}: ${await resp.text()}`);
  }
  const data = await resp.json();
  if (!data.access_token) throw new Error("No access_token in Google token response");

  cachedToken = {
    token: data.access_token,
    expiresAt: Date.now() + (data.expires_in ?? 3600) * 1000,
  };
  return cachedToken.token;
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

// A booking page that cannot show times is an outage. Previously it failed in
// silence and looked, to visitors, exactly like being fully booked.
let lastAlertAt = 0;
const ALERT_COOLDOWN_MS = 15 * 60 * 1000;

function notifyFailure(e: unknown) {
  const nowMs = Date.now();
  if (nowMs - lastAlertAt < ALERT_COOLDOWN_MS) return;
  lastAlertAt = nowMs;

  if (!RESEND_API_KEY) {
    console.error("ALERT: slot fetch failing and RESEND_API_KEY is unset - no alert sent");
    return;
  }
  const detail = e instanceof Error ? `${e.message}\n\n${e.stack ?? ""}` : String(e);
  sendEmail(
    "bonjour@fluentish.co.uk",
    "FluentISH: the booking page cannot load times",
    `<h2>The free-chat slot picker is failing</h2>
     <p>Visitors are being shown the "we couldn't load the calendar" fallback
     instead of available times.</p>
     <pre style="white-space:pre-wrap;font-size:12px">${detail}</pre>
     <p>Further alerts suppressed for 15 minutes.</p>`
  ).catch((sendErr) => console.error("Alert email failed:", sendErr));
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
    const url = new URL(req.url);

    // GET ?action=test-capi: diagnostic endpoint for verifying CAPI connectivity
    if (req.method === "GET" && url.searchParams.get("action") === "test-capi") {
      if (!META_TEST_EVENT_CODE) {
        return json({ ok: false, error: "META_TEST_EVENT_CODE not set. Set it first to avoid polluting live data." }, 400);
      }
      const result = await sendMetaCAPI("Lead", crypto.randomUUID(), "test@example.com", "+440000000000");
      return json({ ok: result.status === 200, capi_status: result.status, capi_response: result.body });
    }

    if (req.method === "GET") {
      return await handleGetSlots();
    }
    if (req.method === "POST") {
      const body = await req.json();

      // Lead CAPI: fire-and-forget from CTA click, deduplicated with browser pixel.
      // Meta requires at least one matchable user parameter (fbc, fbp, email, phone).
      // Ad traffic always has _fbc (from fbclid); organic visitors get _fbp once
      // fbevents.js loads. If neither is present, skip the CAPI call silently
      // (the browser pixel still fires).
      if (body.action === "lead") {
        const fbc = body.fbc || "";
        const fbp = body.fbp || "";
        if (!fbc && !fbp) {
          return json({ ok: true, skipped: "no_fbc_fbp" });
        }
        const clientIp = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
          || req.headers.get("cf-connecting-ip")
          || "";
        const clientUa = req.headers.get("user-agent") || "";
        const result = await sendMetaCAPI("Lead", body.event_id || crypto.randomUUID(), "", "", {
          fbc, fbp, client_ip: clientIp, client_ua: clientUa,
          source_url: body.source_url || "",
        });
        return json({ ok: result.status === 200 });
      }

      return await handleBooking(req, body);
    }
    return err("Method not allowed", 405);
  } catch (e) {
    console.error("Unhandled error:", e);
    if (req.method === "GET") notifyFailure(e);
    return json({ ok: false, error: "availability_unavailable" }, 500);
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

  // One freeBusy query covering the whole horizon. This was previously one request
  // per day, awaited in series - up to 14 sequential round-trips to Google on every
  // page load, with the count growing as the calendar filled up.
  const windowStart = new Date(Date.UTC(
    tomorrow.getUTCFullYear(), tomorrow.getUTCMonth(), tomorrow.getUTCDate(), 0, 0
  ));
  const windowEnd = new Date(windowStart);
  windowEnd.setUTCDate(windowEnd.getUTCDate() + MAX_DAYS_AHEAD + 1);

  const busy = await getBusyPeriods(
    accessToken,
    windowStart.toISOString(),
    windowEnd.toISOString()
  );

  for (let i = 0; i < MAX_DAYS_AHEAD && collected.length < MAX_SLOTS; i++) {
    const candidate = new Date(tomorrow);
    candidate.setUTCDate(candidate.getUTCDate() + i);

    // Skip weekends
    const dow = candidate.getUTCDay();
    if (dow === 0 || dow === 6) continue;

    // generateSlotsForDay compares absolute times, so the full busy list is safe
    // to pass - periods on other days simply never overlap.
    const daySlots = generateSlotsForDay(candidate.toISOString().slice(0, 10), busy);
    for (const s of daySlots) {
      if (collected.length >= MAX_SLOTS) break;
      collected.push(s);
    }
  }

  return json({ slots: collected });
}

// ── POST: book a slot ────────────────────────────────────────────────────────

async function handleBooking(req: Request, body: Record<string, unknown>): Promise<Response> {
  const { name, surname, email, phone, age_consent, slot_start, variant, visitor_id, honeypot, fbc, fbp } = body;

  // Honeypot: silently accept (bot: true tells client not to fire tracking pixels)
  if (honeypot) return json({ ok: true, bot: true });

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

  // Send emails + Meta CAPI in parallel (don't block on failure)
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
      sendMetaCAPI("Schedule", eventId, trimEmail, trimPhone, {
        fbc: (fbc as string) || "",
        fbp: (fbp as string) || "",
        client_ip: req.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
          || req.headers.get("cf-connecting-ip") || "",
        client_ua: req.headers.get("user-agent") || "",
      }),
    ]);
  } catch (e) {
    console.error("Post-booking task error (booking still saved):", e);
  }

  return json({ ok: true, date: dayLabel, time: timeStr, event_id: eventId });
}
