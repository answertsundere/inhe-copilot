# Project Documentation Index

This index lists durable design and operating documents for the INHE customer-service Copilot.

## Current Status And Roadmap

- `docs/current-system-status.md` - historical system-status snapshot.
- `docs/top_rag_development_roadmap.md` - top-level RAG development roadmap.

## Real Replay And Evaluation

- `docs/REAL_REPLAY_SIDECAR_DATA_REQUIREMENTS.md` - QianNiu sidecar data requirements for real replay.
- `docs/real_conversation_daily_replay.md` - daily real-conversation replay process.
- `docs/training_sample_eval_set_conversion.md` - reviewed training-sample evaluation-set conversion.

## Answer Memory

- `docs/answer_memory_layer.md` - Answer Memory Layer design, safety contract, data model, import flow, and shadow trace.

Current status: MVP implemented as a shadow/reference layer. The optional shadow-to-draft adapter can append `answer_memory_guidance` to analyze responses when `COPILOT_ANSWER_MEMORY_SHADOW_ENABLED=true`, but it cannot change `can_send`.

Entry points:

- `app/services/answer_memory_service.py`
- `app/services/answer_memory_adapter_service.py`
- `scripts/import_answer_memory_from_training_samples.py`
- `scripts/trace_answer_memory_for_training_samples.py`
- `scripts/trace_answer_memory_adapter_for_training_samples.py`

## Retrieval And Shadow Experiments

- `docs/llamaindex_shadow_poc.md` - LlamaIndex shadow proof of concept.
- `docs/embedding_config.md` - embedding configuration notes.

## Architecture

- `docs/langgraph-architecture.md` - LangGraph architecture.
- `docs/sidecar_client_setup.md` - sidecar client setup notes.
