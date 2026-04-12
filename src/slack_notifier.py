"""Send analysis results to Slack via webhook."""

from __future__ import annotations

import json
import logging
from urllib.request import Request, urlopen

from src.models import AnalysisReport

logger = logging.getLogger(__name__)


def _build_slack_blocks(report: AnalysisReport, dashboard_url: str, notify_user: str) -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Last Stretch VOC Analysis — Daily Report",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"<@{notify_user}> — here's your daily R&A VOC analysis.\n\n"
                    f"*Date range:* {report.date_range_start:%b %d} — {report.date_range_end:%b %d, %Y}\n"
                    f"*Total VOCs scanned:* {report.total_raw_messages} raw → {report.total_deduped} deduped\n"
                    f"*R&A-related negative VOCs:* *{report.total_ra_negative}*\n"
                    f"*Overall MRR exposure:* *${report.overall_mrr_exposure:,.0f}*"
                ),
            },
        },
        {"type": "divider"},
    ]

    for i, bucket in enumerate(report.theme_buckets):
        emoji = ["🔴", "🟠", "🟡", "🟢", "🔵", "⚪"][min(i, 5)]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{emoji} *P{i+1}: {bucket.theme.value}*\n"
                    f"VOCs: {len(bucket.vocs)} · "
                    f"MRR: ${bucket.total_mrr_exposure:,.0f} · "
                    f"HVC: {bucket.hvc_count} (${bucket.hvc_mrr_exposure:,.0f}) · "
                    f"Churn signals: {bucket.churn_signals}"
                ),
            },
        })

    eval_status = "N/A"
    if report.evaluation:
        ev = report.evaluation
        eval_status = f"{'✅ PASSED' if ev.passed else '⚠️ NEEDS REVIEW'} ({ev.confidence:.0%} confidence, {ev.corrections_made} corrections)"

    blocks.extend([
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*LLM Quality Gate:* {eval_status}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Full Dashboard"},
                    "url": dashboard_url,
                    "style": "primary",
                }
            ],
        },
    ])

    return blocks


def send_slack_notification(
    webhook_url: str,
    report: AnalysisReport,
    dashboard_url: str,
    notify_user: str,
) -> bool:
    blocks = _build_slack_blocks(report, dashboard_url, notify_user)
    payload = json.dumps({"blocks": blocks}).encode("utf-8")

    req = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req) as resp:
            if resp.status == 200:
                logger.info("Slack notification sent successfully")
                return True
            logger.warning(f"Slack webhook returned status {resp.status}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False
