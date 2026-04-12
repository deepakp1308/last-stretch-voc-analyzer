"""LLM-based quality gate that evaluates and corrects the VOC analysis
before publishing.

The evaluator:
1. Samples classified VOCs and validates classification accuracy
2. Checks thematic categorization consistency
3. Validates MRR math
4. Proposes corrections for misclassified items
5. Returns a pass/fail verdict with confidence score
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from openai import OpenAI

from src.models import (
    AnalysisReport,
    ClassifiedVOC,
    EvaluationResult,
    Theme,
)

logger = logging.getLogger(__name__)

EVALUATION_SYSTEM_PROMPT = """You are a senior product analytics QA reviewer. Your job is to evaluate
a Voice of Customer (VOC) analysis for accuracy and correctness.

You will receive:
1. A batch of classified VOC records with their assigned attributes
2. Summary aggregation data

For each VOC record, evaluate:
- is_ra_related: Should this be tagged as Reporting & Analytics related?
  R&A topics include: report exports, analytics dashboards, campaign metrics,
  recipient activity, data accuracy, bounce reports, click performance, A/B test
  reporting, custom reports, marketing dashboard, CSV exports with audience fields.
- is_negative: Is the sentiment genuinely negative? (Terrible/Poor CSAT,
  PRS 0-4, explicit frustration, churn signals)
- theme: Is the thematic bucket correct? Available themes:
  - Export Fields Stripped from Reports
  - Report Data Accuracy & Metrics Discrepancies
  - Custom Reports & Dashboard UX Regression
  - A/B & Multivariate Test Reporting Deficiencies
  - Bot / MPP Data Contamination
  - Deprecated Reporting Features
  - Miscellaneous / Others
- mrr_tier: Is HVC ($299+) vs Non-HVC (<$299) vs Free correct?

Return a JSON object with:
{
  "passed": true/false,
  "confidence": 0.0-1.0,
  "issues_found": ["issue description", ...],
  "corrections": [
    {
      "dedup_key": "user:hash",
      "field": "theme|is_ra_related|is_negative",
      "current_value": "...",
      "corrected_value": "...",
      "reason": "..."
    }
  ],
  "summary": "Brief assessment of analysis quality"
}

Pass the analysis if accuracy is >= 85%. Be strict but fair."""

AGGREGATION_CHECK_PROMPT = """You are a data validation specialist. Check these aggregation numbers
for the VOC analysis report.

For each theme bucket, verify:
1. VOC count matches the listed VOCs
2. MRR exposure math is correct (sum of unique customer MRRs)
3. HVC count matches customers with MRR >= $299
4. Priority ordering makes sense given MRR exposure, volume, and churn signals

Return JSON:
{
  "math_correct": true/false,
  "ordering_correct": true/false,
  "issues": ["description", ...],
  "suggested_reorder": ["Theme1", "Theme2", ...] or null
}"""


def _sample_vocs(classified: list[ClassifiedVOC], max_samples: int = 30) -> list[ClassifiedVOC]:
    """Sample VOCs for LLM review, biasing toward edge cases."""
    ra_neg = [v for v in classified if v.is_ra_related and v.is_negative]
    ra_pos = [v for v in classified if v.is_ra_related and not v.is_negative]
    misc_neg = [v for v in classified if not v.is_ra_related and v.is_negative]
    low_conf = [v for v in classified if v.confidence < 0.6]

    sample: list[ClassifiedVOC] = []
    for pool in [low_conf, ra_pos, misc_neg, ra_neg]:
        remaining = max_samples - len(sample)
        if remaining <= 0:
            break
        take = min(len(pool), max(remaining // 2, 5))
        sample.extend(pool[:take])

    if len(sample) < max_samples:
        for v in classified:
            if v not in sample:
                sample.append(v)
                if len(sample) >= max_samples:
                    break

    return sample[:max_samples]


def _voc_to_review_dict(v: ClassifiedVOC) -> dict:
    return {
        "dedup_key": v.parsed.dedup_key,
        "user_id": v.parsed.user_id,
        "mrr": v.parsed.mrr,
        "csat": v.parsed.csat,
        "prs": v.parsed.prs,
        "feedback_preview": v.parsed.feedback[:300],
        "is_ra_related": v.is_ra_related,
        "is_negative": v.is_negative,
        "theme": v.theme.value,
        "mrr_tier": v.mrr_tier.value,
        "confidence": v.confidence,
    }


def _report_to_summary_dict(report: AnalysisReport) -> dict:
    buckets = []
    for b in report.theme_buckets:
        buckets.append({
            "theme": b.theme.value,
            "voc_count": len(b.vocs),
            "total_mrr": b.total_mrr_exposure,
            "hvc_mrr": b.hvc_mrr_exposure,
            "hvc_count": b.hvc_count,
            "non_hvc_count": b.non_hvc_count,
            "churn_signals": b.churn_signals,
            "priority_score": b.priority_score,
        })
    return {
        "total_raw": report.total_raw_messages,
        "total_deduped": report.total_deduped,
        "total_ra_negative": report.total_ra_negative,
        "overall_mrr_exposure": report.overall_mrr_exposure,
        "buckets": buckets,
    }


def evaluate_classifications(
    client: OpenAI,
    classified: list[ClassifiedVOC],
    model: str = "gpt-4o",
) -> tuple[list[dict], float]:
    """Have the LLM review a sample of classifications.

    Returns (corrections, confidence).
    """
    sample = _sample_vocs(classified)
    review_batch = [_voc_to_review_dict(v) for v in sample]

    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(review_batch, indent=2)},
        ],
        temperature=0.1,
    )

    result = json.loads(response.choices[0].message.content)
    corrections = result.get("corrections", [])
    confidence = result.get("confidence", 0.5)
    return corrections, confidence


def evaluate_aggregation(
    client: OpenAI,
    report: AnalysisReport,
    model: str = "gpt-4o",
) -> dict:
    """Have the LLM validate the aggregation math and priority ordering."""
    summary = _report_to_summary_dict(report)

    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": AGGREGATION_CHECK_PROMPT},
            {"role": "user", "content": json.dumps(summary, indent=2)},
        ],
        temperature=0.1,
    )

    return json.loads(response.choices[0].message.content)


def apply_corrections(
    classified: list[ClassifiedVOC],
    corrections: list[dict],
) -> int:
    """Apply LLM-suggested corrections to the classified VOCs.

    Returns the count of corrections applied.
    """
    key_map = {v.parsed.dedup_key: v for v in classified}
    applied = 0

    for c in corrections:
        key = c.get("dedup_key", "")
        voc = key_map.get(key)
        if not voc:
            continue

        field = c.get("field", "")
        new_val = c.get("corrected_value")

        if field == "is_ra_related" and isinstance(new_val, bool):
            voc.is_ra_related = new_val
            applied += 1
        elif field == "is_negative" and isinstance(new_val, bool):
            voc.is_negative = new_val
            applied += 1
        elif field == "theme" and isinstance(new_val, str):
            try:
                voc.theme = Theme(new_val)
                applied += 1
            except ValueError:
                logger.warning(f"Invalid theme correction: {new_val}")

    return applied


def run_evaluation(
    client: OpenAI,
    classified: list[ClassifiedVOC],
    report: AnalysisReport,
    model: str = "gpt-4o",
    max_retries: int = 2,
) -> EvaluationResult:
    """Full evaluation pipeline: classify review -> corrections -> aggregation check.

    Retries up to max_retries times if corrections are needed.
    """
    total_corrections = 0
    all_issues: list[str] = []
    confidence = 0.0

    for attempt in range(max_retries + 1):
        logger.info(f"Evaluation pass {attempt + 1}/{max_retries + 1}")

        corrections, confidence = evaluate_classifications(
            client, classified, model
        )

        if corrections:
            applied = apply_corrections(classified, corrections)
            total_corrections += applied
            all_issues.extend(
                f"[Pass {attempt+1}] {c.get('reason', 'no reason')}"
                for c in corrections
            )
            logger.info(f"Applied {applied} corrections in pass {attempt + 1}")
        else:
            logger.info(f"No corrections needed in pass {attempt + 1}")
            break

    agg_check = evaluate_aggregation(client, report, model)
    if not agg_check.get("math_correct", True):
        all_issues.extend(agg_check.get("issues", []))
    if not agg_check.get("ordering_correct", True):
        all_issues.append("Priority ordering may need adjustment")

    passed = confidence >= 0.85 and total_corrections <= 3

    return EvaluationResult(
        passed=passed,
        confidence=confidence,
        total_vocs_reviewed=min(len(classified), 30),
        corrections_made=total_corrections,
        issues_found=all_issues,
        corrections=[],
        summary=(
            f"Evaluation {'PASSED' if passed else 'NEEDS REVIEW'} with "
            f"{confidence:.0%} confidence. {total_corrections} corrections applied "
            f"across {len(all_issues)} issues found."
        ),
    )
