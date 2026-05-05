create type lead_status as enum ('new', 'auto_contacted', 'replied', 'booked');

create table leads (
  id         bigserial primary key,
  name       text not null,
  phone      text not null unique,
  status     lead_status not null default 'new',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table messages (
  id        bigserial primary key,
  lead_id   bigint not null references leads(id) on delete cascade,
  direction text not null check (direction in ('inbound', 'outbound')),
  body      text not null,
  sent_at   timestamptz not null default now()
);

-- Publish changes so Supabase Realtime can broadcast them to the dashboard
alter publication supabase_realtime add table leads;
alter publication supabase_realtime add table messages;

-- RLS: Edge Functions use the service role key (bypasses RLS).
-- The dashboard uses the anon key only for Realtime subscriptions, so it needs SELECT.
alter table leads enable row level security;
alter table messages enable row level security;

create policy "anon can read leads"    on leads    for select using (true);
create policy "anon can read messages" on messages for select using (true);
