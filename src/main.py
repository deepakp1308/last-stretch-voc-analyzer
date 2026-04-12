"""Main orchestrator: ingest -> parse -> classify -> evaluate -> publish."""

from __future__ import annotations

import logging
import os
import sys

from openai import OpenAI

from src.aggregator import build_report, build_theme_buckets
from src.classifier import classify_all
from src.config import (
    get_date_range,
    get_notify_user_id,
    get_openai_api_key,
    get_slack_bot_token,
    get_slack_webhook_url,
)
from src.dashboard import generate_dashboard
from src.llm_evaluator import run_evaluation
from src.models import AnalysisReport, ChannelSource
from src.parser import deduplicate, parse_all
from src.slack_notifier import send_slack_notification
from src.slack_reader import SlackReader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DASHBOARD_URL_TEMPLATE = "https://{owner}.github.io/last-stretch-voc-analyzer/"


def run(
    skip_llm: bool = False,
    skip_slack: bool = False,
    output_path: str = "dashboard/index.html",
) -> AnalysisReport:
    """Execute the full analysis pipeline.

    1. Read messages from all 3 Slack channels
    2. Parse into structured VOC records
    3. Deduplicate across channels
    4. Classify: R&A relevance, sentiment, MRR tier, theme
    5. Aggregate into themed buckets with MRR exposure
    6. Run LLM evaluator quality gate (review + correct)
    7. Re-aggregate after corrections
    8. Generate dashboard HTML
    9. Send Slack notification
    """
    date_start, date_end = get_date_range()
    logger.info(f"Analysis window: {date_start:%Y-%m-%d} to {date_end:%Y-%m-%d}")

    # Step 1: Ingest
    logger.info("Step 1/9: Reading Slack channels...")
    reader = SlackReader(get_slack_bot_token())
    all_messages = reader.read_all_channels(date_start, date_end)
    raw_count = sum(len(msgs) for msgs in all_messages.values())
    logger.info(f"  Read {raw_count} raw messages across {len(all_messages)} channels")

    flat_messages = []
    for msgs in all_messages.values():
        flat_messages.extend(msgs)

    # Step 2: Parse
    logger.info("Step 2/9: Parsing messages...")
    parsed = parse_all(flat_messages)
    logger.info(f"  Parsed {len(parsed)} VOC records")

    # Step 3: Deduplicate
    logger.info("Step 3/9: Deduplicating...")
    deduped = deduplicate(parsed)
    logger.info(f"  {len(deduped)} unique VOCs after dedup")

    # Step 4: Classify
    logger.info("Step 4/9: Classifying...")
    classified = classify_all(deduped)
    ra_neg = [v for v in classified if v.is_ra_related and v.is_negative]
    logger.info(f"  {len(ra_neg)} R&A-related negative VOCs identified")

    # Step 5: Initial aggregation
    logger.info("Step 5/9: Aggregating theme buckets...")
    report = build_report(classified, date_start, date_end, raw_count, len(deduped))
    for b in report.theme_buckets:
        logger.info(f"  {b.theme.value}: {len(b.vocs)} VOCs, ${b.total_mrr_exposure:,.0f} MRR")

    # Step 6: LLM Evaluation
    if not skip_llm:
        logger.info("Step 6/9: Running LLM quality gate...")
        try:
            oai = OpenAI(api_key=get_openai_api_key())
            evaluation = run_evaluation(oai, classified, report)
            report.evaluation = evaluation
            logger.info(f"  Evaluation: {'PASSED' if evaluation.passed else 'NEEDS REVIEW'} "
                        f"({evaluation.confidence:.0%}, {evaluation.corrections_made} corrections)")
        except Exception as e:
            logger.warning(f"  LLM evaluation failed (non-blocking): {e}")
    else:
        logger.info("Step 6/9: Skipping LLM evaluation")

    # Step 7: Re-aggregate after corrections
    if report.evaluation and report.evaluation.corrections_made > 0:
        logger.info("Step 7/9: Re-aggregating after LLM corrections...")
        report = build_report(classified, date_start, date_end, raw_count, len(deduped))
        report.evaluation = report.evaluation
    else:
        logger.info("Step 7/9: No corrections to apply, skipping re-aggregation")

    # Step 8: Generate dashboard
    logger.info("Step 8/9: Generating dashboard...")
    path = generate_dashboard(report, output_path)
    logger.info(f"  Dashboard written to {path}")

    # Step 9: Slack notification
    if not skip_slack:
        logger.info("Step 9/9: Sending Slack notification...")
        try:
            gh_owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "dprabhakara")
            dashboard_url = DASHBOARD_URL_TEMPLATE.format(owner=gh_owner)
            send_slack_notification(
                get_slack_webhook_url(),
                report,
                dashboard_url,
                get_notify_user_id(),
            )
        except Exception as e:
            logger.warning(f"  Slack notification failed (non-blocking): {e}")
    else:
        logger.info("Step 9/9: Skipping Slack notification")

    logger.info("Pipeline complete.")
    return report


if __name__ == "__main__":
    skip_llm = "--skip-llm" in sys.argv
    skip_slack = "--skip-slack" in sys.argv
    run(skip_llm=skip_llm, skip_slack=skip_slack)
