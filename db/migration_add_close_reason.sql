-- Migration: add close_reason / close_price columns to public.trades
--
-- Why: db/writer.py (write_trade) and agents/reporter.py (_sync_closed_trades)
-- both write `close_reason` (and writer also `close_price`), but these columns
-- do not exist in the live schema. PostgREST rejects the whole upsert/update
-- with PGRST204 ("Could not find the 'close_reason' column"), so any close that
-- sets a reason (MOMENTUM_EXIT / ZONE_BREAK / CONFLICT_CLOSE / RECONCILED…)
-- silently fails to persist. Adding the columns fixes that and lets
-- reconcile_open_trades() tag RECONCILED / RECONCILED_STALE.
--
-- Apply: Supabase dashboard → SQL editor → run this. Idempotent.

alter table public.trades
    add column if not exists close_reason text,
    add column if not exists close_price double precision;
