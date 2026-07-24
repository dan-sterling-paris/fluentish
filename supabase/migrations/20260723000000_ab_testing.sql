-- ════════════════════════════════════════════════════════════════════════════
-- A/B Testing for free-chat.html
-- ════════════════════════════════════════════════════════════════════════════

-- Append-only events table: pageviews, cta_clicks, and bookings per visitor
create table public.ab_events (
  id          bigserial     primary key,
  visitor_id  text          not null,
  variant     text          not null check (variant in ('A', 'B')),
  event_type  text          not null check (event_type in ('pageview', 'cta_click', 'booking')),
  metadata    jsonb,
  created_at  timestamptz   not null default now()
);

create index idx_ab_events_variant_type on public.ab_events (variant, event_type);
create index idx_ab_events_visitor on public.ab_events (visitor_id, event_type);

alter table public.ab_events enable row level security;

-- Anon can INSERT (landing page uses anon key, no auth)
create policy "anon_insert_ab_events"
  on public.ab_events for insert
  with check (true);

-- Anon can SELECT (needed for weight-fetching RPC; data is non-PII)
create policy "anon_select_ab_events"
  on public.ab_events for select
  using (true);


-- ── RPC: compute current variant weights ─────────────────────────────────
create or replace function public.ab_weights()
returns jsonb
language plpgsql
security definer
stable
as $$
declare
  v_total     int;
  v_a_views   int;
  v_b_views   int;
  v_a_books   int;
  v_b_books   int;
  v_a_rate    numeric;
  v_b_rate    numeric;
  v_phase     text;
  v_weight_a  numeric;
  v_weight_b  numeric;
begin
  select count(distinct visitor_id) into v_a_views
    from public.ab_events where variant = 'A' and event_type = 'pageview';
  select count(distinct visitor_id) into v_b_views
    from public.ab_events where variant = 'B' and event_type = 'pageview';

  v_total := coalesce(v_a_views, 0) + coalesce(v_b_views, 0);

  select count(distinct visitor_id) into v_a_books
    from public.ab_events where variant = 'A' and event_type = 'booking';
  select count(distinct visitor_id) into v_b_books
    from public.ab_events where variant = 'B' and event_type = 'booking';

  if v_total < 60 then
    -- Phase 1: warm-up (~2 days at 30/day), 50/50
    v_phase := 'warmup';
    v_weight_a := 0.5;
    v_weight_b := 0.5;
  else
    v_a_rate := case when v_a_views > 0 then v_a_books::numeric / v_a_views else 0 end;
    v_b_rate := case when v_b_views > 0 then v_b_books::numeric / v_b_views else 0 end;

    -- Tiebreaker: if booking rates are equal, use CTA click rate
    if v_a_rate = v_b_rate then
      declare
        v_a_clicks int;
        v_b_clicks int;
      begin
        select count(distinct visitor_id) into v_a_clicks
          from public.ab_events where variant = 'A' and event_type = 'cta_click';
        select count(distinct visitor_id) into v_b_clicks
          from public.ab_events where variant = 'B' and event_type = 'cta_click';
        v_a_rate := case when v_a_views > 0 then v_a_clicks::numeric / v_a_views else 0 end;
        v_b_rate := case when v_b_views > 0 then v_b_clicks::numeric / v_b_views else 0 end;
      end;
    end if;

    if v_total < 120 then
      -- Phase 2: gradual (~days 3-4), 70/30
      v_phase := 'gradual';
      if v_a_rate >= v_b_rate then
        v_weight_a := 0.7; v_weight_b := 0.3;
      else
        v_weight_a := 0.3; v_weight_b := 0.7;
      end if;
    else
      -- Phase 3: optimised (day 5+), 90/10
      v_phase := 'optimised';
      if v_a_rate >= v_b_rate then
        v_weight_a := 0.9; v_weight_b := 0.1;
      else
        v_weight_a := 0.1; v_weight_b := 0.9;
      end if;
    end if;
  end if;

  return jsonb_build_object(
    'weight_a', v_weight_a,
    'weight_b', v_weight_b,
    'total_visitors', v_total,
    'phase', v_phase,
    'a_views', coalesce(v_a_views, 0),
    'b_views', coalesce(v_b_views, 0),
    'a_bookings', coalesce(v_a_books, 0),
    'b_bookings', coalesce(v_b_books, 0)
  );
end;
$$;
