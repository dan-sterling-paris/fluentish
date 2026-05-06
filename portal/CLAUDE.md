# Portal

Student-facing portal for FluentISH, hosted as a static file in Supabase Storage.

## What it is

A single-page app (`index.html`) that enrolled students use to view their profile, lesson schedule, and shared resources. No build step — CDN-only (Supabase JS, Alpine.js, Tailwind).

## Auth model

- Students are invited via Supabase Auth "Invite User" flow (never self-signup)
- CRM admins are created via "Create User" (never invite) — this distinction drives the trigger below
- On first click of an invite link, the student sets a password via the portal's password-set form
- Returning students use email + password

## Database tables (to be created via migration)

| Table | Purpose |
|-------|---------|
| `customer_profiles` | One row per student (id = auth.users.id). Stores name, email, phone, level, tutor notes. |
| `lessons` | One row per lesson. Linked to a customer. Fields: topic, scheduled_at, duration_mins, notes, status (scheduled/completed/cancelled). |
| `resources` | Links/PDFs. `customer_id = null` → visible to all students; non-null → private to that student. |

## RLS model

- `customer_profiles` — student can select their own row only
- `lessons` — student can select their own lessons only
- `resources` — student can select global rows (customer_id IS NULL) and their own
- `leads`, `messages`, `templates` (CRM tables) — blocked for students via `is_customer()` helper function

## Key invariant

CRM admins must **never** be invited via the "Invite User" flow. Invited users automatically get a `customer_profiles` row (via trigger on `auth.users`), which would block them from the CRM. Always use "Create User" for CRM admins.

## Deployment

1. Apply migration `20260506000000_customer_portal.sql` via Supabase Studio SQL Editor
2. Create a public Storage bucket named `portal`
3. Upload `index.html` to the `portal` bucket
4. Add the Storage URL to Auth > URL Configuration > Redirect URLs in Supabase Dashboard
5. Invite students via Dashboard > Auth > Users > Invite User
6. Manage lesson/resource data directly in Supabase Studio Table Editor

## Portal URL

```
https://<project-ref>.supabase.co/storage/v1/object/public/portal/index.html
```
