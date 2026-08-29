# Product Hub Reviewed Fact Bridge Plan

## Goal

Close the exact-identity product-fact context gap without creating a parallel
retriever or changing delivery authority.

## Steps

1. Verify the live Product Hub Agent read contract and fix its response shape in
   an isolated Hub release copy. Keep the live service unchanged during this
   verification.
2. Add tests for an opt-in Copilot client: disabled by default, exact resolved
   identity only, bounded timeout, no title fallback, invalid response rejection,
   and no raw source-detail propagation.
3. Add a narrow Hub fact adapter to the existing Product Context Pack. It emits
   only confirmed/non-conflicting, type-compatible candidates with exact product
   and optional SKU scope.
4. Reuse the existing admission path in tests to prove accepted candidates can
   be normalized while blocked, wrong-scope, pending, conflicted, and high-risk
   rows cannot be admitted.
5. Run focused service tests, static compilation, and a read-only local Hub
   contract probe. Do not claim reply-quality improvement until the Hub release
   and a comparable formal-pipeline evaluation run against an enabled canary.

## Non-Goals

- No Hub database copy, write, migration, vector-store ingestion, Graph change,
  media delivery, automatic send, or live product-title search.
- No product-specific answer text, SKU branch, or test-case exception.
