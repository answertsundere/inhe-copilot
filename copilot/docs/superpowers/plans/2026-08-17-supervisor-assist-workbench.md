# Supervisor Assist Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Chinese, review-only multi-turn test workbench on the existing formal analyze pipeline.

**Architecture:** Replace the legacy `/real-test` HTML owner with the existing Vue SPA, add one focused API adapter and one workbench view, and keep conversation state in the browser. The backend Agent pipeline, evidence admission, Safety, Delivery, and `can_send` contracts remain unchanged.

**Tech Stack:** Vue 3, TypeScript, Vue Router, Element Plus, Axios, Flask, Pytest, Vite.

## Global Constraints

- Use only `POST /ask/api/analyze` through the existing formal pipeline.
- Never expose a customer-channel send action; every result remains operator-reviewed.
- Do not add an Agent owner, service, graph node, model call, retry, repair, fallback, or evidence rule.
- Do not persist entered product/order context in the frontend.
- Keep all visible copy in concise Chinese.

---

### Task 1: Route Ownership

**Files:**
- Modify: `tests/test_copilot_panel.py`
- Modify: `app/main.py`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/vite.config.ts`

**Interfaces:**
- Produces: `/ask/real-test` as an SPA route rendered by `WorkbenchLayout`.

- [ ] Add a failing Flask test asserting `/real-test` returns the SPA shell and not the legacy test template.
- [ ] Run `python -m pytest tests/test_copilot_panel.py -q` and confirm the new assertion fails.
- [ ] Move the old template to `/real-test-legacy`, add `/real-test` to the SPA route set, add the Vue child route, and remove the Vite proxy interception for `/ask/real-test`.
- [ ] Run the route test and confirm it passes.

### Task 2: Analyze API Adapter

**Files:**
- Create: `frontend/src/api/supervisorAssist.ts`
- Create: `frontend/src/utils/supervisorAssist.ts`

**Interfaces:**
- Consumes: buyer message, prior `ConversationTurn[]`, and optional `WorkbenchContext`.
- Produces: `AnalyzeRequest`, `AnalyzeResponse`, `CandidateObservation`, and safe evidence summaries.

- [ ] Define explicit request/response types matching `/api/analyze`.
- [ ] Implement pure payload construction that excludes empty context and the current turn from history.
- [ ] Implement response normalization without generating fallback customer text.
- [ ] Post through a dedicated Axios client with a 120-second timeout and existing admin identity headers.
- [ ] Verify with `npm run build` after the view is connected.

### Task 3: Chinese Multi-Turn Workbench

**Files:**
- Create: `frontend/src/views/SupervisorAssistWorkbenchPage.vue`
- Modify: `frontend/src/components/layout/WorkbenchLayout.vue`

**Interfaces:**
- Consumes: `analyzeForSupervisor(request)` from Task 2.
- Produces: local multi-turn conversation, context form, candidate observation, copy/reset/retry controls.

- [ ] Build the dense desktop split layout and responsive single-column layout.
- [ ] Add message submission, exact prior-turn history, failure retention, and one-click retry.
- [ ] Render candidate reply, elapsed time, evidence count, review status, and collapsed safe evidence detail.
- [ ] Add copy and reset controls; do not add a send or approve action.
- [ ] Make the shared workbench heading use route metadata so replay and live testing have correct Chinese titles.

### Task 4: Verification And Documentation

**Files:**
- Modify: `docs/index.md`
- Modify: `docs/module-index.md`

**Interfaces:**
- Produces: a durable entry for the workbench and verified local URL.

- [ ] Run `python -m pytest tests/test_copilot_panel.py -q`.
- [ ] Run `npm run build` and verify generated assets load under `/ask/assets/`.
- [ ] Start Vite against the existing local API and open `/ask/real-test`.
- [ ] Verify desktop and mobile screenshots, empty/error states, and no overlap.
- [ ] Run `git diff --check`, inspect staged scope, commit, and push the feature branch.

