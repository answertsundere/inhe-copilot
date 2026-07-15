# Real Conversation Daily Replay MVP

This MVP imports sanitized long customer-service conversations, replays buyer
turns through the existing Agent chain, and exposes stored traces for manual QA.

## Import Samples

Dry-run, no database writes:

```powershell
python scripts\import_real_conversation_eval_cases.py `
  --source-dir "D:\桌面文件\客服质检系统" `
  --limit 50 `
  --min-turns 6 `
  --output outputs\real_conversation_import_preview.json
```

Apply sanitized samples to `eval_cases` and `eval_conversation_turns`:

```powershell
python scripts\import_real_conversation_eval_cases.py `
  --source-dir "D:\桌面文件\客服质检系统" `
  --limit 50 `
  --min-turns 6 `
  --apply `
  --output outputs\real_conversation_import_apply.json
```

## Replay Existing Samples

Replay already-imported `source_type=real_conversation` cases:

```powershell
python scripts\run_daily_real_conversation_replay.py `
  --replay-only `
  --limit 50 `
  --output outputs\real_conversation_replay.json
```

## Import And Replay

Write sanitized samples first, then replay:

```powershell
python scripts\run_daily_real_conversation_replay.py `
  --source-dir "D:\桌面文件\客服质检系统" `
  --limit 50 `
  --min-turns 6 `
  --apply `
  --output outputs\real_conversation_daily.json
```

## Safety Contract

- Default mode is dry-run. Database writes require `--apply`.
- The importer stores sanitized text only.
- The replay uses the existing Agent entry point and does not write product
  knowledge, RAG data, training data, or repaired answers.
- Human review writes only review records.
- The original human reply is stored as reference context, not as a gold answer.

## Versioned Active Benchmark Fixture

The reviewed active benchmark is also available as a privacy-safe, versioned
fixture under `tests/fixtures/agent_benchmark/`. It is a semantic projection:
it retains the reviewed evaluation contract while replacing customer turns,
product identities, order identities, source identifiers, and titles with
synthetic values. It is the required source for clean-worktree and CI benchmark
validation; `knowledge_base.db` is never a benchmark fixture.

Create an isolated temporary benchmark database:

```powershell
python scripts\init_agent_benchmark_fixture_db.py `
  --fixture tests\fixtures\agent_benchmark\active_benchmark_synthetic_v1.json `
  --manifest tests\fixtures\agent_benchmark\active_benchmark_synthetic_v1.manifest.json `
  --output-db outputs\active_benchmark_fixture.sqlite
```

Run smoke or full evaluation against that exact fixture. Both commands record
the dataset ID, version, hash, and database source in their JSON result.

```powershell
python scripts\run_agent_benchmark.py `
  --fixture tests\fixtures\agent_benchmark\active_benchmark_synthetic_v1.json `
  --fixture-manifest tests\fixtures\agent_benchmark\active_benchmark_synthetic_v1.manifest.json `
  --benchmark-db outputs\active_benchmark_fixture.sqlite `
  --status active --limit 5 --fail-on-failure

python scripts\run_agent_benchmark.py `
  --fixture tests\fixtures\agent_benchmark\active_benchmark_synthetic_v1.json `
  --fixture-manifest tests\fixtures\agent_benchmark\active_benchmark_synthetic_v1.manifest.json `
  --benchmark-db outputs\active_benchmark_fixture.sqlite `
  --status active --fail-on-failure
```

The initializer refuses `knowledge_base.db` and existing paths. A fixture hash,
schema, manifest, or scenario-count mismatch fails closed. A runner result with
zero scenarios is `invalid_run/no_scenarios`, has exit code `2`, and must never
be reported as a passing benchmark.
