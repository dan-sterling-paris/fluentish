-- ════════════════════════════════════════════════════════════════════════════
-- Customer Portal — 20260506000000_customer_portal.sql
-- ════════════════════════════════════════════════════════════════════════════

-- ── 1. Helper: identify portal customers ─────────────────────────────────────
-- security definer avoids RLS recursion when called from other tables' policies.
-- Must be created before customer_profiles so the tightened CRM policies can
-- reference it (even though customer_profiles doesn't exist yet, the function
-- body is not validated at CREATE time in PostgreSQL).
create or replace function public.is_customer()
returns boolean
language sql
security definer
stable
as $$
  select exists (select 1 from public.customer_profiles where id = auth.uid())
$$;


-- ── 2. Tighten CRM table RLS ──────────────────────────────────────────────────
-- Existing policies allow any authenticated user. Customers will also be
-- authenticated, so we restrict CRM tables to non-customer authenticated users.
drop policy if exists "auth can read leads"     on leads;
drop policy if exists "auth can read messages"  on messages;
drop policy if exists "auth can read templates" on templates;

create policy "crm admin can read leads"
  on leads for select
  using (auth.role() = 'authenticated' and not is_customer());

create policy "crm admin can read messages"
  on messages for select
  using (auth.role() = 'authenticated' and not is_customer());

create policy "crm admin can read templates"
  on templates for select
  using (auth.role() = 'authenticated' and not is_customer());


-- ── 3. customer_profiles ──────────────────────────────────────────────────────
create table public.customer_profiles (
  id          uuid        primary key references auth.users(id) on delete cascade,
  full_name   text        not null default '',
  email       text        not null default '',
  phone       text,
  level       text,       -- e.g. 'A1', 'B2'
  notes       text,       -- tutor notes visible to the student
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table public.customer_profiles enable row level security;

-- Student can read only their own profile row
create policy "customer can read own profile"
  on customer_profiles for select
  using (auth.uid() = id);


-- ── 4. lessons ────────────────────────────────────────────────────────────────
create type lesson_status as enum ('scheduled', 'completed', 'cancelled');

create table public.lessons (
  id            bigserial   primary key,
  customer_id   uuid        not null references public.customer_profiles(id) on delete cascade,
  topic         text        not null default '',
  scheduled_at  timestamptz not null,
  duration_mins integer     not null default 60,
  notes         text,
  status        lesson_status not null default 'scheduled',
  created_at    timestamptz not null default now()
);

alter table public.lessons enable row level security;

-- Student can read only their own lessons
create policy "customer can read own lessons"
  on lessons for select
  using (auth.uid() = customer_id);


-- ── 5. resources ──────────────────────────────────────────────────────────────
create table public.resources (
  id             bigserial primary key,
  title          text      not null,
  url            text      not null,
  description    text,
  resource_type  text      not null default 'link', -- 'link' | 'pdf' | 'vocabulary'
  customer_id    uuid      references public.customer_profiles(id) on delete set null,
  -- null  = visible to ALL authenticated customers
  -- uuid  = private to that student only
  created_at     timestamptz not null default now()
);

alter table public.resources enable row level security;

-- Student can read global resources (customer_id IS NULL) and their own
create policy "customer can read own and global resources"
  on resources for select
  using (
    auth.role() = 'authenticated'
    and is_customer()
    and (customer_id is null or customer_id = auth.uid())
  );


-- ── 6. Trigger: auto-create profile row when admin invites a student ──────────
-- invited_at is set by Supabase only for the "Invite User" flow.
-- CRM admins must be created via "Create User" (no invited_at) to avoid
-- accidentally getting a customer_profiles row, which would block CRM access.
create or replace function public.handle_new_customer()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.invited_at is not null then
    insert into public.customer_profiles (id, full_name, email)
    values (
      new.id,
      coalesce(new.raw_user_meta_data->>'full_name', ''),
      coalesce(new.email, '')
    )
    on conflict (id) do nothing;
  end if;
  return new;
end;
$$;

create trigger on_auth_user_invited
  after insert on auth.users
  for each row execute function public.handle_new_customer();


-- ── 7. updated_at trigger for customer_profiles ───────────────────────────────
create or replace function public.set_customer_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger customer_profiles_set_updated_at
  before update on public.customer_profiles
  for each row execute function public.set_customer_updated_at();
