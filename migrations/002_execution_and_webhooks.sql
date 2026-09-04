alter table leads
    add column if not exists classification text,
    add column if not exists score_metadata jsonb not null default '{}'::jsonb,
    add column if not exists email_candidate_score numeric(5,2),
    add column if not exists provider_verification_confidence numeric(5,2);

alter table email_logs
    add column if not exists error_message text;

alter table events
    add column if not exists provider_event_id text,
    add column if not exists provider text;

create unique index if not exists events_provider_event_id_unique
    on events (provider, provider_event_id)
    where provider_event_id is not null;
