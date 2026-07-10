# Omnichannel Customer-Service Control Plane

## Status

Planned target architecture. No QianNiu, Pinduoduo, or JD production API is connected yet.

## Product Direction

The project is not a QianNiu-specific bot. It is a platform-neutral customer-service Copilot and supervision system that can connect multiple shops and platforms through adapters.

Target platforms include:

- QianNiu / Taobao / Tmall
- Pinduoduo
- JD
- local simulation, replay, and benchmark inputs

The Agent core must not depend on native platform payload names, authentication details, or message-send APIs.

## Target Flow

```text
QianNiu / Pinduoduo / JD / local replay
                    |
            platform inbound adapter
                    |
        canonical ConversationEvent
                    |
             AnalysisPipeline
                    |
  identity -> tools -> retrieval -> evidence gate
                    |
      grounded reasoning -> final safety gate
                    |
          canonical AgentDecision
             /               \
 platform outbound adapter   HandoffEvent
                                  |
                         supervision center
                                  |
                     desktop/WebSocket alert
```

## Canonical Conversation Contract

Every platform adapter should normalize its native payload into a common structure before the Agent runs:

```text
platform
tenant_id
shop_id
account_id
conversation_id
message_id
buyer_id_hash
customer_message
conversation_history
product_candidates
order_references
attachments
received_at
idempotency_key
platform_capabilities
platform_metadata
```

Rules:

- Raw platform payloads stay in the adapter/integration layer.
- The Agent must not branch on QianNiu, Pinduoduo, or JD field names.
- Product and order identifiers are resolved through canonical identity and tool contracts.
- Local replay and benchmark should construct the same canonical context instead of inventing separate Agent payloads.

## Canonical Agent Decision

The Agent returns a platform-neutral decision:

```text
suggested_reply
sendable_reply
reply_blocks
recommended_assets
can_send
requires_human_review
risk_level
handoff_reason
recommended_actions
selected_evidence
tool_requests
conversation_summary
```

The platform outbound adapter decides how supported text, image, video, product card, or order actions map to the platform API. Missing platform capability must never be simulated as a successful send.

## Platform Ports

Platform integrations should implement narrow ports rather than enter Agent nodes directly:

- `ConversationInboundPort`
- `MessageOutboundPort`
- `ProductLookupPort`
- `OrderLookupPort`
- `LogisticsLookupPort`
- `MediaDeliveryPort`
- `PlatformCapabilityPort`

Local mock adapters can implement these ports before production API access is approved. Real adapters should replace mocks without changing the Agent or evidence contracts.

## Human Handoff Contract

High-risk and human-review decisions create a durable `HandoffTask`, not only a browser toast.

```text
task_id
tenant_id
platform
shop_id
account_id
conversation_id
risk_level
handoff_reason
latest_messages
agent_suggested_reply
evidence_summary
assigned_to
status
sla_deadline
created_at
claimed_at
resolved_at
```

Recommended states:

```text
pending -> notified -> claimed -> handling -> resolved
                              \-> expired/escalated
```

Required behavior:

- deduplicate repeated platform events;
- allow only one active owner for a claimed conversation;
- record assignment, transfer, edit, send, and resolution actions;
- retry failed notifications;
- escalate unacknowledged P0/P1 tasks by SLA;
- preserve an audit trail without exposing raw secrets or unnecessary buyer PII.

## Supervision Center

The central supervisor account should support:

- all-platform and all-shop conversation status;
- high-risk and pending-handoff queues;
- claim, transfer, resolve, and reopen actions;
- SLA and unacknowledged-alert monitoring;
- Agent auto-send, safe-handoff, and error metrics;
- platform API, worker, and adapter health;
- knowledge, evidence, and media gaps;
- role-based access for administrators, supervisors, agents, reviewers, and auditors.

Desktop notification should be driven by a durable handoff event. WebSocket or desktop push is the presentation channel; the database task and acknowledgement state are the source of truth.

## Risk Routing

- `P0`: safety incident, ingestion, injury, severe complaint, threat, or other urgent risk. Immediate notification and acknowledgement required.
- `P1`: refund, replacement, order exception, conflicting evidence, or time-sensitive service action. Priority queue and SLA required.
- `P2`: ordinary knowledge gap or non-urgent verification. Normal queue.

Risk routing does not grant permission to send. `can_send` remains controlled by evidence eligibility, final safety checks, and platform capability.

## Control Plane And Data Plane

Data plane responsibilities:

- receive and normalize messages;
- run tools, retrieval, reasoning, and final gates;
- emit Agent decisions and outbound commands.

Control plane responsibilities:

- manage tenants, platforms, shops, accounts, roles, and policies;
- supervise handoff tasks, SLA, health, quality, and audit logs;
- manage configuration and rollout state.

These responsibilities should not be implemented inside Flask route handlers or LangGraph nodes.

## Current Reusable Components

- product identity resolution;
- JST product/order lookup capabilities;
- LangGraph Agent and tool registry;
- product context and evidence gates;
- RAG and pgvector shadow work;
- final response and delivery contracts;
- replay, benchmark, bad-case, and review concepts;
- Answer Memory and Grounded Reasoning shadow layers.

## Current Gaps

- no canonical multi-platform event schema;
- no single AnalysisPipeline shared by UI, sidecar, replay, and benchmark;
- no durable platform/account/shop ownership model;
- no formal outbound platform port;
- no durable HandoffTask assignment and SLA workflow;
- no event bus or independent worker boundary;
- QianNiu-specific context remains mixed with general Agent input in places;
- final response persistence and user-facing delivery stages require convergence.

## Implementation Order

1. Establish project governance, current architecture documentation, and ADRs.
2. Unify the analysis pipeline and final-response trace contract.
3. Define canonical conversation, Agent decision, and platform port schemas.
4. Implement local/mock adapters and contract tests.
5. Build durable handoff tasks and the supervision-center event flow.
6. Separate Web API and background workers.
7. Add QianNiu, Pinduoduo, and JD adapters as API access becomes available.

Production platform integration must not begin by adding platform-specific branches to Agent nodes.
