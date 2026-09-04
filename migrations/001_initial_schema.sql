create extension if not exists "pgcrypto";

create table if not exists leads (
    id uuid primary key default gen_random_uuid(),

    name text,
    title text,
    company text,
    domain text,

    email text,
    email_confidence numeric(5,2),

    source_url text,

    score integer check (score between 0 and 100),
    score_reason text,

    status text not null default 'new'
        check (
            status in (
                'new',
                'enriched',
                'scored',
                'contacted',
                'engaged',
                'unsubscribed',
                'dead'
            )
        ),

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


create table if not exists email_logs (
    id uuid primary key default gen_random_uuid(),

    lead_id uuid not null
        references leads(id)
        on delete cascade,

    email_type text not null,

    subject text,
    body text,

    provider text,
    provider_message_id text,

    status text not null default 'pending',

    sent_at timestamptz,
    created_at timestamptz not null default now()
);


create table if not exists events (
    id uuid primary key default gen_random_uuid(),

    lead_id uuid not null
        references leads(id)
        on delete cascade,

    email_log_id uuid
        references email_logs(id)
        on delete set null,

    event_type text not null,

    metadata jsonb not null default '{}'::jsonb,

    ip_address text,
    user_agent text,

    is_suspected_scanner boolean not null default false,

    created_at timestamptz not null default now()
);


create table if not exists agent_actions (
    id uuid primary key default gen_random_uuid(),

    lead_id uuid not null
        references leads(id)
        on delete cascade,

    trigger_type text not null,
    action_type text not null,

    reason text,

    status text not null default 'completed',

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now()
);
