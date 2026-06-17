"""Export knowledge rows that contain risky convenience claims.

This is a read-only quality helper. It does not update the knowledge base.

Usage:
    python scripts/knowledge/export_risky_claims.py
    python scripts/knowledge/export_risky_claims.py --db data/knowledge_base.db --out data/rag_risky_claims_report.csv
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


RISKY_PHRASES = (
    "\u5b89\u88c5\u5f88\u65b9\u4fbf",
    "\u5b89\u88c5\u975e\u5e38\u65b9\u4fbf",
    "\u5b89\u88c5\u5f88\u7b80\u5355",
    "\u5b89\u88c5\u7b80\u5355",
    "\u64cd\u4f5c\u5f88\u7b80\u5355",
    "\u5f88\u5bb9\u6613\u5b89\u88c5",
    "\u8f7b\u677e\u5b89\u88c5",
    "\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177",
    "\u65e0\u9700\u989d\u5916\u5de5\u5177",
    "\u4e00\u822c15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5",
    "15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5",
)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def _matched_phrases(text: str) -> list[str]:
    return [phrase for phrase in RISKY_PHRASES if phrase in (text or "")]


def _scan_knowledge_entries(conn: sqlite3.Connection) -> list[dict]:
    if not _has_table(conn, "knowledge_entries"):
        return []
    rows = conn.execute(
        """
        SELECT id, source_type, title, content, status, risk_level, fact_type,
               auto_reply_allowed, human_review_required, source_sheet, row_number
        FROM knowledge_entries
        """
    ).fetchall()
    findings = []
    for row in rows:
        text = " ".join(str(row[key] or "") for key in ("title", "content"))
        matches = _matched_phrases(text)
        if matches:
            findings.append({
                "table": "knowledge_entries",
                "id": row["id"],
                "source_type": row["source_type"] or "",
                "title": row["title"] or "",
                "status": row["status"] or "",
                "risk_level": row["risk_level"] or "",
                "fact_type": row["fact_type"] or "",
                "auto_reply_allowed": row["auto_reply_allowed"],
                "human_review_required": row["human_review_required"],
                "source_sheet": row["source_sheet"] or "",
                "row_number": row["row_number"] or "",
                "matched_phrases": "\uff1b".join(matches),
                "suggested_action": "\u6539\u4e3a\u201c\u53c2\u8003\u8bf4\u660e\u4e66/\u5b89\u88c5\u89c6\u9891\u6309\u6b65\u9aa4\u64cd\u4f5c\uff0c\u5177\u4f53\u4ee5\u5b9e\u9645\u914d\u4ef6\u548c\u9875\u9762\u4e3a\u51c6\u201d",
            })
    return findings


def _scan_kb_qa(conn: sqlite3.Connection) -> list[dict]:
    if not _has_table(conn, "kb_qa"):
        return []
    rows = conn.execute(
        """
        SELECT id, source_type, question, answer, status, risk_level,
               auto_reply, human_review, import_batch_id
        FROM kb_qa
        """
    ).fetchall()
    findings = []
    for row in rows:
        text = " ".join(str(row[key] or "") for key in ("question", "answer"))
        matches = _matched_phrases(text)
        if matches:
            findings.append({
                "table": "kb_qa",
                "id": row["id"],
                "source_type": row["source_type"] or "faq",
                "title": row["question"] or "",
                "status": row["status"] or "",
                "risk_level": row["risk_level"] or "",
                "fact_type": "",
                "auto_reply_allowed": row["auto_reply"],
                "human_review_required": row["human_review"],
                "source_sheet": row["import_batch_id"] or "",
                "row_number": row["id"],
                "matched_phrases": "\uff1b".join(matches),
                "suggested_action": "\u6539\u4e3a\u201c\u53c2\u8003\u8bf4\u660e\u4e66/\u5b89\u88c5\u89c6\u9891\u6309\u6b65\u9aa4\u64cd\u4f5c\uff0c\u5177\u4f53\u4ee5\u5b9e\u9645\u914d\u4ef6\u548c\u9875\u9762\u4e3a\u51c6\u201d",
            })
    return findings


def export_report(db_path: Path, out_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        findings = _scan_knowledge_entries(conn) + _scan_kb_qa(conn)
    finally:
        conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "table", "id", "source_type", "title", "status", "risk_level",
        "fact_type", "auto_reply_allowed", "human_review_required",
        "source_sheet", "row_number", "matched_phrases", "suggested_action",
    ]
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(findings)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/knowledge_base.db")
    parser.add_argument("--out", default="data/rag_risky_claims_report.csv")
    args = parser.parse_args()

    findings = export_report(Path(args.db), Path(args.out))
    print(f"exported={len(findings)} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
