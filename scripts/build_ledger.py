"""Extract all SRS IDs and retain source wording; enrich with actual implementation evidence."""
import json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
s=subprocess.check_output(['pdftotext','-layout',str(ROOT/'Miyazaki Industrial AI Copilot — SRS.pdf'),'-'],text=True)
pattern=re.compile(r'^(US-[A-Z]\d+)\s+(Must|Should|Could|Won.t \(v1\))\s+',re.M)
starts=list(pattern.finditer(s));items=[]
extra={'US-A06','US-A08','US-C07','US-C09','US-E06','US-E08','US-K07','US-F04'}
# Evidence entries are conservative: passing a subset test never establishes complete SRS acceptance.
info={
'A01':('Implemented','Workspace creation, unique slugs, industry/size/language and audit.','test_deactivation_blocks_access',''),
'A02':('Implemented','Seven-day single-use invitations, resend/revoke and localised protected outbox.','test_invitation_accept_replay_and_language; test_invitation_expiry_and_revoke','Live email delivery is optional and not validated.'),
'A03':('Partial','Invitation acceptance, password policy, saved language and onboarding entry.','test_invitation_accept_replay_and_language','Invited accounts now open the wizard on first login; seeded demo accounts intentionally bypass that first-run flag.'),
'A04':('Implemented','Member invitations, pending list, resend and membership removal.','test_invitation_expiry_and_revoke',''),
'A05':('Implemented','Login/logout, hashed tokens, password reset, idle expiry and database failed-login limiting.','test_bad_password_generic; test_logout_revokes_session; test_session_idle_expiry; test_reset_generic_and_one_use; test_failed_login_rate_limit','No independent penetration test.'),
'A06':('Implemented','Authenticator enrolment, codes, hashed recovery codes and verification.','test_mfa_enrollment_recovery_and_reuse','Local demo bypass is visible and enabled; production rejects this configuration.'),
'A07':('Implemented','Workspace-scoped API, records, vectors, files and relationships.','test_cross_workspace_endpoints; test_tenant_vector_retrieval; test_cross_workspace_reference_blocked','Security assurance is limited to the recorded test set.'),
'A08':('Partial','Named Coordinator grants/revocation and shared-profile read/comment checks.','test_coordinator_read_comment_scope','Document/workflow-specific Coordinator sharing remains unavailable.'),
'A09':('Partial','Persisted JA/EN switch, AI language and localised invitation/reset templates.','test_invitation_accept_replay_and_language; browser Japanese language toggle and font asset','Some statuses, domain content and secondary labels remain English.'),
'A10':('Implemented','Workspace deactivation/reactivation enforced by access checks; data retained.','test_deactivation_blocks_access',''),
'B01':('Implemented','Companies, calculated dormancy, filtering, sorting in API order, completeness/counts and CSV.','browser Admin dashboard, company records and audit','Name, completeness and activity sorting are exposed; broader sorting combinations are not independently tested.'),
'B02':('Implemented','Shared confirmed sections and aggregate counts without private content.','test_operator_only_shared_content',''),
'B03':('Partial','Status, funnel, weekly activity, industry and sentiment aggregates.','browser Admin dashboard, company records and audit','Most-chosen-use-case chart and precise profile-approval event definition require completion.'),
'B04':('Implemented','Platform editor, bilingual fields, states, version snapshots and Operator approval gate.','test_bilingual_publish_gate','Draft seed content is not approved Atomic Loops material.'),
'B06':('Implemented','Feedback inbox, tags/reply/status service and CSV.','test_feedback_and_admin_reply','Tag controls are not exposed in the simple UI.'),
'B07':('Implemented','Database trigger blocks audit mutation; access/action logs and filtering/search.','test_audit_append_only; test_operator_only_shared_content','Retention operations and independent tamper review remain production tasks.'),
'C01':('Partial','Resumable basic wizard and text/file/photo upload pipeline.','test_plain_pdf_docx_xlsx_pptx_extraction; browser Profile review modal and history','Wizard does not expose every SRS field; photos have no interpretation.'),
'C02':('Partial','Live/public and offline crawl, robots policy, redirects, limits, source URLs and progress.','test_offline_ingestion_and_injection_jobs; live Real offline ingestion pipeline','Live-site performance and DNS rebinding cases need broader validation; failure is conservative.'),
'C03':('Partial','Structured extraction and product add/edit/merge/delete domain endpoints.','live Real multilingual embedding and structured extraction','Product merge UI is present; deletion UI and per-statement product analysis need further work.'),
'C04':('Implemented','Eight sections, provenance/confidence, confirm/edit/reject and history.','test_fact_review_history_and_rejection; test_stale_fact_version_rejected',''),
'C05':('Implemented','Deterministic required fields, per-section/overall score, top gaps with question/template links.','browser English login and workspace redirect','Completeness rules are documented defaults, not Operator-approved scoring.'),
'C06':('Partial','Workflow facts and explicit chat-to-profile proposals with review and history.','test_workflow_b1_b3_answers_and_confirmation; test_fact_review_history_and_rejection','User messages now enqueue automatic fact capture; document-wide automatic capture and extraction quality need further validation.'),
'C07':('Partial','Re-analysis creates a new source and preserves confirmed facts.','test_fact_conflict_not_silent','Dedicated added/changed/removed fact diff UI remains incomplete.'),
'C08':('Implemented','Default overview/products sharing, settings, visibility rules and audit.','test_operator_only_shared_content',''),
'C09':('Partial','Japanese-font PDF and DOCX profile exports with date and provenance legend.','test_export_formats_and_japanese_font','Per-fact alternate-language translation exists; whole-profile translated export remains incomplete.'),
'C10':('Partial','Source instruction separation, suspicious source quarantine, private-address blocking.','test_prompt_injection_fixture_quarantined; test_offline_ingestion_and_injection_jobs','Regex quarantine is not comprehensive; full adversarial golden set remains required.'),
'D01':('Partial','B1-B4 initial proposals and product-specific deep dives; start/defer/dismiss.','test_workflow_b1_b3_answers_and_confirmation','AI rationale generation is queued per profile; rationale relevance is not yet reviewer-scored.'),
'D02':('Implemented','Generic step types/statuses, owner/due-date fields and versioned templates.','test_workflow_b1_b3_answers_and_confirmation','Owner/due-date editing UI needs expansion.'),
'D03':('Partial','Five-question sets, text answers, unknown/assignment and proposed Stated facts.','test_workflow_b1_b3_answers_and_confirmation','AI generates five bilingual follow-ups after the first five answers, up to ten total; live relevance scoring and upload answer interpretation remain unvalidated. Voice deferred.'),
'D04':('Partial','Stepper and simple dependency/feed display.','browser Workspace route workflows','Detailed profile/document/use-case dependency graph requires expansion.'),
'D05':('Implemented','Own linked chat and version-checked confirmed transitions.','test_pending_action_requires_confirmation_and_is_idempotent; test_workflow_b1_b3_answers_and_confirmation',''),
'D08':('Partial','B1/B3 complete into a findings document and confirmed profile updates.','test_workflow_b1_b3_answers_and_confirmation','Template-specific analyses and automatic next-proposal rationale need completion.'),
'E01':('Partial','Thread creation, pin/rename/archive and workflow/document context.','browser Chat creation and context controls','Message-content search and archived-thread recovery UI remain incomplete.'),
'E02':('Partial','Real SSE, Markdown/tables, citation context, copy/save/document/workflow/profile actions.','live Real Japanese grounded chat; test_pending_action_requires_confirmation_and_is_idempotent','Two-second p95 not established; streamed text needs stronger claim validation.'),
'E03':('Implemented','Real profile/source/workflow toggles and profile-off notice.','test_context_profile_off_excludes_history; browser Chat creation and context controls','Profile section-level toggles are now exposed in the context panel; dedicated per-section browser assertions remain to add.'),
'E05':('Partial','25 MB PDF/DOCX/XLSX/PPTX/text/image uploads; parsing of selectable text.','test_plain_pdf_docx_xlsx_pptx_extraction; test_misleading_pdf_rejected','Image/scanned interpretation deferred by user.'),
'E06':('Partial','Gap-based suggestions from home API and sample chat prompts.','browser English login and workspace redirect','Waiting-step/library-based suggestions and dismissal need completion.'),
'E07':('Partial','Explicit message-to-fact proposal, source reference and Company Admin review.','test_fact_review_history_and_rejection','Automatic user-message capture now runs as a background job; a mocked regression verifies proposed-only writes. Live capture quality remains unvalidated.'),
'E08':('Partial','Chat Markdown/PDF export and shared-with metadata.','test_export_formats_and_japanese_font','Explicit colleague sharing UI and per-chat visibility enforcement need completion.'),
'E09':('Implemented','Atomic reservations, calendar-month usage, 80% state and admin limit changes.','test_budget_reservation_concurrency','Home displays the 80 percent warning; the boundary has a backend reservation test but not a dedicated browser assertion.'),
'E10':('Partial','Bounded history, queued summary and visible summary area.','test_rejected_claim_not_in_historical_context','Summaries now use older turns and a revision-valid prior summary. Long-duration preservation and quality are not validated.'),
'F01':('Partial','File/URL ingestion, tags/statuses, quotas and embeddings.','test_plain_pdf_docx_xlsx_pptx_extraction; live Real multilingual embedding and structured extraction','Japanese OCR is explicitly deferred; image records are preview-only.'),
'F02':('Implemented','Extraction/summary, re-index and immediate retrieval exclusion on deletion.','test_source_delete_excludes_vector_and_reopens_fact',''),
'F03':('Partial','Prompt/template selection, context API, language and saved request.','live Real Japanese document generation and PDF export','Length is selected in the UI; explicit source/workflow picker UI needs completion.'),
'F04':('Partial','Outline stored before generation and available in draft editor.','browser Workspace route knowledge','Section-specific regeneration and formal outline editing are incomplete.'),
'F05':('Partial','Rich text, AI rewrite/shorten/expand/translate/table actions, fact insertion, comments, version compare/restore.','test_document_versions_restore; test_editor_stored_xss_removed','Formatting/table fidelity across rich editor and all exports is not fully preserved.'),
'F06':('Partial','DOCX/PDF/Markdown and local workspace downloads.','test_export_formats_and_japanese_font','Explicit member/Coordinator sharing controls need completion.'),
'F07':('Implemented','Save document with origin/version and enqueue indexing.','test_source_saved_from_document',''),
'F09':('Partial','Citation checks, conservative uncited-paragraph markers and export marker toggle.','test_invalid_citation_detected; live Real Japanese document generation and PDF export','Every-statement citation/assumption accuracy is not established.'),
'H01':('Partial','Bilingual draft method overview, stages, ladder, horizons and principles.','browser Workspace route ai-use-cases','Three report outcomes and examples require Atomic Loops source material.'),
'H02':('Partial','Seven-stage factory map, supporting lanes and draft descriptions.','browser Workspace route ai-use-cases','Profile-derived highlights and complete stage-specific operations/systems need completion.'),
'H03':('Partial','44 bilingual baseline cards, enriched draft fields, search and filters.','test_library_seed_44; browser Workspace route ai-use-cases','Draft fields are generic and require domain/Japanese review; no invented measured value ranges.'),
'H04':('Partial','Transparent rule-ranked recommendations tied to confirmed machining/inspection facts; add is idempotent.','test_usecase_add_and_dependencies','AI matching, richer gaps and recommendation-specific feedback need completion.'),
'H05':('Partial','Custom wizard, editable fields and AI charter document action.','test_usecase_add_and_dependencies','AI level classification and full charter journey not independently validated.'),
'H07':('Partial','Drag/drop quadrants, horizon timeline, dependencies API and roadmap export.','test_usecase_add_and_dependencies','Four readiness dimensions and year are editable; dependency editing UI and dynamic programme layout need completion.'),
'H10':('Partial','Draft stage learning/glossary foundation.','browser Workspace route ai-use-cases','Complete approved bilingual teaching material unavailable.'),
'I01':('Partial','Thumb ratings with target references on implemented outputs.','test_feedback_and_admin_reply','Reason/free-text capture is global; per-output detail flow needs completion.'),
'I02':('Implemented','Global category/text widget, screenshot upload, role/page/language capture.','browser Workspace route feedback','Screenshot is an uploaded image; no OCR.'),
'I03':('Implemented','Fact dispute, correction payload, review and inbox.','test_fact_review_history_and_rejection','Dispute correction UI is minimal.'),
'I04':('Implemented','User feedback history, statuses and Operator reply.','test_feedback_and_admin_reply',''),
'I05':('Partial','Analytics API by date/company/feature and CSV.','test_feedback_and_admin_reply','Detailed trend/feature charts not exposed in UI.'),
'I06':('Partial','Consent gate, local redaction, review acknowledgement and evaluation export.','test_eval_export_requires_consent; test_redaction','Automated redaction is not guaranteed anonymisation; reviewer must inspect preview.'),
'J01':('Partial','Notification centre, preferences, daily/weekly database-backed digests and outbox.','test_digest_deduplication','Some event hooks and optional SMTP delivery are not complete.'),
'J03':('Partial','Name/language/instructions/retention/members/grants/sharing, ZIP and deletion request.','test_workspace_zip_export; test_coordinator_read_comment_scope','Logo upload is present; complete approved deletion execution remains incomplete.'),
'J04':('Partial','Tour, contextual first steps and gap checklist.','browser English login and workspace redirect','Full bilingual help articles and automatic completed checklist are incomplete.'),
'J06':('Partial','Invitation terms acceptance, distinct feedback-use consent and change records.','test_invitation_accept_replay_and_language; test_eval_export_requires_consent','Seed-account first-login notice and legal review are incomplete.'),
'K01':('Partial','226 paired JA/EN resource keys and persistent language switch.','frontend-checks.txt; browser Japanese language toggle and font asset','Some hard-coded statuses/secondary content are still English.'),
'K02':('Implemented','User/request language passed to real model; mixed-script inputs supported.','live Real Japanese grounded chat; live Real English unknown-revenue answer','Human quality review still required.'),
'K03':('Partial','Workspace-language documents, selected-text translation and glossary foundations.','live Real Japanese document generation and PDF export','One-click alternate versions for every output are not complete.'),
'K04':('Partial','Selectable Japanese PDFs/HTML and original text; Japanese embedding model.','test_plain_pdf_docx_xlsx_pptx_extraction; test_scanned_pdf_explicit_limitation','OCR deferred; vertical layout/encoding corpus and translation labels require expansion.'),
'K05':('Partial','Paired library fields, draft states and version-aware Operator publication gate.','test_bilingual_publish_gate','Actual Operator Japanese approval not provided.'),
'K06':('Partial','Locale-formatted UI dates, numeric basics and ISO exports.','browser Japanese language toggle and font asset','All chart/status/currency formatting needs comprehensive validation.'),
'K07':('Partial','Multilingual embeddings and tenant-scoped semantic retrieval.','test_tenant_vector_retrieval; live Real multilingual embedding and structured extraction','Japanese-to-English relevance corpus is not yet evaluated.'),
'K09':('Partial','IME-safe chat Enter handling, bundled Japanese font and CJK PDF wrapping.','test_i18n_keys_and_ime_guard_present; test_export_formats_and_japanese_font; browser Mobile workspace layout','Full JIS typography and current/previous browser matrix not verified.'),
'K11':('Partial','Bilingual invitation/reset and notification digest templates.','test_invitation_accept_replay_and_language; test_digest_deduplication','All event wording and recipient-language combinations need review.')}
for n,m in enumerate(starts):
 block=s[m.start():starts[n+1].start() if n+1<len(starts) else s.index('5. Page examples',m.end())]
 lines=block.splitlines();head=lines[0]
 columns=re.match(r'^(US-[A-Z]\d+)\s+(Must|Should|Could|Won.t \(v1\))\s+(.*?)\s{3,}(.*)$',head)
 story=[];accept=[]
 if columns:
  storypos=columns.start(3);acceptpos=columns.start(4)
  for i,line in enumerate(lines):
   if i and re.match(r'^\s*(4\.\d+ |5\. |ID\s+Priority|Miyazaki Industrial|\f)',line):continue
   if i and line and not line.startswith(' '):break
   story.append(line[storypos:acceptpos].strip());accept.append(line[acceptpos:].strip())
 else:story=[re.sub(pattern,'',head)];accept=[]
 id=m.group(1);short=id[3:];priority=m.group(2);included=priority=='Must' or id in extra or id=='US-D09'
 values=info.get(short)
 if values:status,behaviour,tests,gaps=values
 else:status='Deferred';behaviour='Not built in this phase.';tests='';gaps='Roadmap scope follows SRS section 11. US-D09 includes only the E02-required conversion path.' if short=='D09' else 'Deferred to v2.' if short in ('B10','F10') else 'Deferred to v1.1.'
 if short=='D09':status='Partial';behaviour='Confirmed chat-to-B1 workflow draft path is implemented.';tests='test_pending_action_requires_confirmation_and_is_idempotent';gaps='General AI step drafting and editing remain deferred.'
 items.append({'id':id,'priority':priority,'included':included,'scope_reason':'SRS Must' if priority=='Must' else 'Explicitly included v1 or supporting capability' if included else 'SRS later release','story':' '.join(x for x in story if x),'acceptance_criteria':' '.join(x for x in accept if x),'status':status,'behaviour':behaviour,'tests':[t.strip() for t in tests.split(';') if t.strip()],'gaps':gaps,'evidence':['evidence/all-junit.xml','evidence/browser-results.json','evidence/live-model-results.json'] if tests else []})
assert len(items)==98,len(items)
assert sum(r['priority']=='Must' for r in items)==67
(ROOT/'docs/requirements.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
print('Ledger:',len(items),'stories;',sum(r['priority']=='Must' for r in items),'Musts')
