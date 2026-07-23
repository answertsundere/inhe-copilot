# Project Charter

## Mission

Build a platform-neutral, evidence-grounded customer-service Copilot for INHE
that can assist or safely automate service across QianNiu, Pinduoduo, JD, and
future channels while giving supervisors one auditable control center.

The product is not a QianNiu-specific reply bot. QianNiu is the first planned
adapter around a reusable customer-service core.

## Business Truth Flow

For a product question, the intended truth path is:

```text
channel context or customer reference
-> external product identity
-> JST/internal product identity
-> reviewed structured facts, scoped knowledge, or described media
-> bounded reasoning
-> final safety and delivery decision
```

For an order, logistics, promotion, refund, replacement, or other live-state
question, the intended truth path uses the relevant platform/JST tool or an
approved policy source. Historical replies and generic service actions cannot
replace live state.

## Product Goals

- Resolve the correct product and order before answering scoped questions.
- Answer ordinary questions naturally from verified facts and low-risk bounded
  reasoning instead of defaulting every uncertainty to a scripted handoff.
- Block unsupported high-risk claims and unsupported platform actions.
- Learn handling patterns and tone from reviewed historical answers without
  treating those answers as product truth.
- Normalize all channels into one conversation contract and one analysis
  pipeline.
- Create durable handoff tasks for high-risk, unresolved, or human-only work.
- Give supervisors a cross-platform view of queues, SLA, quality, evidence gaps,
  platform health, and Agent behavior.
- Make every delivered answer reproducible from its context, evidence, tools,
  pipeline version, and final audit.

## Non-Goals

- Do not encode one-off customer sentences, SKUs, orders, or benchmark scenarios
  in production logic.
- Do not turn missing knowledge into confident prose.
- Do not infer strong safety or compliance claims from a broad material name.
  For example, `PP` alone does not prove food grade, non-toxicity, certification,
  or child suitability.
- Do not use Answer Memory, service actions, or media references as direct
  product facts.
- Do not build separate Agent logic for each commerce platform.
- Do not treat a benchmark pass rate as production readiness when benchmark,
  replay, and user-facing entry points execute different stages.

## Quality Definition

A strong answer must satisfy all of the following:

1. It answers the current customer question and relevant conversation context.
2. Product and order identity are correct.
3. Factual claims are supported by eligible evidence or explicitly allowed
   low-risk reasoning.
4. High-risk claims and actions obey policy and tool requirements.
5. The wording sounds like a capable human representative, not an internal risk
   engine.
6. Media promises match actual delivered reply blocks.
7. `can_send` reflects evidence, final audit, and channel capability.
8. Trace, snapshot, replay, and delivered output describe the same final result.

## Current Phase

The project is in **Agent Core capability convergence**, not broad feature
expansion and not production automation.

The current priority is one real-conversation vertical slice through the
existing formal Pipeline:

```text
context
-> goals
-> identity and tools
-> admitted evidence
-> one model-first reply
-> final safety/delivery gate
-> supervisor assist or handoff
```

Near-term success is measured by supported-claim correctness, action completion,
unnecessary handoff, naturalness, latency, and safety on comparable real
conversations. Additional review pages, shadow subsystems, provider
qualification frameworks, and platform-specific behavior are frozen unless
that slice proves they are the earliest blocker.

Synthetic benchmark success remains regression evidence only. When approved
real labels are insufficient, the project reports `real_accuracy=null`.

ADR 0009 defines this mainline and its rollback boundary.
