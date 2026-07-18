from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = PROJECT_ROOT / "docs"


def test_required_governance_documents_exist():
    required = (
        PROJECT_ROOT / "AGENTS.md",
        DOCS_ROOT / "index.md",
        DOCS_ROOT / "PROJECT_CHARTER.md",
        DOCS_ROOT / "architecture-overview.md",
        DOCS_ROOT / "module-index.md",
        DOCS_ROOT / "adr" / "README.md",
    )

    missing = [str(path.relative_to(PROJECT_ROOT)) for path in required if not path.is_file()]

    assert not missing, f"Missing required governance documents: {missing}"


def test_project_agent_instructions_require_governance_reading():
    content = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for required_reference in (
        "docs/index.md",
        "docs/PROJECT_CHARTER.md",
        "docs/architecture-overview.md",
        "docs/module-index.md",
    ):
        assert required_reference in content


def test_project_agent_instructions_require_real_dataset_change_gate():
    instructions = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    accuracy_contract = (
        DOCS_ROOT / "research" / "real-customer-service-accuracy-evaluation.md"
    ).read_text(encoding="utf-8")

    for required_term in (
        "Real-dataset change gate",
        "before-change baseline",
        "real_accuracy=null",
        "synthetic fixtures",
    ):
        assert required_term in instructions

    for required_term in (
        "Mandatory Before/After Change Gate",
        "dataset content hash",
        "optimization_unverified",
        "p50/p95 latency",
    ):
        assert required_term in accuracy_contract


def test_document_index_has_no_missing_or_unindexed_markdown_files():
    index = (DOCS_ROOT / "index.md").read_text(encoding="utf-8")
    referenced_paths = set(re.findall(r"docs/[A-Za-z0-9_./-]+\.md", index))

    missing_references = [
        path for path in sorted(referenced_paths) if not (PROJECT_ROOT / Path(path)).is_file()
    ]
    assert not missing_references, f"Index contains missing documents: {missing_references}"

    unindexed = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if relative == "docs/index.md":
            continue
        if relative not in index:
            unindexed.append(relative)

    assert not unindexed, f"Durable documents missing from docs/index.md: {unindexed}"
