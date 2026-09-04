create unique index if not exists email_logs_one_active_followup
    on email_logs (lead_id, email_type)
    where status in ('pending', 'sent')
      and email_type in ('no_open_followup', 'contextual_followup');
