# Architecture Decision Records

Use ADRs for decisions that change production data flow, module ownership,
platform contracts, persistence, queues, retrieval backends, reasoning promotion,
or safety/delivery authority.

## Required Sections

```text
Title
Status: proposed | accepted | superseded | rejected
Date
Context
Decision
Alternatives considered
Business and safety consequences
Migration and rollback
Verification
```

Name records `NNNN-short-title.md`. Link accepted and active ADRs from
`docs/index.md` and the relevant durable design document.

An ADR is not required for a narrow implementation bug whose intended behavior
is already defined by an existing contract.
