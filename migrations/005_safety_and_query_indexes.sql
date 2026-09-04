create unique index if not exists email_logs_one_active_initial
    on email_logs (lead_id, email_type)
    where status in ('pending', 'sent') and email_type = 'initial';

create index if not exists email_logs_provider_message_id_idx
    on email_logs (provider_message_id);

create index if not exists events_lead_id_created_at_idx
    on events (lead_id, created_at);

create index if not exists agent_actions_lead_id_idx
    on agent_actions (lead_id);
