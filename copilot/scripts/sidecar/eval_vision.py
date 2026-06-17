from __future__ import annotations

"""Batch evaluation of VLM chat extraction against labeled screenshots.

Usage:
    python scripts/sidecar/eval_vision.py --screenshots-dir data/sidecar/eval_screenshots --provider mock

Screenshot directory should contain:
  - *.png or *.jpg files (the screenshots)
  - A labels.json with ground truth:
    {
      "screenshot_name.png": {
        "latest_customer_message": "...",
        "latest_agent_message": "...",
        "messages": [{"role": "customer", "text": "..."}, ...]
      }
    }
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sidecar.config import SidecarConfig
from scripts.sidecar.vlm_client import call_vlm
from scripts.sidecar.vision_eval import VisionEvalRecord, VisionEvalTimer, append_eval_record

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_labels(labels_path: Path) -> dict[str, Any]:
    if not labels_path.exists():
        logger.warning("labels.json not found at %s", labels_path)
        return {}
    with open(labels_path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_screenshot(
    image_path: Path,
    label: dict[str, Any] | None,
    config: SidecarConfig,
) -> dict[str, Any]:
    image_data = image_path.read_bytes()
    timer = VisionEvalTimer()
    timer.start()

    result = call_vlm(image_data, config)
    duration_ms = timer.elapsed_ms()

    predicted_customer = result.get("latest_customer_message", "")
    predicted_agent = result.get("latest_agent_message", "")
    predicted_messages = result.get("messages", [])

    metrics: dict[str, Any] = {
        "file": image_path.name,
        "provider": config.vision_provider,
        "model": config.vision_model,
        "duration_ms": duration_ms,
        "json_parse_success": result.get("success", False),
        "confidence": result.get("overall_confidence", 0.0),
        "predicted_customer_message": predicted_customer,
        "predicted_agent_message": predicted_agent,
        "predicted_messages_count": len(predicted_messages),
        "needs_manual_confirm": True,
        "warnings": result.get("warnings", []),
    }

    if label:
        expected_customer = label.get("latest_customer_message", "")
        expected_agent = label.get("latest_agent_message", "")
        expected_messages = label.get("messages", [])

        customer_match = predicted_customer.strip() == expected_customer.strip()
        agent_match = predicted_agent.strip() == expected_agent.strip()

        metrics["expected_customer_message"] = expected_customer
        metrics["expected_agent_message"] = expected_agent
        metrics["customer_exact_match"] = customer_match
        metrics["agent_exact_match"] = agent_match
        metrics["expected_messages_count"] = len(expected_messages)

        role_correct = 0
        role_total = 0
        for pred_msg in predicted_messages:
            for exp_msg in expected_messages:
                if pred_msg.get("text", "").strip() == exp_msg.get("text", "").strip():
                    role_total += 1
                    if pred_msg.get("role") == exp_msg.get("role"):
                        role_correct += 1
                    break
        metrics["role_accuracy"] = role_correct / max(role_total, 1)
        metrics["role_total"] = role_total
        metrics["role_correct"] = role_correct

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="VLM Vision Eval")
    parser.add_argument("--screenshots-dir", required=True)
    parser.add_argument("--provider", default="mock",
                        choices=["mock", "external_openai_compatible", "local_openai_compatible"])
    parser.add_argument("--model", default="qwen2.5-vl-7b-instruct")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    config = SidecarConfig(
        vision_provider=args.provider,
        vision_model=args.model,
        vision_base_url=args.base_url,
        vision_api_key=args.api_key,
    )

    screenshots_dir = Path(args.screenshots_dir)
    if not screenshots_dir.exists():
        logger.error("screenshots dir not found: %s", screenshots_dir)
        sys.exit(1)

    labels = load_labels(screenshots_dir / "labels.json")

    image_files = sorted(
        p for p in screenshots_dir.iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg")
    )

    if not image_files:
        logger.error("no images found in %s", screenshots_dir)
        sys.exit(1)

    logger.info("evaluating %d screenshots with provider=%s model=%s", len(image_files), args.provider, args.model)

    all_metrics: list[dict[str, Any]] = []
    for image_path in image_files:
        label = labels.get(image_path.name)
        metrics = evaluate_screenshot(image_path, label, config)
        all_metrics.append(metrics)
        logger.info(
            "%s: customer_match=%s agent_match=%s duration=%dms confidence=%.2f",
            image_path.name,
            metrics.get("customer_exact_match", "N/A"),
            metrics.get("agent_exact_match", "N/A"),
            metrics["duration_ms"],
            metrics["confidence"],
        )

    summary = compute_summary(all_metrics)
    logger.info("=== SUMMARY ===")
    logger.info("total: %d", summary["total"])
    logger.info("json_parse_success_rate: %.2f%%", summary["json_parse_success_rate"])
    if "customer_exact_match_rate" in summary:
        logger.info("customer_exact_match_rate: %.2f%%", summary["customer_exact_match_rate"])
        logger.info("agent_exact_match_rate: %.2f%%", summary["agent_exact_match_rate"])
        logger.info("role_accuracy: %.2f%%", summary["role_accuracy"])
    logger.info("avg_duration_ms: %.0f", summary["avg_duration_ms"])
    logger.info("avg_confidence: %.2f", summary["avg_confidence"])

    output_path = args.output or str(screenshots_dir / "eval_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "details": all_metrics}, f, ensure_ascii=False, indent=2)
    logger.info("results saved to %s", output_path)


def compute_summary(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(metrics)
    if total == 0:
        return {"total": 0}

    json_ok = sum(1 for m in metrics if m.get("json_parse_success"))
    durations = [m.get("duration_ms", 0) for m in metrics]
    confidences = [m.get("confidence", 0.0) for m in metrics]

    summary: dict[str, Any] = {
        "total": total,
        "json_parse_success_rate": json_ok / total * 100,
        "avg_duration_ms": sum(durations) / total,
        "avg_confidence": sum(confidences) / total,
        "json_parse_failures": total - json_ok,
    }

    has_labels = any("customer_exact_match" in m for m in metrics)
    if has_labels:
        customer_matches = [m for m in metrics if m.get("customer_exact_match")]
        agent_matches = [m for m in metrics if m.get("agent_exact_match")]
        role_accuracies = [m.get("role_accuracy", 0.0) for m in metrics if "role_accuracy" in m]

        labeled = [m for m in metrics if "customer_exact_match" in m]
        labeled_count = len(labeled)

        summary["labeled_count"] = labeled_count
        summary["customer_exact_match_rate"] = len(customer_matches) / max(labeled_count, 1) * 100
        summary["agent_exact_match_rate"] = len(agent_matches) / max(labeled_count, 1) * 100
        summary["role_accuracy"] = sum(role_accuracies) / max(len(role_accuracies), 1) * 100

    return summary


if __name__ == "__main__":
    main()
