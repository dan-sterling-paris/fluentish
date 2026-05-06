import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL              = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const CALENDLY_SIGNING_KEY      = Deno.env.get("CALENDLY_SIGNING_KEY")!;

// Invite emails redirect here so the customer can set their password.
const PORTAL_URL = `${SUPABASE_URL}/storage/v1/object/public/portal/index.html`;

// ── Signature verification ─────────────────────────────────────────────────────
// Calendly uses the same t=..,v1=.. HMAC-SHA256 format as Stripe.
async function verifySignature(
  rawBody: string,
  sigHeader: string,
  secret: string,
): Promise<boolean> {
  const parts: Record<string, string[]> = {};
  for (const segment of sigHeader.split(",")) {
    const eq = segment.indexOf("=");
    if (eq === -1) continue;
    const k = segment.slice(0, eq);
    const v = segment.slice(eq + 1);
    (parts[k] ??= []).push(v);
  }

  const timestamp  = parts["t"]?.[0];
  const signatures = parts["v1"] ?? [];
  if (!timestamp || signatures.length === 0) return false;

  // Reject events older than 5 minutes (replay-attack protection)
  const age = Math.floor(Date.now() / 1000) - parseInt(timestamp, 10);
  if (age > 300) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`${timestamp}.${rawBody}`),
  );
  const computed = Array.from(new Uint8Array(mac))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  return signatures.some((sig) => sig === computed);
}

// ── Phone normalisation (same logic as inbound-webhook) ───────────────────────
function normalizePhone(raw: string): string {
  let d = raw.replace(/[^\d+]/g, "");
  if (d.startsWith("00"))                        d = "+" + d.slice(2);
  else if (d.startsWith("07") && d.length === 11) d = "+44" + d.slice(1);
  else if (d.startsWith("7")  && d.length === 10) d = "+44" + d;
  else if (!d.startsWith("+"))                   d = "+" + d;
  return d;
}

// ── Handler ───────────────────────────────────────────────────────────────────
Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const rawBody   = await req.text();
  const sigHeader = req.headers.get("Calendly-Webhook-Signature") ?? "";

  if (!await verifySignature(rawBody, sigHeader, CALENDLY_SIGNING_KEY)) {
    console.error("calendly-webhook: invalid signature");
    return new Response("Invalid signature", { status: 400 });
  }

  const body = JSON.parse(rawBody);

  // Acknowledge everything that isn't a new booking
  if (body.event !== "invitee.created") {
    return new Response(JSON.stringify({ received: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  const invitee = body.payload;
  const email   = invitee.email ?? "";
  const name    = invitee.name  ?? "";

  // Only provision a portal for paid bookings.
  // Free discovery calls have payment === null; skip those.
  const payment = invitee.payment;
  if (!payment || payment.status !== "paid") {
    console.log("calendly-webhook: free/unpaid booking — skipping portal for", email);
    return new Response(JSON.stringify({ received: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!email) {
    console.error("calendly-webhook: no email in payload");
    return new Response(JSON.stringify({ received: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Extract phone from the "Your phone number" question (added to the event type)
  const phoneQA  = (invitee.questions_and_answers ?? []).find(
    (qa: { question: string }) => qa.question.toLowerCase().includes("phone"),
  );
  const rawPhone = phoneQA?.answer ?? "";
  const phone    = rawPhone ? normalizePhone(rawPhone) : null;

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

  // ── 1. Invite customer to the portal ────────────────────────────────────────
  // inviteUserByEmail creates an auth.users row with invited_at set, which
  // triggers on_auth_user_invited → auto-creates their customer_profiles row.
  // Calendly sends an invite email; clicking the link lands on PORTAL_URL
  // where the customer sets a password on their first visit.
  const { error: inviteError } = await supabase.auth.admin.inviteUserByEmail(
    email,
    { data: { full_name: name }, redirectTo: PORTAL_URL },
  );

  const alreadyRegistered =
    inviteError?.message?.toLowerCase().includes("already been registered") ||
    inviteError?.message?.toLowerCase().includes("user already exists");

  if (inviteError && !alreadyRegistered) {
    console.error("calendly-webhook: invite failed for", email, inviteError.message);
    // Return 200 so Calendly doesn't retry endlessly — the error is logged.
  }

  // ── 2. Fill in customer_profiles with name + phone ───────────────────────────
  // The trigger creates the row; we patch in any fields it couldn't set.
  // For returning customers this also refreshes their info.
  const profileUpdate: Record<string, string | null> = { email };
  if (name)  profileUpdate.full_name = name;
  if (phone) profileUpdate.phone     = phone;

  const { error: profileError } = await supabase
    .from("customer_profiles")
    .update(profileUpdate)
    .eq("email", email);

  if (profileError) {
    console.error("calendly-webhook: profile update failed", email, profileError.message);
  }

  // ── 3. Mark matching lead as enrolled ───────────────────────────────────────
  if (phone) {
    await supabase
      .from("leads")
      .update({ status: "enrolled", updated_at: new Date().toISOString() })
      .eq("phone", phone);
  }

  console.log(
    "calendly-webhook: portal provisioned for",
    email,
    alreadyRegistered ? "(existing user)" : "(new user)",
  );

  return new Response(JSON.stringify({ received: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
