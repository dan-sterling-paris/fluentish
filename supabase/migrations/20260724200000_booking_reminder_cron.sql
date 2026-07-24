-- Schedule booking-reminder Edge Function to run every 5 minutes via pg_cron + pg_net.
-- Sends a reminder email 1 hour before confirmed bookings.
select cron.schedule(
  'booking-reminder-every-5min',
  '*/5 * * * *',
  $$
  select net.http_post(
    url     := 'https://gutihncfxjdyxulfwtgp.supabase.co/functions/v1/booking-reminder',
    headers := '{"Content-Type": "application/json"}'::jsonb,
    body    := '{}'::jsonb
  )
  $$
);
