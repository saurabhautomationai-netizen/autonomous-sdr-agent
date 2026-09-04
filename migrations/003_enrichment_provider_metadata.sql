alter table leads
    add column if not exists email_provider_source text,
    add column if not exists email_verification_status text,
    add column if not exists enrichment_metadata jsonb not null default '{}'::jsonb;
