ALTER TABLE leads ADD COLUMN IF NOT EXISTS reply_dismissed_at timestamptz;
