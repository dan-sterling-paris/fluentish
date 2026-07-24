-- Add surname, phone and age-consent fields to booking_requests.
-- Also add reminder_sent flag for the 1-hour-before reminder email.

alter table public.booking_requests
  add column surname      text,
  add column phone        text,
  add column age_consent  boolean not null default false,
  add column reminder_sent boolean not null default false;
