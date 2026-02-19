# AGENTS Instructions

## Purpose
Keep execution structured, track all changes, and preserve context quality across long projects.

## Required workflow
1) Before pushing:
- Summarize changes in plain English.
- Confirm included/excluded files in the push.

2) After pushing:
- Append entry to `docs/CHANGELOG_CUSTOM.md`:
- Date (YYYY-MM-DD)
- Bullet list of changes
- Files touched
- Do not push changelog file

3) Error-fix memory rule:
- If bug fix is confirmed by user, add it to project context to avoid repeat regressions.

## New Project Bootstrap (Mandatory)
- If `PROJECT_CONTEXT.md` does not exist, create it before implementation.
- Ask kickoff questions first, then write `PROJECT_CONTEXT.md` from answers.
- Do not start coding before context is confirmed.

### Kickoff questions (required)
- Project goal and success criteria
- Users/roles and access boundaries
- In-scope vs out-of-scope
- Core modules/screens for V1
- Tech stack and deployment preference
- Integrations (APIs, automations, external services)
- Timeline expectations
- Budget/pricing style
- Approval process for future changes

### Kickoff style rule
- Do not use rigid copy-paste questionnaire.
- Adapt questions to project/client context.
- Ask only what is needed to lock execution decisions.

## Minimum files/folders for every new project
- `AGENTS.md`
- `PROJECT_CONTEXT.md`
- `docs/`
- `docs/CHANGELOG_CUSTOM.md`
- First plan: `docs/plan-YYYY-MM-DD-HHMM-<task>.md`

## Session start rules
- Read `PROJECT_CONTEXT.md` first.
- Review existing `docs/plan-*.md`.
- Check latest context in `docs/CHANGELOG_CUSTOM.md`.

## Project Closing Pack Workflow
- Trigger: `closing project`, `finish project`, `project handover`.

### Required closing documents
1) Delivery Acceptance
2) Final Invoice
3) Scope Freeze + Change Policy
4) Support Terms
5) Handover Pack (guides, links, credentials checklist if applicable)

### Closure email package
- Send all closing docs in one email.
- Request explicit acceptance and payment confirmation.
- State that new modules/features require written pre-approval of scope, price, and timeline.
