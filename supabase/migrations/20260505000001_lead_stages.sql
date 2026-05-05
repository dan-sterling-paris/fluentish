-- New lead status enum
create type lead_status_new as enum ('new','contacted','interested','call_booked','enrolled','lost');

-- Migrate existing data
alter table leads alter column status drop default;
alter table leads alter column status type lead_status_new
  using case status::text
    when 'new'            then 'new'
    when 'auto_contacted' then 'contacted'
    when 'replied'        then 'interested'
    when 'booked'         then 'call_booked'
    else 'new'
  end::lead_status_new;
alter table leads alter column status set default 'new';

drop type lead_status;
alter type lead_status_new rename to lead_status;

-- Track last message direction for conversation state indicator
alter table leads add column last_message_direction text;

-- Track when SMS 3 was sent (for auto-lost logic)
alter table leads add column sms3_sent_at timestamptz;

-- Trigger: keep last_message_direction up to date on every message insert
create or replace function sync_lead_last_message()
returns trigger as $$
begin
  update leads
  set last_message_direction = new.direction,
      updated_at = now()
  where id = new.lead_id;
  return new;
end;
$$ language plpgsql;

create trigger on_message_insert
after insert on messages
for each row execute function sync_lead_last_message();

-- pg_cron: auto-mark lost 24h after SMS 3 with no reply (runs hourly)
select cron.schedule(
  'auto-lost-after-sms3',
  '0 * * * *',
  $$
  update leads
  set status = 'lost', updated_at = now()
  where sms3_sent_at < now() - interval '24 hours'
    and status not in ('interested', 'call_booked', 'enrolled', 'lost')
  $$
);
