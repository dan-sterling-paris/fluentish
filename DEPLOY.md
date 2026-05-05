# Fluentish Lead System — Deployment Guide

This guide takes you from the code sitting on your Mac to a fully live, automated SMS pipeline. Follow every step in order. Do not skip anything.

---

## What You'll Need Before You Start

Accounts you must have (or create):
- **Supabase** — supabase.com (free tier is fine to start)
- **Meta Business Manager** — business.facebook.com (for Lead Ads + CAPI)
- **ClickSend** — clicksend.com (you need to top up credit and buy a dedicated number)
- **Calendly** — calendly.com (you already have this)
- **Stripe** — stripe.com (you already have this)

Time estimate: 2–3 hours the first time.

---

## Part 1 — Create Your Supabase Project

### 1.1 — Sign Up & Create a Project

1. Go to **supabase.com** and sign in (or create a free account).
2. Click **"New Project"**.
3. Fill in:
   - **Name:** `fluentish`
   - **Database Password:** Choose a strong password. Save it somewhere safe (1Password, Notes, etc.) — you won't see it again.
   - **Region:** `West EU (Ireland)` — closest to your UK users.
4. Click **"Create new project"**.
5. Wait about 2 minutes for provisioning. You'll see a loading screen.

### 1.2 — Collect Your Project Credentials

Once the project is ready:

1. In the left sidebar, click **"Project Settings"** (the gear icon at the bottom).
2. Click **"API"** in the settings menu.
3. Copy and save these two values somewhere:
   - **Project URL** — looks like `https://abcdefghijklmnop.supabase.co`
   - **Project Ref** — the `abcdefghijklmnop` part of the URL (also shown as "Reference ID")
   - **service_role key** — under "Project API keys", click the eye icon to reveal it. This is a long JWT string starting with `eyJ...`. Copy the whole thing.

   > **Warning:** The service_role key has full database access. Never put it in frontend code or commit it to GitHub.

---

## Part 2 — Enable Required Database Extensions

Before running any migrations, you must manually enable two PostgreSQL extensions in the Supabase dashboard.

1. In the left sidebar, click **"Database"**.
2. Click **"Extensions"**.
3. Search for **`pg_cron`** and toggle it ON.
4. Search for **`pg_net`** and toggle it ON.

Wait a few seconds for each to activate. You'll see a green indicator when they're enabled.

---

## Part 3 — Update Migration 003 With Your Project URL

Migration 003 contains your Supabase project URL hardcoded into the pg_cron schedule. You need to put the real URL in before pushing.

1. Open the file:
   ```
   supabase/migrations/003_cron_jobs.sql
   ```

2. Find this line (it appears twice):
   ```sql
   url := current_setting('app.supabase_url') || '/functions/v1/process-drip-queue',
   ```
   and
   ```sql
   url := current_setting('app.supabase_url') || '/functions/v1/refresh-bank-holidays',
   ```

3. Replace both with your actual project URL. Example (use YOUR URL, not this one):
   ```sql
   url := 'https://abcdefghijklmnop.supabase.co/functions/v1/process-drip-queue',
   ```
   ```sql
   url := 'https://abcdefghijklmnop.supabase.co/functions/v1/refresh-bank-holidays',
   ```

4. Save the file.

---

## Part 4 — Link Your Local Project to Supabase

Open a terminal in the project folder:

```bash
cd /Users/danblumenau/Dropbox/fluentish
```

Log in to Supabase (only needed once):
```bash
supabase login
```
This opens a browser window. Authorise it.

Link your local folder to your online project (replace with your actual project ref):
```bash
supabase link --project-ref abcdefghijklmnop
```

When prompted for the database password, enter the one you saved in Step 1.1.

Verify it worked:
```bash
supabase status
```
You should see your project URL listed.

---

## Part 5 — Push the Database Migrations

This creates all 6 tables, the SQL functions, the seed data, and the pg_cron jobs in your online database.

```bash
supabase db push
```

You'll see output listing each migration file as it runs. If you see any errors, read Part 10 (Troubleshooting) at the bottom.

### Verify the migrations worked

1. Go to your Supabase dashboard.
2. Click **"Table Editor"** in the left sidebar.
3. You should see these 6 tables:
   - `bank_holidays`
   - `drip_schedule`
   - `leads`
   - `sms_log`
   - `sms_templates`
   - `working_hours_config`
4. Click `sms_templates` — you should see 5 rows (sms_1_standard, sms_1_after_hours, sms_2, sms_3, dead_lead_signal).
5. Click `working_hours_config` — you should see 7 rows (one per day of week).
6. Click `bank_holidays` — you should see 16 rows (2025 and 2026 UK bank holidays).

---

## Part 6 — Generate the CRON_AUTH_TOKEN

This is a secret random token that pg_cron uses to authenticate its calls to your Edge Functions. You need to generate it now, before setting secrets.

In your terminal:
```bash
openssl rand -hex 32
```

Copy the output. It looks like: `a3f2c1d8e9b7...` (64 hex characters). Save it somewhere — you'll need it in the next step.

---

## Part 7 — Set All Secrets

Secrets are environment variables injected into your Edge Functions at runtime. They are stored encrypted in Supabase Vault.

You'll set them via the CLI. Run each command below, replacing the placeholder values with your real values. The real values come from each external service — instructions for obtaining each one follow in Parts 8–12.

```bash
supabase secrets set META_APP_SECRET="your-meta-app-secret"
supabase secrets set META_PAGE_ACCESS_TOKEN="your-page-access-token"
supabase secrets set META_PIXEL_ID="your-pixel-id"
supabase secrets set META_VERIFY_TOKEN="any-random-string-you-choose"
supabase secrets set CLICKSEND_API_USERNAME="your-clicksend-email"
supabase secrets set CLICKSEND_API_KEY="your-clicksend-api-key"
supabase secrets set CLICKSEND_FROM_NUMBER="+447700xxxxxx"
supabase secrets set CLICKSEND_INBOUND_TOKEN="another-random-string-you-choose"
supabase secrets set CALENDLY_SIGNING_KEY="your-calendly-signing-key"
supabase secrets set STRIPE_WEBHOOK_SECRET="whsec_xxxxxx"
supabase secrets set CRON_AUTH_TOKEN="the-token-you-generated-in-part-6"
supabase secrets set CALENDLY_LINK="https://calendly.com/fluentish/free-15-minute-chat"
```

> **About META_VERIFY_TOKEN and CLICKSEND_INBOUND_TOKEN:**
> These are values YOU invent. They're passwords that only you know. Use the same `openssl rand -hex 32` command to generate them. You'll paste them into the Meta and ClickSend dashboards later when registering your webhooks.

Verify secrets are set:
```bash
supabase secrets list
```
You should see all 12 secret names listed (values are hidden).

---

## Part 8 — Deploy Edge Functions

```bash
supabase functions deploy
```

This deploys all 6 functions at once. Each will get a public HTTPS URL.

Your function URLs will follow this pattern:
```
https://abcdefghijklmnop.supabase.co/functions/v1/meta-lead-webhook
https://abcdefghijklmnop.supabase.co/functions/v1/process-drip-queue
https://abcdefghijklmnop.supabase.co/functions/v1/calendly-webhook
https://abcdefghijklmnop.supabase.co/functions/v1/stripe-webhook
https://abcdefghijklmnop.supabase.co/functions/v1/clicksend-inbound/CLICKSEND_INBOUND_TOKEN
https://abcdefghijklmnop.supabase.co/functions/v1/refresh-bank-holidays
```

> **Note on the ClickSend inbound URL:** Replace `CLICKSEND_INBOUND_TOKEN` with the actual token string you generated and set as `CLICKSEND_INBOUND_TOKEN` in your secrets. For example: `https://abcdefghijklmnop.supabase.co/functions/v1/clicksend-inbound/a3f2c1d8e9b7...`

Verify deployment in the dashboard:
1. Click **"Edge Functions"** in the left sidebar.
2. You should see all 6 functions listed with a green "Active" status.

---

## Part 9 — Configure External Services

Now you need to go into each service and point their webhooks at your new Edge Function URLs, and collect any API keys/secrets you haven't gathered yet.

---

### 9A — Meta (Facebook): Lead Ads Setup

You need three things from Meta: App Secret, Page Access Token, and Pixel ID. You also need to register your webhook URL.

#### Get Your Meta App Secret

1. Go to **business.facebook.com** and log in.
2. In the top menu, click **"All Tools"** → **"Meta for Developers"** (or go to developers.facebook.com).
3. Click **"My Apps"** and open your app (or create one if you haven't: click "Create App" → "Business" type).
4. In the left sidebar, click **"Settings"** → **"Basic"**.
5. Find **"App Secret"** and click "Show". Copy it. → This is your `META_APP_SECRET`.

#### Get Your Page Access Token

1. In the left sidebar, go to **"Tools"** → **"Graph API Explorer"**.
2. In the top-right, select your App from the dropdown.
3. Click **"Generate Access Token"** → select your Facebook Page.
4. Grant the permissions requested (especially `pages_manage_metadata`, `leads_retrieval`).
5. Copy the token. → This is your `META_PAGE_ACCESS_TOKEN`.

   > **Important:** Standard tokens expire. For production, generate a **long-lived page access token**. In the Graph API Explorer, click the information icon (ℹ) next to your token and follow the "Extend Token" link. Long-lived tokens last ~60 days. For a permanent token, you need a System User token via Business Manager → Settings → Users → System Users.

#### Get Your Pixel ID

1. Go to **business.facebook.com** → **"Events Manager"**.
2. Click your Pixel (or create one if you don't have one yet).
3. Your Pixel ID is the number shown at the top (e.g., `1234567890123456`). → This is your `META_PIXEL_ID`.

#### Register the Lead Ads Webhook

1. Go to **developers.facebook.com** → your App → left sidebar → **"Webhooks"**.
2. Click **"Subscribe to this object"** → choose **"Page"**.
3. Fill in:
   - **Callback URL:** `https://abcdefghijklmnop.supabase.co/functions/v1/meta-lead-webhook`
   - **Verify Token:** The string you set as `META_VERIFY_TOKEN` in your secrets.
4. Click **"Verify and Save"**. Meta will send a GET request to your Edge Function with `hub.challenge`. The function will echo it back. You should see a green tick.
5. In the subscription fields list, find **"leadgen"** and tick it.
6. Now go to your **Facebook Page** (not the app) → **"Settings"** → **"Subscribed Apps"** → ensure your app is subscribed.

---

### 9B — ClickSend: SMS Setup

#### Get Your ClickSend Credentials

1. Go to **clicksend.com** and log in (or create an account).
2. In the top-right, click your name → **"Account Settings"**.
3. You'll see your **Username** (your email address) → `CLICKSEND_API_USERNAME`.
4. Click **"API Credentials"** → copy your **API Key** → `CLICKSEND_API_KEY`.

#### Buy a Dedicated Inbound-Capable Number

> This is mandatory for the kill switch to work. Shared sender IDs (e.g. "FluentISH") cannot receive replies.

1. In ClickSend dashboard, go to **"Numbers"** → **"Buy a Number"**.
2. Select **"United Kingdom"** as the country.
3. Choose any available long number (starts with +44).
4. Click **"Buy"** (approximately £1–2/month).
5. Your new number is now listed under "Numbers". Copy it in full E.164 format (e.g. `+447700123456`) → `CLICKSEND_FROM_NUMBER`.

#### Set Up Inbound SMS Routing

1. In ClickSend, go to **"Numbers"** → click your new number → **"Manage"**.
2. Under "Inbound SMS", set the delivery type to **"URL"**.
3. Paste your inbound webhook URL:
   ```
   https://abcdefghijklmnop.supabase.co/functions/v1/clicksend-inbound/YOUR_CLICKSEND_INBOUND_TOKEN
   ```
   (Replace `YOUR_CLICKSEND_INBOUND_TOKEN` with the actual token string.)
4. Save.

#### Update the `CLICKSEND_FROM_NUMBER` Secret

If you didn't have this when you ran the secrets commands earlier:
```bash
supabase secrets set CLICKSEND_FROM_NUMBER="+447700123456"
```

---

### 9C — Calendly: Booking Webhook

#### Add Phone Number Question to Your Event Type

> Without this, the system cannot match a Calendly booking back to a lead.

1. Go to **calendly.com** and log in.
2. Click **"Event Types"** → click the pencil icon on **"Free 15 Minute Chat"** (or whatever your discovery call event is called).
3. Click through to **"Questions"** → **"+ Add New Question"**.
4. Set:
   - **Type:** Phone
   - **Label:** "Your phone number"
   - **Required:** YES (toggle on)
5. Save.

#### Get Your Calendly Signing Key

1. In Calendly, go to **"Integrations"** in the left sidebar.
2. Click **"Webhooks"** → **"Create Webhook Subscription"**.
3. Fill in:
   - **Webhook URL:** `https://abcdefghijklmnop.supabase.co/functions/v1/calendly-webhook`
   - **Events:** tick **"invitee.created"** only
   - **Scope:** Organisation (or User — either works for a solo account)
4. Click **"Create Webhook Subscription"**.
5. After saving, click on the webhook you just created to view its details.
6. Copy the **"Signing Key"** shown → `CALENDLY_SIGNING_KEY`.

Update the secret:
```bash
supabase secrets set CALENDLY_SIGNING_KEY="your-signing-key-here"
```

---

### 9D — Stripe: Payment Webhook

#### Create the Stripe Webhook

1. Go to **dashboard.stripe.com** and log in.
2. In the left sidebar, go to **"Developers"** → **"Webhooks"**.
3. Click **"+ Add endpoint"**.
4. Fill in:
   - **Endpoint URL:** `https://abcdefghijklmnop.supabase.co/functions/v1/stripe-webhook`
   - **Events to send:** Click "Select events" → search for and select **`checkout.session.completed`**.
5. Click **"Add endpoint"**.
6. After saving, click on the webhook endpoint you just created.
7. Under **"Signing secret"**, click **"Reveal"** → copy the value (starts with `whsec_`) → `STRIPE_WEBHOOK_SECRET`.

Update the secret:
```bash
supabase secrets set STRIPE_WEBHOOK_SECRET="whsec_xxxxxxxx"
```

> **Note on Stripe phone numbers:** Stripe collects phone numbers at checkout only if you enable it. Go to **Settings** → **Checkout** → toggle on "Phone number collection". If you're using Stripe Payment Links, edit the link settings to collect phone. Without a phone, the system falls back to matching by email.

---

## Part 10 — Verify the pg_cron Schedule

The cron job was created when you ran `supabase db push`. Confirm it's registered:

1. In your Supabase dashboard, click **"Database"** → **"SQL Editor"**.
2. Run this query:
   ```sql
   SELECT jobid, jobname, schedule, active FROM cron.job;
   ```
3. You should see `process-drip-queue` with schedule `*/5 * * * *` and `active = true`.
4. Also verify `refresh-bank-holidays` is listed with schedule `0 9 1 11 *`.

If the jobs are missing, run this in the SQL Editor:
```sql
SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 5;
```
This shows the execution history and any errors.

---

## Part 11 — Re-deploy Functions With Final Secrets

Now that all secrets are set, redeploy the functions so they pick up all values:

```bash
supabase functions deploy
```

---

## Part 12 — End-to-End Testing

Test each component of the system in this order.

### Test 1: SMS Templates (Quick Sanity Check)

In the Supabase SQL Editor:
```sql
SELECT key, LEFT(body, 60) AS body_preview FROM sms_templates ORDER BY key;
```
You should see all 5 template rows. `dead_lead_signal` should have a NULL body.

---

### Test 2: Working Day Calculation

In the SQL Editor:
```sql
-- Test: Monday ingestion → SMS 2 on Wednesday, SMS 3 on Friday
SELECT
  calculate_working_day_timestamp('2025-06-02', 2, '10:00:00', 'Europe/London') AS sms2_time,
  calculate_working_day_timestamp('2025-06-02', 4, '10:00:00', 'Europe/London') AS sms3_time;
```
Expected results (2025-06-02 is a Monday, BST so UTC is -1h):
- `sms2_time` = `2025-06-04 09:00:00+00` (Wednesday 10am BST = 9am UTC)
- `sms3_time` = `2025-06-06 09:00:00+00` (Friday 10am BST = 9am UTC)

---

### Test 3: Working Hours Check

```sql
-- Test in-hours (Monday 10am London time → should be TRUE)
SELECT is_working_hours('2025-06-02 10:00:00+01'::timestamptz);

-- Test out-of-hours (Sunday → should be FALSE)
SELECT is_working_hours('2025-06-01 10:00:00+01'::timestamptz);
```

---

### Test 4: Meta Webhook — Test Lead

Meta provides a tool to send test leads without needing a live ad.

1. Go to **developers.facebook.com** → your App → **"Lead Ads Testing Tool"** (search for it in the left sidebar tools, or go to developers.facebook.com/tools/lead-ads-testing).
2. Select your Page and your Lead Form.
3. Click **"Create lead"** and fill in test data (use a real mobile number you control).
4. Click **"Submit"**.

Check the result:
- In Supabase Table Editor → `leads` → you should see a new row.
- In `drip_schedule` → you should see 3 rows for that lead (sms_1_standard or sms_1_after_hours, sms_2, sms_3).
- Check your test phone — you should receive an SMS within 30 seconds.

If no SMS arrives, check Edge Function logs:
1. Supabase dashboard → **"Edge Functions"** → click `meta-lead-webhook` → **"Logs"**.
2. Look for any error messages.

---

### Test 5: Kill Switch — Inbound SMS Reply

Reply "Stop" (or anything) from the test phone number you used in Test 4.

Wait up to 30 seconds, then check:
```sql
SELECT drip_stopped, drip_stopped_reason FROM leads WHERE phone_e164 = '+44XXXXXXXXXX';
```
Should show `drip_stopped = true`, `drip_stopped_reason = 'replied'`.

```sql
SELECT status FROM drip_schedule WHERE lead_id = (
  SELECT id FROM leads WHERE phone_e164 = '+44XXXXXXXXXX'
);
```
All rows should show `status = 'cancelled'`.

---

### Test 6: Force a Drip Message to Fire Immediately

In the SQL Editor, manually wind back a drip entry's scheduled time to make the cron job pick it up:

```sql
-- First, insert a fresh test lead (or use an existing one)
-- Then find the sms_2 row and backdate it:
UPDATE drip_schedule
SET scheduled_for = NOW() - INTERVAL '1 minute'
WHERE lead_id = (SELECT id FROM leads ORDER BY created_at DESC LIMIT 1)
  AND sms_template_key = 'sms_2'
  AND status = 'pending';
```

Wait up to 5 minutes (the cron job interval), then check your phone for SMS 2.

Check the log:
```sql
SELECT * FROM sms_log ORDER BY sent_at DESC LIMIT 5;
```

---

### Test 7: Calendly Booking

1. Open your Calendly booking link and book a test appointment using the same phone number as your test lead.
2. Check Supabase:
```sql
SELECT status, call_booked_at, drip_stopped FROM leads
WHERE phone_e164 = '+44XXXXXXXXXX';
```
Should show `status = 'call_booked'`, `drip_stopped = true`.

Check Meta Events Manager to confirm a `Schedule` event appeared (it can take a few hours to show in the UI, but the API call happens immediately).

---

### Test 8: Stripe Payment (Test Mode)

1. Make sure Stripe is in **Test Mode** (toggle in the top-left of the Stripe dashboard).
2. Go to your Stripe dashboard → **"Payment Links"** → create a test payment link for £40.
3. Complete a test purchase using Stripe's test card: `4242 4242 4242 4242`, any future expiry, any CVC.
4. Check Supabase:
```sql
SELECT status, paid_at FROM leads WHERE email = 'your-test-email@example.com';
```
Should show `status = 'paid'`.

---

## Part 13 — Go-Live Checklist

Before switching on real Meta ads, run through this checklist:

- [ ] Received a real SMS on a real phone during testing
- [ ] Kill switch cancelled drip rows when you replied
- [ ] Calendly booking correctly set `status = 'call_booked'`
- [ ] Stripe payment correctly set `status = 'paid'`
- [ ] Meta Events Manager shows test events (Lead, Schedule, Purchase)
- [ ] Edge Function logs show no persistent errors
- [ ] `cron.job` shows both jobs as `active = true`
- [ ] ClickSend account has sufficient credit topped up
- [ ] Calendly event has "Phone number" as a required question
- [ ] Your SMS template copy has been reviewed and you're happy with it (edit via Table Editor → `sms_templates`)
- [ ] Stripe is switched from Test Mode to Live Mode (regenerate the webhook and update `STRIPE_WEBHOOK_SECRET`)

---

## Part 14 — Ongoing Maintenance

### Updating SMS Template Copy

No code changes needed. Edit directly in Supabase:
1. Dashboard → **Table Editor** → `sms_templates`
2. Click the cell you want to edit → type your new copy → click the tick.

### Changing Working Hours

No code changes needed:
1. Dashboard → **Table Editor** → `working_hours_config`
2. Edit `open_time`, `close_time`, or toggle `is_working_day`.

### Adding Bank Holidays Manually

1. Dashboard → **Table Editor** → `bank_holidays` → **"Insert Row"**.
2. Fill in `holiday_date` (YYYY-MM-DD format), `name`, leave `region` as `england-wales`.

The `refresh-bank-holidays` function runs automatically each 1st November and populates the next two years from the GOV.UK API.

### Monitoring

Check drip queue health weekly:
```sql
-- See count of pending, sent, failed, cancelled messages
SELECT status, COUNT(*) FROM drip_schedule GROUP BY status;

-- See recent cron job execution history
SELECT jobname, start_time, end_time, status, return_message
FROM cron.job_run_details
ORDER BY start_time DESC
LIMIT 20;
```

If you see many `failed` rows in `drip_schedule`, check Edge Function logs for ClickSend API errors (most likely: insufficient credit on your ClickSend account).

---

## Troubleshooting

### `supabase db push` fails with "extension not found"

You didn't enable pg_cron or pg_net in the dashboard. Go back to Part 2.

### `supabase db push` fails with "permission denied"

You used the wrong password when linking. Re-run:
```bash
supabase link --project-ref abcdefghijklmnop
```
and enter the database password from Step 1.1.

### Meta webhook verification fails (no green tick)

- Check that your `META_VERIFY_TOKEN` secret matches exactly what you typed in the Meta webhook form.
- Check Edge Function logs: Dashboard → Edge Functions → `meta-lead-webhook` → Logs.
- The function must be deployed and running. Run `supabase functions deploy` again if in doubt.

### SMS not arriving

1. Check `drip_schedule` — is the row `status = 'sent'` or `status = 'failed'`?
2. If `failed`, check `error_detail` column.
3. Check Edge Function logs for ClickSend errors.
4. Verify ClickSend account has credit (top up if needed).
5. Verify `CLICKSEND_FROM_NUMBER` is the exact E.164 format number you bought (e.g. `+447700123456`).

### Drip queue not firing

1. Check `cron.job` — is the job active?
2. Check `cron.job_run_details` — are there error messages?
3. Verify the URL in `003_cron_jobs.sql` matches your actual project URL exactly.
4. Re-run migration 003 manually in the SQL Editor if needed.

### Calendly booking not matching a lead

The booking phone number doesn't match the lead's phone. Common causes:
- Phone question not set as required in Calendly (user skipped it).
- User entered phone in a different format that normalisation couldn't handle.
Check `leads` table for the email address instead — you may need to update the lead manually.

### "Unauthorized" errors in Edge Function logs

A webhook is calling a function with the wrong authentication. Double-check:
- Meta: `META_APP_SECRET` is correct.
- Calendly: `CALENDLY_SIGNING_KEY` is copied from the right webhook subscription.
- Stripe: `STRIPE_WEBHOOK_SECRET` starts with `whsec_` and is from the correct endpoint (test vs live mode).
- ClickSend inbound: The full URL including the token suffix is set correctly in ClickSend.
