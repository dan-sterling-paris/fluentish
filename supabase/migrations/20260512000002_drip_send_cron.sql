-- Schedule drip-send Edge Function to run every 5 minutes via pg_cron + pg_net
select cron.schedule(
  'drip-send-every-5min',
  '*/5 * * * *',
  $$
  select net.http_post(
    url     := 'https://gutihncfxjdyxulfwtgp.supabase.co/functions/v1/drip-send',
    headers := '{"Content-Type": "application/json"}'::jsonb,
    body    := '{}'::jsonb
  )
  $$
);
