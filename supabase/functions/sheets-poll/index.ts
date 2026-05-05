import { createClient } from "npm:@supabase/supabase-js@2";
import { GoogleAuth } from "npm:google-auth-library@9";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const CLICKSEND_USERNAME = Deno.env.get("CLICKSEND_USERNAME") ?? "";
const CLICKSEND_API_KEY = Deno.env.get("CLICKSEND_API_KEY") ?? "";
const CLICKSEND_FROM = Deno.env.get("CLICKSEND_FROM") ?? "FluentISH";
const GOOGLE_SERVICE_ACCOUNT_JSON = Deno.env.get("GOOGLE_SERVICE_ACCOUNT_JSON") ?? "";
const SPREADSHEET_ID = Deno.env.get("SPREADSHEET_ID") ?? "";
const SHEET_NAME = Deno.env.get("SHEET_NAME") ?? "Sheet1";
const INGESTED_MARKER = Deno.env.get("INGESTED_MARKER") ?? "Ingested";
const TEMPLATE_1 = Deno.env.get("TEMPLATE_1") ?? "Hi {name}, thanks for your interest in French lessons! Are you looking for in-person or online classes?";

// Column indices (1-based, same as Python config)
const NAME_COL = parseInt(Deno.env.get("SHEET_NAME_COL") ?? "1", 10) - 1;   // 0-indexed
const PHONE_COL = parseInt(Deno.env.get("SHEET_PHONE_COL") ?? "2", 10) - 1;
const STATUS_COL = parseInt(Deno.env.get("SHEET_STATUS_COL") ?? "3", 10) - 1;

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

async function getAccessToken(): Promise<string> {
  const keyFile = JSON.parse(GOOGLE_SERVICE_ACCOUNT_JSON);
  const auth = new GoogleAuth({
    credentials: keyFile,
    scopes: ["https://www.googleapis.com/auth/spreadsheets"],
  });
  const client = await auth.getClient();
  const token = await client.getAccessToken();
  if (!token.token) throw new Error("Failed to obtain Google access token");
  return token.token;
}

async function fetchSheetRows(accessToken: string): Promise<string[][]> {
  const range = encodeURIComponent(`${SHEET_NAME}!A2:Z`);
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${SPREADSHEET_ID}/values/${range}`;
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!resp.ok) throw new Error(`Sheets API error ${resp.status}`);
  const data = await resp.json();
  return data.values ?? [];
}

async function writeIngestedMarker(accessToken: string, rowIndex: number): Promise<void> {
  const colLetter = String.fromCharCode(65 + STATUS_COL); // A=65
  const range = encodeURIComponent(`${SHEET_NAME}!${colLetter}${rowIndex}`);
  const url = `https://sheets.googleapis.com/v4/spreadsheets/${SPREADSHEET_ID}/values/${range}?valueInputOption=RAW`;
  const resp = await fetch(url, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ values: [[INGESTED_MARKER]] }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Sheets write error ${resp.status}: ${text}`);
  }
}

async function sendSms(phone: string, body: string): Promise<void> {
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
}

Deno.serve(async (_req: Request) => {
  if (!GOOGLE_SERVICE_ACCOUNT_JSON || !SPREADSHEET_ID) {
    console.log("sheets-poll: credentials not configured, skipping");
    return new Response(JSON.stringify({ skipped: true }), { status: 200 });
  }

  const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

  // Load sms_1 template from DB, fall back to env var
  const { data: tmplRow } = await supabase.from("templates").select("body").eq("key", "sms_1").single();
  const template1 = tmplRow?.body ?? TEMPLATE_1;

  let accessToken: string;
  try {
    accessToken = await getAccessToken();
  } catch (e) {
    console.error("sheets-poll: failed to authenticate with Google:", e);
    return new Response(JSON.stringify({ error: "Google auth failed" }), { status: 500 });
  }

  let rows: string[][];
  try {
    rows = await fetchSheetRows(accessToken);
  } catch (e) {
    console.error("sheets-poll: failed to fetch sheet rows:", e);
    return new Response(JSON.stringify({ error: "Sheets fetch failed" }), { status: 500 });
  }

  let ingested = 0;

  for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const rowIndex = i + 2; // 1-based, row 1 is header
    try {
      const name = (row[NAME_COL] ?? "").trim();
      const rawPhone = (row[PHONE_COL] ?? "").trim();
      const statusCell = (row[STATUS_COL] ?? "").trim();

      if (!name || !rawPhone) continue;
      if (statusCell === INGESTED_MARKER) continue;

      const phone = normalizePhone(rawPhone);

      // Check if already in DB (race-safe dedup)
      const { data: existing } = await supabase
        .from("leads").select("id").eq("phone", phone).single();

      if (existing) {
        // DB has it but sheet wasn't marked — write the marker and continue
        await writeIngestedMarker(accessToken, rowIndex).catch((e) =>
          console.error(`sheets-poll: catch-up marker failed for row ${rowIndex}:`, e)
        );
        continue;
      }

      // Insert lead
      const { data: lead, error: insertErr } = await supabase
        .from("leads")
        .insert({ name, phone, status: "auto_contacted" })
        .select("id").single();

      if (insertErr || !lead) {
        console.error(`sheets-poll: insert failed for row ${rowIndex}:`, insertErr);
        continue;
      }

      // Send initial SMS
      const firstName = name.split(" ")[0];
      const smsBody = template1.replace("{name}", firstName);
      try {
        await sendSms(phone, smsBody);
        await supabase.from("messages")
          .insert({ lead_id: lead.id, direction: "outbound", body: smsBody });
      } catch (e) {
        console.error(`sheets-poll: SMS failed for ${name} (${phone}):`, e);
      }

      // Always write ingested marker, even if SMS failed
      await writeIngestedMarker(accessToken, rowIndex).catch((e) =>
        console.error(`sheets-poll: marker write failed for row ${rowIndex}:`, e)
      );

      ingested++;
    } catch (e) {
      console.error(`sheets-poll: error processing row ${rowIndex}:`, e);
    }
  }

  console.log(`sheets-poll: ingested ${ingested} new lead(s) from ${rows.length} row(s)`);
  return new Response(JSON.stringify({ ok: true, ingested }), { status: 200 });
});
