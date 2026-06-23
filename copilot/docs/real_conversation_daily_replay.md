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
