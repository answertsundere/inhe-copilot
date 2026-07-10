# Document Location Policy

## Decision

`copilot/docs/` is the single authoritative documentation center for the active
customer-service Copilot project.

This does not mean every Markdown file in the workspace should be physically
moved into this directory. A single front door is useful; destroying automatic
discovery and module locality is not.

## Location Rules

| Document kind | Required location | Authority |
|---|---|---|
| Project business charter, architecture, contracts, ADRs, and research | `copilot/docs/` | authoritative |
| Workspace AI instructions | workspace-root `AGENTS.md`, `CLAUDE.md` | automatic entry point |
| Copilot-specific AI instructions | `copilot/AGENTS.md` | automatic project entry point |
| Project overview | `copilot/README.md` | orientation; `copilot/docs/` wins on architecture |
| Deployment instructions | `copilot/deploy/` | module-local operations reference |
| Frontend development instructions | `copilot/frontend/` | module-local development reference |
| Runtime knowledge content | `copilot/knowledge/` | application data, not architecture documentation |
| Test fixture instructions and generated reports | under the owning test directory | test evidence, not current architecture |
| Product-data operating manuals | `product_knowledge/` | data-operations reference |
| Dated acceptance reports | original/archive location | historical snapshot only |
| Generated Obsidian/canvas architecture maps under `客服系统/` | original location | historical visual archive only |
| Third-party repository documentation | inside the third-party repository | excluded from this project index |

## Why Entry Files Stay At The Root

Tools discover `AGENTS.md`, `CLAUDE.md`, and common project `README.md` files by
walking directory boundaries. Moving them into a document archive would make AI
startup behavior less reliable. These files should remain short and point to
`copilot/docs/index.md` for durable project truth.

## Historical Documentation

The following workspace areas contain useful history but are not current sources
of truth:

- workspace-root `docs/`;
- workspace-root acceptance reports named `验收报告*.md`;
- workspace-root `客服系统/` architecture and Obsidian maps;
- generated reports under `copilot/tests/simulation_results/`;
- dated status and delivery reports under `copilot/docs/`.

An AI may use them to understand why a decision was made, but it must verify the
current code and authoritative documents before acting on a historical claim.

## Module-Local References

These remain in place and are discoverable from this policy rather than being
copied into the documentation center:

- `copilot/deploy/DEPLOY_CONFIG.md`
- `copilot/deploy/DEPLOY_INHE.md`
- `copilot/frontend/DESIGN.md`
- `copilot/frontend/README.md`
- `copilot/tests/golden_cases/agent_phase1/README.md`
- `product_knowledge/data_quality_report.md`
- `product_knowledge/聚水潭API数据拉取手册.md`

Copying these files into `copilot/docs/` would create two versions that can drift.

## New Document Rule

Before adding Markdown, classify it:

1. Durable cross-module business or architecture contract: add it under
   `copilot/docs/` and link it from `copilot/docs/index.md`.
2. Module-specific setup or development instruction: keep it beside the module
   and add it to this policy only when other teams need to discover it.
3. Dated run, acceptance, or generated report: store it under an archive/output
   location and never present it as current architecture.
4. Runtime knowledge: store it in the governed knowledge system, not project
   architecture documentation.

Do not create a second architecture index outside `copilot/docs/index.md`.
