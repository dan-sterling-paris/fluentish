-- Archive conversations after 7 days of no message activity
alter table leads add column if not exists archived_at timestamptz;

-- Auto-unarchive: any new message (in or out) brings a conversation back to life
create or replace function sync_lead_last_message()
returns trigger as $$
begin
  update leads
  set last_message_direction = new.direction,
      last_message_at        = new.sent_at,
      archived_at             = null,
      updated_at              = now()
  where id = new.lead_id;
  return new;
end;
$$ language plpgsql;

-- pg_cron: archive leads inactive for 7+ days (runs daily, off-peak)
select cron.schedule(
  'archive-inactive-leads',
  '0 3 * * *',
  $$
  update leads
  set archived_at = now()
  where archived_at is null
    and coalesce(last_message_at, created_at) < now() - interval '7 days'
  $$
);
