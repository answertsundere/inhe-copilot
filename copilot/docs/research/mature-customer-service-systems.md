# Mature Customer-Service Systems Research

## Purpose

This note records the architecture patterns that should be considered before the
project builds additional control-plane infrastructure. It is not a vendor
selection and does not authorize a production dependency.

## Systems Reviewed

- Microsoft Dynamics 365 Customer Service: cases, unified routing, queues, SLA,
  analytics, and AI-to-human handoff with conversation context.
  - https://learn.microsoft.com/en-us/dynamics365/customer-service/
  - https://learn.microsoft.com/en-us/dynamics365/customer-service/administer/overview-unified-routing
- Zendesk: omnichannel queues, skills, agent capacity, priority/SLA, and routing
  diagnostics.
  - https://support.zendesk.com/hc/en-us/articles/4409149119514-About-omnichannel-routing
- Amazon Connect: event-driven contacts, queues, tasks, cases, agent workspace,
  and real-time alerts.
  - https://docs.aws.amazon.com/connect/latest/adminguide/contact-events.html
  - https://docs.aws.amazon.com/connect/latest/adminguide/tasks.html
- Intercom Fin: grounded support-content retrieval, answer inspection, escalation
  rules, workflow handoff, and context collection before human escalation.
  - https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained
  - https://www.intercom.com/help/en/articles/12396892-manage-fin-ai-agent-s-escalation-guidance-and-rules
- Chatwoot: self-hosted inbox/control-plane patterns, assignment, capacity, SLA,
  webhooks, teams, and separate web/worker/PostgreSQL/Redis architecture.
  - https://developers.chatwoot.com/self-hosted/deployment/architecture
  - https://www.chatwoot.com/hc/user-guide/articles/1763978164-chatwoot-assignment-v2

## Common Mature Pattern

Mature systems separate:

1. channel ingestion and normalization;
2. durable conversations, cases, and tasks;
3. queues, routing, skills, capacity, and SLA;
4. agent workspace and human takeover;
5. knowledge and AI assistance;
6. audit, analytics, quality, and health monitoring;
7. web/API processes from asynchronous workers.

The INHE project should keep its differentiated Agent, product identity, evidence
governance, and safety logic. It should evaluate reuse for generic inbox, task,
assignment, notification, and supervisor capabilities instead of assuming all
control-plane infrastructure must be custom-built.

## Recommended Reuse Evaluation

Before implementing the full supervisor control plane, run a bounded proof of
concept comparing:

- integrating the INHE Agent with a mature self-hosted control plane through
  webhooks/APIs; and
- implementing the minimum canonical event, HandoffTask, assignment, and SLA
  services in this repository.

The comparison must cover Chinese commerce adapter needs, data ownership,
permissions, deployment burden, customization limits, auditability, and total
operating cost. QianNiu, Pinduoduo, and JD adapters will likely remain custom even
if inbox and handoff infrastructure is reused.

## Phase 0.2 Pipeline Decision

For the current modular-monolith convergence work, three official references
support a single explicit application pipeline without introducing new runtime
infrastructure:

- Flask application factories keep route registration and application lifecycle
  separate from reusable services, and make multiple configured instances
  practical for testing. This supports routes delegating to one service rather
  than owning delivery behavior.
  - https://flask.palletsprojects.com/en/stable/patterns/appfactories/
- OpenTelemetry defines a trace as structured spans with attributes, events, and
  status. The project adopts the smaller idea of named ordered pipeline stages
  and final outcome metadata; it does not add the OpenTelemetry dependency or a
  collector in this phase.
  - https://opentelemetry.io/docs/concepts/signals/traces/
- Rasa documents flows as explicit ordered actions, data collection, backend
  access, and response delivery. The project borrows the boundary clarity, not
  Rasa's runtime or a second dialogue manager.
  - https://rasa.com/docs/learn/concepts/dialogue-management/

The reviewed external strategy report recommends queues, Kafka, Flink, vector
infrastructure, and Kubernetes at larger scale. Those are not adopted here:
the verified problem is duplicated in-process stage ownership, so a single
pipeline and final-response trace contract are the smallest reversible repair.
