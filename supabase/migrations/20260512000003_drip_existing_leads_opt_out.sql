-- Exclude all existing leads from the automated drip sequence.
-- New leads (created after this migration) will have both columns null
-- and will go through the sequence normally.
update leads
set sms2_sent_at = now(), sms3_sent_at = now()
where sms2_sent_at is null;
