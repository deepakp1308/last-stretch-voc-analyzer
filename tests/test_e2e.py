"""End-to-end quality control tests.

These tests simulate the full pipeline with fixture data and validate:
1. Parse -> Classify -> Aggregate pipeline integrity
2. Dashboard generation produces valid HTML
3. Slack notification payload is well-formed
4. Report invariants hold (MRR math, counts, ordering)
"""

import json
import pytest
from datetime import datetime
from pathlib import Path

from src.parser import parse_message, parse_all, deduplicate
from src.classifier import classify_all
from src.aggregator import build_report, build_theme_buckets
from src.dashboard import generate_dashboard
from src.slack_notifier import _build_slack_blocks
from src.models import (
    AnalysisReport,
    ChannelSource,
    EvaluationResult,
    RawSlackMessage,
    Theme,
)


FIXTURES = Path(__file__).parent / "fixtures" / "sample_vocs.json"


def _load_fixtures() -> list[RawSlackMessage]:
    with open(FIXTURES) as f:
        data = json.load(f)
    return [
        RawSlackMessage(
            channel=ChannelSource.REPORTING_FEEDBACK,
            channel_id="C06SW7512P2",
            timestamp=f"177592{i}857.0",
            datetime_utc=datetime(2026, 4, 11, 10 + i),
            author="Qualtrics",
            author_id="W017BFA7JKT",
            text=fx["text"],
        )
        for i, fx in enumerate(data)
    ]


class TestFullPipeline:
    """Run the complete pipeline on fixture data and validate invariants."""

    @pytest.fixture
    def report(self, tmp_path) -> AnalysisReport:
        raw = _load_fixtures()
        parsed = parse_all(raw)
        deduped = deduplicate(parsed)
        classified = classify_all(deduped)
        return build_report(
            classified,
            date_start=datetime(2026, 3, 24),
            date_end=datetime(2026, 4, 12),
            raw_count=len(raw),
            deduped_count=len(deduped),
        )

    def test_pipeline_produces_report(self, report):
        assert isinstance(report, AnalysisReport)
        assert report.total_raw_messages > 0
        assert report.total_deduped > 0

    def test_ra_negative_count_is_plausible(self, report):
        """At least some of our test fixtures should be classified as R&A negative."""
        assert report.total_ra_negative >= 4

    def test_mrr_exposure_is_non_negative(self, report):
        assert report.overall_mrr_exposure >= 0
        for b in report.theme_buckets:
            assert b.total_mrr_exposure >= 0
            assert b.hvc_mrr_exposure >= 0
            assert b.non_hvc_mrr_exposure >= 0

    def test_mrr_math_adds_up(self, report):
        for b in report.theme_buckets:
            assert abs(
                b.total_mrr_exposure - b.hvc_mrr_exposure - b.non_hvc_mrr_exposure
            ) < 0.01, f"MRR doesn't add up for {b.theme.value}"

    def test_counts_are_consistent(self, report):
        for b in report.theme_buckets:
            voc_count = len(b.vocs)
            segment_count = b.hvc_count + b.non_hvc_count + b.free_count
            assert segment_count <= voc_count, (
                f"Segment count {segment_count} > VOC count {voc_count} for {b.theme.value}"
            )

    def test_buckets_are_priority_ordered(self, report):
        scores = [b.priority_score for b in report.theme_buckets]
        assert scores == sorted(scores, reverse=True), "Buckets not in priority order"

    def test_no_miscellaneous_in_themed_buckets(self, report):
        for b in report.theme_buckets:
            assert b.theme != Theme.MISCELLANEOUS


class TestDashboardGeneration:
    def test_generates_valid_html(self, tmp_path):
        raw = _load_fixtures()
        parsed = parse_all(raw)
        classified = classify_all(deduplicate(parsed))
        report = build_report(
            classified,
            datetime(2026, 3, 24),
            datetime(2026, 4, 12),
            len(raw),
            len(parsed),
        )
        report.evaluation = EvaluationResult(
            passed=True, confidence=0.92,
            total_vocs_reviewed=10, corrections_made=1,
            issues_found=["Minor theme adjustment"],
            summary="Evaluation PASSED",
        )
        output = tmp_path / "index.html"
        generate_dashboard(report, str(output))
        html = output.read_text()

        assert "<!DOCTYPE html>" in html
        assert "Last Stretch VOC Analyzer" in html
        assert "PASSED" in html
        assert "$" in html  # MRR values present

    def test_handles_empty_report(self, tmp_path):
        report = AnalysisReport(
            run_date=datetime.now(),
            date_range_start=datetime(2026, 3, 24),
            date_range_end=datetime(2026, 4, 12),
        )
        output = tmp_path / "index.html"
        generate_dashboard(report, str(output))
        assert output.exists()


class TestSlackPayload:
    def test_builds_valid_blocks(self):
        raw = _load_fixtures()
        parsed = parse_all(raw)
        classified = classify_all(deduplicate(parsed))
        report = build_report(
            classified,
            datetime(2026, 3, 24),
            datetime(2026, 4, 12),
            len(raw),
            len(parsed),
        )
        blocks = _build_slack_blocks(report, "https://example.com", "W8FL6URHQ")

        assert len(blocks) > 3
        assert blocks[0]["type"] == "header"
        assert any(b.get("type") == "actions" for b in blocks)

    def test_includes_user_mention(self):
        report = AnalysisReport(
            run_date=datetime.now(),
            date_range_start=datetime(2026, 3, 24),
            date_range_end=datetime(2026, 4, 12),
        )
        blocks = _build_slack_blocks(report, "https://example.com", "W8FL6URHQ")
        text_content = json.dumps(blocks)
        assert "W8FL6URHQ" in text_content
