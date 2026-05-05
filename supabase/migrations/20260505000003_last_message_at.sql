-- Track the timestamp of the last message so the frontend can show
-- "Follow up" when a lead has replied but no response in >24 hours.
alter table leads add column if not exists last_message_at timestamptz;

-- Backfill from existing messages
update leads l
set last_message_at = m.last_at
from (
  select lead_id, max(sent_at) as last_at
  from messages
  group by lead_id
) m
where l.id = m.lead_id;

-- Update trigger to also set last_message_at
create or replace function sync_lead_last_message()
returns trigger as $$
begin
  update leads
  set last_message_direction = new.direction,
      last_message_at        = new.sent_at,
      updated_at             = now()
  where id = new.lead_id;
  return new;
end;
$$ language plpgsql;
