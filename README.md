# Miyazaki Industrial AI Copilot

A local-first React/FastAPI demonstration with PostgreSQL + pgvector, Ollama, a reviewed fact ledger, workspace-isolated retrieval, discovery workflows, document generation and manufacturing use-case planning.

**This is a controlled-localhost demonstration, not a production-certified release.** The two reports in `output/docx/` and the individual entries in `docs/requirements.json` distinguish implemented behaviour, partial acceptance and deferred scope. Japanese OCR/image interpretation is intentionally deferred. Draft Japanese and Atomic Loops content needs human approval.

## Install on another machine

1. Install Python 3.11+, PostgreSQL and the **pgvector package matching the PostgreSQL major version**. Install/start Ollama.
2. Create a virtual environment with `python -m venv .venv` and activate it using your platform's normal activation command.
3. Install `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env`. Set `DATABASE_URL` to a dedicated demo database and a role allowed to create it, or have an administrator create the database first. An administrator must enable `CREATE EXTENSION vector;` if the application role cannot do so.
5. Run `python manage.py setup`. It applies versioned migrations, creates deterministic synthetic seeds, and pulls missing models with progress. Run this with internet access **before** the venue demo.
6. Run `python manage.py check` to verify the database, schema, extension, Japanese/English answers, embeddings and bundled files.
7. Run `python manage.py run`. It serves the built frontend and API on `http://127.0.0.1:8000` and opens the browser.

A running PostgreSQL service and running Ollama service are required. No Docker, Redis, Celery, SMTP server or Node is required on a demo machine. All models, scripts, styles and fonts must be present before going offline. Models may be transferred using Ollama's supported model-storage procedure, then verified with `check`.

`python manage.py setup --no-pull` initialises the database without downloading models. `python manage.py check --no-smoke` skips model generation. `python manage.py seed --reset` resets only demo-owned content and refuses a database whose name does not contain `demo`; it retains the append-only audit trail and existing account passwords. Re-running setup does not reset work.

### Demo accounts

For synthetic **localhost-only** use, setup prints the password `MiyazakiDemo2026!` and these accounts:

| Account | Role |
| --- | --- |
| company@demo.local | Company Admin, Sample Co. A |
| member@demo.local | Member, Sample Co. A |
| other@demo.local | Company Admin, Sample Co. B |
| admin@demo.local | Operator Super Admin |
| platform@demo.local | Platform library editor |
| advisor@demo.local | Coordinator, initially unassigned |

`DEMO_SKIP_MFA=true` is a visible demo bypass. The real MFA flow can be exercised by disabling it, or enrolling in security settings. Invitations and resets go to the authenticated development outbox. Company Admins can see their own workspace outbox; Operator admins can inspect the demonstration outbox.

## Models and offline flow

Default generation is **qwen2.5:3b**, with **bge-m3** embeddings (1,024 dimensions). The tested Ollama 0.40.3/Qwen3 combination emitted reasoning instead of final answers, so the configured default was changed after measurement. Qwen3 remains installed and configurable; upgrading Ollama or switching generation model does not require re-indexing. Changing the embedding model/dimension does require a compatible embedding space/schema migration and a full re-index; this build rejects dimension mismatches rather than mixing vectors.

Open Knowledge, choose Analyse website, and select the saved snapshot. The synthetic fixture is clearly labelled and uses the actual ingestion/extraction/indexing pipeline. A malicious fixture is available to demonstrate quarantine. Live fetching respects robots rules and blocks private destinations, but it requires internet and has not been verified against a 200-page manufacturer corpus.

## Demo storyline

1. Operator creates a company and opens its invitation in the scoped outbox.
2. Company accepts, enters basic facts and analyses an offline snapshot or uploads a selectable-text document.
3. Review proposed profile facts. Confirm/edit/reject; inspect history and source references.
4. Start discovery, answer questions, review facts and confirm workflow transitions.
5. Open a conversation; inspect context toggles and citations. Unknown claims should be questioned, not treated as verified facts.
6. Generate a document, edit, inspect versions and export PDF/DOCX/Markdown.
7. Add a library candidate, define a custom use case, move it on the roadmap and export.
8. Submit feedback and inspect the Operator inbox/audit. Show that Sample Co. B's data is unavailable to company A.

## Development

Node is needed only for frontend changes:

```
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix frontend test
```

Built files under `frontend/dist/` are intentionally shipped. API server reload/multiple Uvicorn workers are disabled for the one-process demonstration. The API schema is available at `/openapi.json`; external-CDN Swagger/Redoc pages are disabled.

Python development tooling is in `requirements-dev.txt`. Backend tests **require a separate database whose name contains `security_demo`**; they truncate that test database. Set `TEST_DATABASE_URL` to the separate database using your environment configuration, then run:

```
python -m pytest tests -q --junitxml=evidence/all-junit.xml
```

Never point that setting at a database with valuable data. The default test URL uses localhost port 55432 and database `miyazaki_security_demo`, matching the isolated instance used during implementation.

`python scripts/live_smoke.py` uses running localhost services and synthetic demo records, creating sources/chats/documents. It does not mock the model. Browser checks are in `scripts/browser-tests.mjs`; its Playwright import path is the implementation environment's bundled runtime and should be adjusted to your installed Playwright package before reuse elsewhere.

## Reports and evidence

- `docs/decisions.json`: recorded decisions and consequences.
- `docs/requirements.json`: all 98 SRS stories, scope, actual status, gaps and evidence mappings.
- `scripts/build_ledger.py`: regenerates the ledger from the supplied SRS plus maintained implementation annotations; requires `pdftotext` on the authoring machine only.
- `scripts/generate_reports.py`: creates the two DOCX reports from the ledgers and retained evidence. During this build it is run with the Codex bundled document runtime.
- `evidence/`: JUnit, browser checks, dependency audits, real-model checks, preflight and sanitised screenshots of synthetic data.
- `output/docx/`: final decision/change log and requirements/security report.

DOCX creation/rendering tools are authoring-time dependencies. They are not needed to run the deployed demo. Application exports use pip-only libraries and the bundled font.

## Security and production limits

The application checks tenant ownership server-side, validates linked references, scopes vector queries before ranking, hashes passwords/tokens, enforces CSRF/strict cookies, blocks audit updates/deletes with a database trigger, and requires confirmation for proposed workflow mutations. Jobs have durable state, idempotent keys, leases, cancellation and bounded retries. Unknown extraction is not silently marked successful.

**Do not expose this demo to a shared network or the internet as-is.** Before such use: replace demo credentials, disable MFA bypass, configure TLS/secure cookies/trusted hosts, use a least-privilege runtime database role, remove the development outbox, approve notices/content, and complete remaining permission/feature and deployment checks. `DEMO_MODE=false` rejects several unsafe defaults but is not a production deployment recipe.

Important remaining work includes full claim-level factual evaluation, a complete prompt-injection corpus, exhaustive upload/parser and resource-exhaustion testing, complete Coordinator/document sharing, some secondary localisation/UI acceptance criteria, retention/deletion execution, encrypted MFA secret handling, an independent penetration test, accessibility/browser audits, production backups/restore verification, load/SLA testing and approved Japan-region/provider agreements. The reports are the detailed source of truth.

Citation handles establish references, not semantic truth. Generated drafts still require human verification. Known unverified profile values are rejected, uncited prose is marked conservatively, and confirmed evidence is used for document generation; these controls are not a proof against every possible hallucination.
