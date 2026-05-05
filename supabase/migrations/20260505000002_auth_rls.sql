-- Require authentication for Realtime subscriptions
-- (crm-api uses service role key and is protected by verify_jwt in config.toml)
drop policy if exists "anon can read leads"    on leads;
drop policy if exists "anon can read messages" on messages;
drop policy if exists "anon can read templates" on templates;

create policy "auth can read leads"     on leads     for select using (auth.role() = 'authenticated');
create policy "auth can read messages"  on messages  for select using (auth.role() = 'authenticated');
create policy "auth can read templates" on templates for select using (auth.role() = 'authenticated');
