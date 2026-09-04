# Autonomous SDR Agent

A practical-assessment FastAPI service that extracts, enriches, scores, contacts,
and reacts to lead behavior while keeping deterministic rules and safety gates in
control. PostgreSQL/Supabase is the system of record; OpenAI assists only where
contextual generation or scoring adds value, and Resend is the email transport.

The objective is to demonstrate an auditable autonomous SDR loop: acquire a lead,
enrich and rank a recipient deterministically, score fit, decide outreach, record
the send lifecycle, evaluate behavior, and take a safe next action.

## Architecture and execution flow

```text
                         +-------------------------+
Lead URL / API request ->| FastAPI routes          |
                         +------------+------------+
                                      |
           +--------------------------+--------------------------+
           v                          v                          v
  extraction/enrichment       hybrid scoring             event ingestion
  Hunter -> Apollo ->          rules (90) + LLM (10)      webhook/simulation
  local deterministic rank            |                          |
           +--------------------------+--------------------------+
                                      v
                         deterministic decision engine
                                      |
                     +----------------+----------------+
                     v                                 v
              initial outreach                 behavior orchestrator
                     |                          Scenarios A / B / C
                     +----------------+----------------+
                                      v
                         centralized outbound gates
                         pending -> sent | failed
                                      |
                                      v
                    PostgreSQL: leads, email_logs, events,
                              agent_actions

Separate worker -> persisted sent_at query -> Scenario A evaluation
```

1. `app/main.py` exposes extraction, enrichment, scoring, simulated event,
   behavior-execution, and Resend webhook endpoints.
2. Services contain deterministic extraction/ranking/scoring, bounded LLM calls,
   behavioral decisions, scanner filtering, and outbound orchestration.
3. Repositories contain SQL persistence for `leads`, `email_logs`, `events`, and
   `agent_actions`.
4. A qualified lead is enriched and scored. Outreach decisions are deterministic.
5. Behavioral events are summarized using only valid opens. Scenario A sends a
   fresh-angle follow-up after the configured no-open delay. Scenario B sends a
   contextual follow-up after a click or two valid opens. Scenario C unsubscribes
   and halts outreach.
6. Every automated send creates one `pending` email log. The same row becomes
   `sent` with its Resend ID and timestamp, or `failed` with a sanitized error.
   Status is re-read immediately before transport; `unsubscribed` and `dead` are
   hard stops and blocked attempts are recorded.
7. Enrichment and score persistence preserve terminal `unsubscribed`/`dead`
   statuses at the SQL update level, preventing lifecycle regression.

## Folder structure

```text
app/
  main.py                 FastAPI routes
  config.py               environment-backed configuration
  database.py             SQLAlchemy engine/session
  repositories/           database access
  services/               extraction, enrichment, scoring, behavior and email
migrations/               ordered PostgreSQL migrations
scripts/                  manual assessment/demo scripts
tests/                    mocked unit tests and HTML fixtures
Dockerfile                Linux API/worker image
docker-compose.yml        API and worker process definitions
```

## Setup

Use Python 3.11+ and create a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Configure `.env` (never commit it):

- `DATABASE_URL`: Supabase/PostgreSQL connection URL.
- `OPENAI_API_KEY`: extraction fallback, hybrid scoring, and email generation.
- `OPENAI_MODEL`: model used consistently for extraction, scoring, and generation;
  defaults to the previously verified `gpt-5-mini`.
- `RESEND_API_KEY`: Resend transport key.
- `RESEND_WEBHOOK_SECRET`: endpoint-specific `whsec_...` signing secret.
- `RESEND_TEST_MODE`: explicit delivery override; defaults to `false`.
- `RESEND_TEST_RECIPIENT`: allowed Resend test address used only when test mode is true.
- `HUNTER_API_KEY`: Hunter Email Finder key; the primary enrichment provider.
- `APOLLO_API_KEY`: Apollo People Enrichment key; queried after a Hunter miss/error.
- `ENRICHMENT_PROVIDER_TIMEOUT_SECONDS`: per-provider HTTP timeout; default 8 seconds.
- `NO_OPEN_THRESHOLD_SECONDS`: 60 for the assessment; use hours/days in production.
- `SCANNER_OPEN_BURST_COUNT`: default 20.
- `SCANNER_OPEN_BURST_WINDOW_SECONDS`: default 5.
- `SCHEDULER_POLL_INTERVAL_SECONDS`: worker polling interval; default 10 seconds.

Apply migrations in order with the Supabase SQL editor or `psql`:

```powershell
psql $env:DATABASE_URL -f migrations/001_initial_schema.sql
psql $env:DATABASE_URL -f migrations/002_execution_and_webhooks.sql
psql $env:DATABASE_URL -f migrations/003_enrichment_provider_metadata.sql
psql $env:DATABASE_URL -f migrations/004_scheduler_duplicate_protection.sql
psql $env:DATABASE_URL -f migrations/005_safety_and_query_indexes.sql
```

Start the API:

```powershell
uvicorn app.main:app --reload
```

Open Swagger UI at `http://127.0.0.1:8000/docs` (or ReDoc at
`http://127.0.0.1:8000/redoc`). The health endpoint is
`http://127.0.0.1:8000/health`.

Start the Scenario A worker in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

The worker polls for sent initial emails older than
`NO_OPEN_THRESHOLD_SECONDS` with no valid open, click, reply, unsubscribe, or
existing active no-open follow-up. Each due lead passes through the existing
behavior orchestrator. Shutdown via Ctrl+C/SIGTERM sets an event and exits the
poll loop safely. The database partial unique index permits at most one `pending`
or `sent` follow-up per lead/email type, protecting against overlapping workers.
Failed attempts may be retried on a later poll. The demo defaults are intentionally
short; production should use a substantially longer threshold and polling interval.

## Assessment Verification Status

### Live controlled verification

- **Scenario A:** A qualified synthetic lead received initial outreach through the
  normal application flow. Its database-generated `sent_at` was allowed to age
  naturally beyond the configured threshold and was not manually backdated. With
  no engagement, the worker discovered the lead autonomously, selected
  `send_no_open_followup`, and completed the follow-up with status `sent`.
  `RESEND_TEST_MODE` routed physical delivery exclusively to
  `delivered@resend.dev`. The next scheduler poll reported `due_count=0`,
  demonstrating duplicate protection.
- **Scenario B:** A synthetic click event was persisted, the behavior engine selected
  `send_contextual_followup`, and the contextual follow-up `email_logs` row reached
  `sent` with a populated `provider_message_id`. The Resend test recipient showed
  the message as Delivered.
- **Scenario C:** A negative/unsubscribe reply selected `unsubscribe_lead` and the
  lead persisted as `unsubscribed`. A later request containing stale `contacted`
  state did not override the authoritative database status. Evaluation returned
  `stop_outreach`, `execution` was `null`, and no further email was sent.
- **Docker:** The image built and the container started successfully. `/health`
  returned `{"status":"ok","service":"autonomous-sdr-agent"}`, Docker reported
  the container as healthy, and image inspection confirmed that no application
  secrets were baked into it.

All live email verification used Resend's controlled test recipient only. No real
prospect received email.

### Mocked verification

- The automated suite passed all 65 pytest tests; external provider and transport
  calls are mocked.
- `python -m compileall app tests scripts` passed.
- `git diff --check` passed; Windows LF/CRLF messages were informational only.
- `scripts.demo_end_to_end` exercises the complete synthetic flow with its database,
  OpenAI, Hunter, Apollo, and Resend boundaries mocked.

### Not live verified

Hunter and Apollo adapters were verified with mocked responses only. Live provider
results, credit consumption, subscription-dependent fields, and production match
rates are not claimed.

The documented default may use port 8000. During local assessment verification,
port 8000 was occupied by another local service, so the Autonomous SDR Agent ran
on port 8001. This is an environment-specific difference, not an application
requirement.

## Docker

The image uses Python 3.12 slim, installs the UTF-8 `requirements.txt`, runs as a
non-root user, exposes port 8000, and includes an HTTP healthcheck. It copies only
the application and dependency manifest. `.env`, source-control data, tests, and
local artifacts are excluded from the build context. Secrets remain runtime
environment variables.

Build and run the API against an existing Supabase/PostgreSQL database:

```powershell
docker build -t autonomous-sdr-agent:assessment .
docker run --rm -p 8000:8000 --env-file .env autonomous-sdr-agent:assessment
```

Run the autonomous Scenario A worker from the same image:

```powershell
docker run --rm --env-file .env autonomous-sdr-agent:assessment python -m app.worker
```

To run API and worker together (no local PostgreSQL is created):

```powershell
docker compose up --build
docker compose down
```

Both processes use the external `DATABASE_URL` in `.env`. Apply migrations before
starting them. Do not pass a production Resend key for assessment-only runs.

Run tests (external APIs are mocked and no email is sent):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

If pytest is installed, the equivalent full command is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## API endpoints

- `GET /health`
- `POST /leads/extract`
- `POST /leads/enrich`
- `POST /leads/{lead_id}/enrich`
- `POST /leads/score` (calculation only)
- `POST /leads/{lead_id}/score` (calculate and persist)
- `POST /events/open`, `/events/click`, `/events/reply` (assessment simulation)
- `POST /leads/{lead_id}/behavior` (evaluate and execute Scenario A/B/C)
- `POST /leads/{lead_id}/initial-outreach` (use persisted enrichment and score,
  decide, generate, safety-check, send, and record lifecycle/action)
- `POST /webhooks/resend` (raw-body signature verification and provider events)

The webhook uses the installed Resend SDK verifier and Svix headers. Supported
outbound events are stored with the Resend message ID and unique `svix-id` for
idempotency. `email.opened` and `email.clicked` become engagement events. Delivery,
bounce, complaint, delay, failure, suppression, and sent events are also retained.
`email.received` is deliberately not treated as a reply: its notification alone
does not prove it is a reply to a particular outreach or include reply text.

Lead URL extraction accepts only public HTTP(S) destinations. The initial URL and
every redirect hop are rejected when DNS resolves to loopback, private, link-local,
multicast, reserved, or other non-global addresses. Network failures are returned
as controlled client errors without exposing internal networking details.

## Design justification

FastAPI provides typed, inspectable HTTP contracts; SQLAlchemy text queries keep
the small PostgreSQL schema explicit; Supabase supplies managed PostgreSQL; OpenAI
is bounded to structured JSON outputs; and Resend supplies delivery plus signed
webhooks. This is intentionally a small service/repository architecture suited to
an assessment, without replacing deterministic business rules with an LLM.

Lead scoring is 90% deterministic (title, concrete authority evidence, ICP fit,
and real provider verification confidence) plus a maximum 10-point LLM contextual
check. Final score, classification, reason, and breakdown are persisted. Generic
buzzwords earn nothing without concrete authority evidence.

Enrichment is a waterfall: call Hunter Email Finder first, call Apollo People
Enrichment only after a Hunter miss/error, add deterministic name/domain patterns,
then rank candidates consistently. Provider timeouts, quota limits, authentication
or plan restrictions, invalid responses, and other HTTP failures are returned as
sanitized waterfall-step status; the next source still runs. Keys are sent in
provider headers and are never included in returned errors.
`candidate_score` is the internal selection score;
`provider_verification_confidence` is only a confidence supplied by a provider.
`provider_verification_status` retains values such as Hunter `valid` or Apollo
`verified`. Apollo does not expose a numeric confidence comparable to Hunter's
score, so Apollo confidence remains `null`. Generated patterns have neither
provider confidence nor verification and are never represented as verified. An
LLM never participates in recipient selection. The deterministic candidate score
uses a bounded bonus for provider statuses (`valid`/`verified`, `accept_all`, or
`extrapolated`) without rewriting those statuses as invented numeric confidence.
For persisted enrichment, the selected source, raw verification status, confidence,
candidate score, sanitized waterfall outcomes, and provider metadata are stored on
the lead record.

## Scanner filtering and limitations

When at least 20 opens occur inside any five-second rolling window, the burst is
marked `is_suspected_scanner=true`; behavioral decisions exclude those opens.
Both values are configurable. This deterministic heuristic is explainable and
reproducible, but imperfect: aggressive human refreshes can be false positives,
and slow scanners can evade it. Production detection should additionally consider
known scanner IP/UA intelligence, click timing, provider signals, and historical
baselines. Opens themselves are privacy-sensitive and inherently noisy.

## Safety and assessment demo

Never run manual email scripts against real leads. Automated tests mock OpenAI,
Resend, and repository calls. For a controlled demo: use test database records and
Resend's test recipient, run the API, create simulated open/click/reply events, call
the behavior endpoint, and inspect `email_logs`, `events`, and `agent_actions`.
Demonstrate Scenario A after 60 seconds, Scenario B with a click or two valid opens,
and Scenario C with “not interested”; then confirm a later send is blocked.

Run all decision-only fixtures without network or database access:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_scenarios
```

Run the full safe pipeline demonstration:

```powershell
$env:RESEND_TEST_MODE="true"
$env:RESEND_TEST_RECIPIENT="delivered@resend.dev"
.\.venv\Scripts\python.exe -m scripts.demo_end_to_end
```

This runner creates only a fixed synthetic lead and prints each enrichment,
scoring, initial-outreach, simulated-click, behavior, and action-log stage. Hunter,
Apollo, OpenAI, Resend, and database boundaries are mocked in-process. It therefore
cannot spend provider credits, mutate a database, or send an email; the displayed
Resend ID and delivery are explicit mock values. The two environment assignments
make the assessment intent visible, while the runner also asserts that its mocked
transport routes only to `delivered@resend.dev`.

For database-backed testing, use only synthetic leads. Insert an initial `sent`
email log, then use these endpoints: call the worker for Scenario A; post one click
for Scenario B click; post two spaced opens for Scenario B multiple opens; post an
unsubscribe reply for Scenario C; and mark a synthetic lead `unsubscribed` before
evaluating it to demonstrate the hard stop. Twenty simulated opens inside five
seconds demonstrate scanner filtering. Automated tests cover these flows without
calling providers.

The only permitted delivery demonstration is Resend's documented test recipient:

```dotenv
RESEND_TEST_MODE=true
RESEND_TEST_RECIPIENT=delivered@resend.dev
```

In this mode, each lead retains its own email in PostgreSQL and all decisions,
generation, email logs, duplicate checks, and safety gates remain associated with
that lead. Only the final provider destination is changed to
`delivered@resend.dev`. Structured action metadata records the logical recipient,
provider recipient, and test-mode flag. Test mode never bypasses an
`unsubscribed`/`dead` status or permits arbitrary unpersisted recipients. Missing
or unsupported test-recipient configuration fails closed before Resend is called.

Run the controlled transport demonstration with:

```powershell
.\.venv\Scripts\python.exe -m scripts.test_email_sender
```

That script explicitly opts into `delivered@resend.dev`. The transport rejects an
arbitrary recipient unless a lead ID is supplied and its current database status
and email are revalidated immediately before the provider call.

For deployment, set `RESEND_TEST_MODE=false`. Real-recipient outreach should only
be enabled after sender-domain verification, compliance and opt-out review, and
validation of recipient addresses and lawful outreach purpose.

Known limitations: the burst heuristic is deliberately simple; the scheduler is a
separate single-purpose polling process and has no dashboard or distributed job
history; inbound-email correlation/reply-body retrieval is not implemented;
generated candidates are not mailbox-verified. Hunter Email Finder and Apollo
People Enrichment responses vary by subscription, credit availability, and field
visibility. Apollo supplies no directly comparable numeric confidence in the
implemented response, so it remains `null`. Live Hunter/Apollo behavior and a
real-recipient run are intentionally not claimed by this assessment. The Docker
stack expects external PostgreSQL/Supabase and intentionally provides no local
database service.

## Assessment challenge answers

**A. Multiple candidate addresses:** normalize the name/domain, reject invalid and
role-based mailboxes, score deterministic patterns, incorporate real provider
confidence only as a separate bounded signal, sort by score, and select the stable
top candidate. Preserve source and both scores for auditability.

**B. Buzzwords vs. authority:** award points only for explicit evidence such as
revenue ownership, budget/procurement authority, team leadership, or GTM ownership.
Terms such as “innovative” and “results-driven” receive no authority points; a
buzzword-heavy bio without concrete evidence scores zero for that component.

**C. Artificial opens:** detect implausible rolling bursts, persist the scanner flag,
and exclude flagged opens from decisions. Keep thresholds configurable and combine
the heuristic with IP/user-agent/provider intelligence in production because no
single open-tracking rule can perfectly separate people from security software.
