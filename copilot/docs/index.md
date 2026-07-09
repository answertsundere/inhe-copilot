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

Current status: MVP implemented as a shadow/reference layer. It is not connected to live Agent reply generation and cannot change `can_send`.

## Retrieval And Shadow Experiments

- `docs/llamaindex_shadow_poc.md` - LlamaIndex shadow proof of concept.
- `docs/embedding_config.md` - embedding configuration notes.

## Architecture

- `docs/langgraph-architecture.md` - LangGraph architecture.
- `docs/sidecar_client_setup.md` - sidecar client setup notes.
