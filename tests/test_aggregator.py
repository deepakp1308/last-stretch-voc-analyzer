"""Unit tests for the aggregation and prioritization logic."""

import pytest
from datetime import datetime

from src.aggregator import build_theme_buckets, build_report, _count_churn_signals
from src.models import (
    ChannelSource,
    ClassifiedVOC,
    MRRTier,
    ParsedVOC,
    RawSlackMessage,
    Theme,
)


def _make_classified(
    theme: Theme,
    mrr: float | None,
    is_ra: bool = True,
    is_neg: bool = True,
    user_id: str = "1",
    feedback: str = "test",
) -> ClassifiedVOC:
    raw = RawSlackMessage(
        channel=ChannelSource.REPORTING_FEEDBACK,
        channel_id="C06SW7512P2",
        timestamp="1775928857.0",
        datetime_utc=datetime(2026, 4, 11),
        author="Qualtrics",
        author_id="W017BFA7JKT",
        text="",
    )
    tier = MRRTier.FREE
    if mrr and mrr >= 299:
        tier = MRRTier.HVC
    elif mrr and mrr > 0:
        tier = MRRTier.NON_HVC

    return ClassifiedVOC(
        parsed=ParsedVOC(
            raw_message=raw,
            user_id=user_id,
            mrr=mrr,
            feedback=feedback,
            dedup_key=f"{user_id}:abc",
        ),
        is_ra_related=is_ra,
        is_negative=is_neg,
        mrr_tier=tier,
        theme=theme,
        confidence=0.8,
    )


class TestBuildBuckets:
    def test_groups_by_theme(self):
        vocs = [
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 500, user_id="1"),
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 300, user_id="2"),
            _make_classified(Theme.DATA_ACCURACY, 1000, user_id="3"),
        ]
        buckets = build_theme_buckets(vocs)
        themes = {b.theme for b in buckets}
        assert Theme.EXPORT_FIELDS_STRIPPED in themes
        assert Theme.DATA_ACCURACY in themes

    def test_mrr_aggregation(self):
        vocs = [
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 500, user_id="1"),
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 300, user_id="2"),
        ]
        buckets = build_theme_buckets(vocs)
        export_bucket = next(b for b in buckets if b.theme == Theme.EXPORT_FIELDS_STRIPPED)
        assert export_bucket.total_mrr_exposure == 800
        assert export_bucket.hvc_count == 2
        assert export_bucket.hvc_mrr_exposure == 800

    def test_deduplicates_users_within_bucket(self):
        vocs = [
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 500, user_id="1", feedback="a"),
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 500, user_id="1", feedback="b"),
        ]
        buckets = build_theme_buckets(vocs)
        export_bucket = next(b for b in buckets if b.theme == Theme.EXPORT_FIELDS_STRIPPED)
        assert export_bucket.total_mrr_exposure == 500  # counted once

    def test_excludes_non_ra_negative(self):
        vocs = [
            _make_classified(Theme.MISCELLANEOUS, 500, is_ra=False, user_id="1"),
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 300, user_id="2"),
        ]
        buckets = build_theme_buckets(vocs)
        assert len(buckets) == 1
        assert buckets[0].theme == Theme.EXPORT_FIELDS_STRIPPED

    def test_priority_ordering(self):
        vocs = [
            _make_classified(Theme.DEPRECATED_FEATURES, 100, user_id="1"),
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 5000, user_id="2", feedback="may leave churn"),
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 3000, user_id="3", feedback="switching to competitor churn"),
        ]
        buckets = build_theme_buckets(vocs)
        assert buckets[0].theme == Theme.EXPORT_FIELDS_STRIPPED

    def test_free_tier_handling(self):
        vocs = [
            _make_classified(Theme.DATA_ACCURACY, None, user_id="1"),
            _make_classified(Theme.DATA_ACCURACY, 0, user_id="2"),
        ]
        buckets = build_theme_buckets(vocs)
        b = buckets[0]
        assert b.free_count == 2
        assert b.hvc_count == 0


class TestChurnSignals:
    def test_detects_churn_keywords(self):
        vocs = [
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 500, feedback="We may leave the platform"),
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 300, feedback="Everything is fine"),
        ]
        assert _count_churn_signals(vocs) == 1

    def test_detects_p0_criticality(self):
        v = _make_classified(Theme.DATA_ACCURACY, 5000)
        v.parsed.criticality = "P0 (Immediate) – High churn risk"
        assert _count_churn_signals([v]) == 1


class TestBuildReport:
    def test_report_structure(self):
        vocs = [
            _make_classified(Theme.EXPORT_FIELDS_STRIPPED, 500, user_id="1"),
            _make_classified(Theme.MISCELLANEOUS, 100, is_ra=False, user_id="2"),
        ]
        report = build_report(
            vocs,
            date_start=datetime(2026, 3, 24),
            date_end=datetime(2026, 4, 12),
            raw_count=10,
            deduped_count=5,
        )
        assert report.total_raw_messages == 10
        assert report.total_deduped == 5
        assert report.total_ra_negative == 1
        assert report.total_miscellaneous == 1
        assert len(report.theme_buckets) >= 1
        assert report.overall_mrr_exposure == 500
