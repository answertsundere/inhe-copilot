# P1 E2 Long-Conversation Evaluation Plan

## Purpose

`P1-E2-001` is the next quality gate for the Gold Customer Service Agent. It
evaluates the existing formal `/api/analyze` and `AnalysisPipeline` on an
authorized, privacy-safe, deidentified long-conversation review set. It is a
review-only evaluation: it does not write knowledge, call a side-effect tool,
or enable `can_send`.

The purpose is to test whether the Agent behaves like a capable service
representative when one conversation has several turns and several needs. It
does not test static product truth. Product, order, price, policy, stock, and
logistics facts remain answer-time evidence problems; missing or unverified
facts must remain unresolved.

The conversation-quality package and an evidence-enabled quality slice have
different input requirements. A deidentified conversation-only package may
intentionally omit product facts and identities, but then it can evaluate only
understanding, continuity, restraint, and unresolved handling. It must not be
used to diagnose retrieval or admission coverage. An evidence-enabled slice
requires a separate, local, reviewed Sidecar that binds each scenario to an
exact structured `sku`, `i_id`, product ID, or order-to-product identity. A
missing or ambiguous binding is an input/context gap. Titles, customer text,
historical agent replies, and semantic similarity cannot create that binding.

## Entry Conditions

1. The data owner authorizes the selected conversation source for internal
   quality evaluation.
2. Direct identifiers, contact details, addresses, order IDs, tracking IDs,
   payment details, and free-text personal data are removed or replaced with
   irreversible opaque placeholders before any model call.
3. Each retained turn has an immutable source hash, a dataset version, a
   redaction report, and a retention/deletion owner. Raw conversations do not
   enter the repository or model prompt.
4. Review labels stay outside Agent input and identify only conversation
   behavior: explicit goals, supplied context, required unresolved boundaries,
   forbidden unverified outcomes, and handoff need. They must not provide
   product facts or preferred answer sentences.
5. The run uses a query-only snapshot, explicit provider/model identity,
   feature flags, runtime commit, and the existing formal Pipeline.
6. An evidence-enabled run additionally verifies exact Sidecar identity before
   the first Agent call. The dataset manifest reports identity-covered,
   identity-missing, and identity-ambiguous denominators separately. A zero
   identity denominator invalidates evidence-coverage conclusions even when the
   conversation-quality package itself remains valid.

## Dataset And Procedure

The data owner selects a configurable representative slice across journey
stages and risk classes. The manifest records selection rules and exclusions.
For each deidentified conversation, label atomic goals, supplied context,
supported/unresolved/prohibited/tool-pending/handoff-required status, prohibited
outcome claims, and Supervisor Assist status.

Run the unchanged formal `/api/analyze` entry point in review-only mode. Capture
opaque case aliases, runtime identity, source hashes, provider/model, flags,
latency, errors, evidence role decisions, `requires_human_review`, and
`can_send`. Measure goal recall and precision, duplicate or merged goals,
repeated-known-context requests, supported attribution, unresolved coverage,
prohibited outcome assertions, media-delivery assertions, and handoff
necessity. Independent reviewers score factual restraint, goal completion,
naturalness, empathy/politeness, business helpfulness, and bounded reasoning.

For the evidence-enabled slice, pass only reviewed exact structured identity
from the Sidecar through the existing canonical input. Formal Evidence
Convergence may be enabled only in the isolated runtime; its production default
remains disabled. Report Product Context Pack candidates, admitted direct
facts, selected evidence, unresolved claims, and each identity/fact coverage
gap. Do not turn a no-identity case into a generic retrieval miss, and do not
count a no-fact case against the admission algorithm.

## Hard Stops And Exit Evidence

Stop when authorization, deidentification, hashing, label isolation, formal
Pipeline identity, or query-only controls fail; when knowledge changes or DML is
attempted; or when a candidate enables sending, omits required review, asserts
an unsupported high-risk claim, claims a side effect, or claims undelivered
media. Do not compare non-equivalent runtimes or hide exclusions through reruns.

E2 produces a signed internal report with dataset identity, scorable and
excluded denominators, results, reviewer decisions, safety findings, latency,
and risks. It is not a production promotion: `real_customer_accuracy=null` and
`optimization_unverified=true` remain until a separately approved program.
P2-P4 remain blocked until P1 E2 is accepted; customer-visible after-sales
steps also require typed current evidence and durable handoff receipts.
