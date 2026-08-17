# Supervisor Assist Workbench Design

## Goal

Provide a Chinese, supervisor-only conversation workbench at `/ask/real-test`
for manually testing the existing formal `/api/analyze` pipeline. The page
must preserve multi-turn context, expose the complete candidate reply and a
small evidence/status summary, and never send a reply to a customer channel.

## Architecture Boundary

The workbench is a presentation client, not a new Agent path. It calls the
existing formal analyze endpoint once per buyer turn and sends prior turns in
the existing `conversation_history` contract. It does not add a Graph node,
service, model call, reply owner, evidence rule, delivery rule, or `can_send`
condition.

The legacy server-rendered `/real-test` page is replaced by the existing Vue
SPA entry. The Vue router owns `/real-test` under `WorkbenchLayout`; Flask
serves the same built SPA shell used by the other `/ask/*` management routes.

## User Experience

- Center: continuous buyer/assistant conversation with a stable composer at
  the bottom.
- Right: optional product and order context (`product_name`, `sku_code`,
  `i_id`, `order_id`, `tracking_no`). Empty values are omitted from requests.
- Assistant turns: full candidate reply, copy action, elapsed time, evidence
  count, and clear human-review status.
- Evidence detail: collapsed by default and limited to safe evidence UID,
  role, fact type, attribute, source, and review status summaries. Complete
  traces and internal reasoning are not displayed.
- Errors: Chinese, actionable, and retained as a failed turn so the operator
  can retry without losing the conversation.
- Reset: starts a new local conversation and clears messages while preserving
  manually entered context.

The visual language follows the existing quiet operations console: white and
light-gray working surfaces, indigo actions, compact labels, square-ish 6px
corners, and no decorative marketing composition. The conversation timeline is
the signature element: buyer and candidate replies share one readable vertical
record instead of floating chat bubbles.

## Safety And Privacy

- No send, accept, or channel-delivery action exists on the page.
- Every assistant result is labelled as requiring operator confirmation,
  regardless of any runtime `can_send` value.
- Copying is the only outbound user action and copies candidate text only.
- Context is kept in page memory and is not persisted by the frontend.
- The page does not expose complete trace, hidden model reasoning, credentials,
  or raw knowledge records.

## Error Handling

- Empty message: do not call the API.
- Request timeout/network failure: show a Chinese error and allow retry.
- Empty candidate reply: display a deterministic UI error; do not invent text.
- Malformed evidence fields: ignore unsupported fields and keep the response
  usable.

## Acceptance

1. `/ask/real-test` loads the Vue workbench instead of the legacy template.
2. A second buyer turn sends the first buyer and assistant turns as canonical
   history, excluding the current message.
3. Optional context is omitted when blank and preserved when provided.
4. Candidate reply, latency, evidence count, and review state are visible.
5. The page has no customer-channel send control and never changes `can_send`.
6. Frontend build, route regression, and desktop/mobile browser checks pass.

