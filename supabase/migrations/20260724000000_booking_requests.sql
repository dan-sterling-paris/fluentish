-- Booking requests from the free-chat landing page custom form.
-- Replaces Calendly inline widget with a lightweight slot picker
-- backed by Google Calendar availability.

create table public.booking_requests (
  id                bigserial   primary key,
  name              text        not null,
  email             text        not null,
  slot_start        timestamptz not null,
  variant           text        not null check (variant in ('A', 'B')),
  status            text        not null default 'confirmed'
                                check (status in ('confirmed', 'cancelled')),
  calendar_event_id text,
  created_at        timestamptz not null default now()
);

create index idx_booking_requests_status on public.booking_requests (status);

alter table public.booking_requests enable row level security;
-- No anon policies: edge function uses service role key (bypasses RLS).
