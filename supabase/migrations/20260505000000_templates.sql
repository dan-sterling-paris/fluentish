create table templates (
  key  text primary key,
  body text not null
);

insert into templates (key, body) values
  ('sms_1', 'Hi {name}, thanks for your interest in French lessons! Are you looking for in-person or online classes?'),
  ('sms_2', 'Hi {name}, just checking in — have you had a chance to think about your French learning goals?'),
  ('sms_3', 'Hi {name}, I have some availability this week if you''d like to book a free 15-minute discovery call!');

-- Anon key can read templates (for dashboard config endpoint)
alter table templates enable row level security;
create policy "anon can read templates" on templates for select using (true);
