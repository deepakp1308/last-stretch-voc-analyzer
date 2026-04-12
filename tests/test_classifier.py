"""Unit tests for the VOC classifier."""

import json
import pytest
from datetime import datetime
from pathlib import Path

from src.classifier import classify_voc, classify_all, _is_ra_related, _is_negative, _assign_theme
from src.models import (
    ChannelSource,
    ClassifiedVOC,
    MRRTier,
    ParsedVOC,
    RawSlackMessage,
    Theme,
)
from src.parser import parse_message


FIXTURES = Path(__file__).parent / "fixtures" / "sample_vocs.json"


def _make_parsed(
    feedback: str,
    mrr: float | None = None,
    csat: str | None = None,
    prs: int | None = None,
    impacted_product: str | None = None,
    criticality: str | None = None,
) -> ParsedVOC:
    raw = RawSlackMessage(
        channel=ChannelSource.REPORTING_FEEDBACK,
        channel_id="C06SW7512P2",
        timestamp="1775928857.0",
        datetime_utc=datetime(2026, 4, 11),
        author="Qualtrics",
        author_id="W017BFA7JKT",
        text="",
    )
    return ParsedVOC(
        raw_message=raw,
        user_id="12345",
        mrr=mrr,
        csat=csat,
        prs=prs,
        feedback=feedback,
        impacted_product=impacted_product,
        criticality=criticality,
        dedup_key="12345:abc",
    )


class TestRARelevance:
    def test_export_fields_is_ra(self):
        v = _make_parsed("The export reports no longer include vital contact information")
        assert _is_ra_related(v) is True

    def test_bounce_report_is_ra(self):
        v = _make_parsed("Bounced report file no longer contains the Bounce reason")
        assert _is_ra_related(v) is True

    def test_analytics_product_is_ra(self):
        v = _make_parsed("Number discrepancy", impacted_product="Analytics")
        assert _is_ra_related(v) is True

    def test_sms_compliance_is_not_ra(self):
        v = _make_parsed("Add cease to SMS compliance keywords", impacted_product="Messaging (SMS, RCS, WhatsApp)")
        assert _is_ra_related(v) is False

    def test_billing_is_not_ra(self):
        v = _make_parsed("I want a refund for this billing charge")
        assert _is_ra_related(v) is False

    def test_positive_feedback_still_ra(self):
        v = _make_parsed("Better reporting and analytics needed")
        assert _is_ra_related(v) is True


class TestSentiment:
    def test_terrible_is_negative(self):
        v = _make_parsed("Something", csat="Terrible")
        assert _is_negative(v) is True

    def test_poor_is_negative(self):
        v = _make_parsed("Something", csat="Poor")
        assert _is_negative(v) is True

    def test_good_is_not_negative(self):
        v = _make_parsed("Something generic", csat="Good")
        assert _is_negative(v) is False

    def test_good_with_strong_neg_words(self):
        v = _make_parsed("This is destroying how I track KPIs", csat="Good")
        assert _is_negative(v) is True

    def test_prs_zero_is_negative(self):
        v = _make_parsed("Something", prs=0)
        assert _is_negative(v) is True

    def test_prs_ten_is_not_negative(self):
        v = _make_parsed("All good", prs=10)
        assert _is_negative(v) is False

    def test_p0_criticality_is_negative(self):
        v = _make_parsed("Issue", criticality="P0 (Immediate) – High churn risk")
        assert _is_negative(v) is True

    def test_average_with_missing_keyword(self):
        v = _make_parsed("The export is missing critical fields", csat="Average")
        assert _is_negative(v) is True


class TestMRRTier:
    def test_hvc(self):
        v = _make_parsed("x", mrr=949)
        c = classify_voc(v)
        assert c.mrr_tier == MRRTier.HVC

    def test_non_hvc(self):
        v = _make_parsed("x", mrr=100)
        c = classify_voc(v)
        assert c.mrr_tier == MRRTier.NON_HVC

    def test_free(self):
        v = _make_parsed("x", mrr=None)
        c = classify_voc(v)
        assert c.mrr_tier == MRRTier.FREE

    def test_boundary_299(self):
        v = _make_parsed("x", mrr=299)
        c = classify_voc(v)
        assert c.mrr_tier == MRRTier.HVC


class TestThemeAssignment:
    def test_export_theme(self):
        v = _make_parsed("The export no longer contains audience fields and removed the company column")
        theme, conf = _assign_theme(v)
        assert theme == Theme.EXPORT_FIELDS_STRIPPED

    def test_data_accuracy_theme(self):
        v = _make_parsed("The metrics show incorrect data with a discrepancy between dashboard and campaign view")
        theme, conf = _assign_theme(v)
        assert theme == Theme.DATA_ACCURACY

    def test_ux_regression_theme(self):
        v = _make_parsed("Too many clicks to get to reports, can't filter by campaign name")
        theme, conf = _assign_theme(v)
        assert theme == Theme.REPORTING_UX_REGRESSION

    def test_bot_mpp_theme(self):
        v = _make_parsed("The Campaign Report includes bots and MPP data, please exclude bot opens")
        theme, conf = _assign_theme(v)
        assert theme == Theme.BOT_MPP_CONTAMINATION

    def test_ab_theme(self):
        v = _make_parsed("A/B test export doesn't include subject line, groups labeled Group A Group B")
        theme, conf = _assign_theme(v)
        assert theme == Theme.AB_MULTIVARIATE


class TestFixtureAccuracy:
    """Run all fixture VOCs through the full pipeline and check expected outcomes."""

    @pytest.fixture
    def fixtures(self):
        with open(FIXTURES) as f:
            return json.load(f)

    def test_all_fixtures_classify_correctly(self, fixtures):
        correct = 0
        total = len(fixtures)

        for fx in fixtures:
            raw = RawSlackMessage(
                channel=ChannelSource.REPORTING_FEEDBACK,
                channel_id="C06SW7512P2",
                timestamp="1775928857.0",
                datetime_utc=datetime(2026, 4, 11),
                author="Qualtrics",
                author_id="W017BFA7JKT",
                text=fx["text"],
            )
            parsed = parse_message(raw)
            classified = classify_voc(parsed)

            ra_ok = classified.is_ra_related == fx["expected_ra"]
            neg_ok = classified.is_negative == fx["expected_negative"]
            tier_ok = classified.mrr_tier.value == fx["expected_mrr_tier"]

            if ra_ok and neg_ok and tier_ok:
                correct += 1
            else:
                details = []
                if not ra_ok:
                    details.append(f"ra={classified.is_ra_related} expected={fx['expected_ra']}")
                if not neg_ok:
                    details.append(f"neg={classified.is_negative} expected={fx['expected_negative']}")
                if not tier_ok:
                    details.append(f"tier={classified.mrr_tier.value} expected={fx['expected_mrr_tier']}")
                print(f"MISMATCH user={parsed.user_id}: {', '.join(details)}")

        accuracy = correct / total
        assert accuracy >= 0.8, f"Fixture accuracy {accuracy:.0%} below 80% threshold ({correct}/{total})"

    def test_theme_accuracy(self, fixtures):
        """Theme assignment is harder -- require >= 70% accuracy."""
        ra_fixtures = [fx for fx in fixtures if fx["expected_ra"] and fx["expected_negative"]]
        correct = 0

        for fx in ra_fixtures:
            raw = RawSlackMessage(
                channel=ChannelSource.REPORTING_FEEDBACK,
                channel_id="C06SW7512P2",
                timestamp="1775928857.0",
                datetime_utc=datetime(2026, 4, 11),
                author="Qualtrics",
                author_id="W017BFA7JKT",
                text=fx["text"],
            )
            parsed = parse_message(raw)
            classified = classify_voc(parsed)
            if classified.theme.value == fx["expected_theme"]:
                correct += 1

        if ra_fixtures:
            accuracy = correct / len(ra_fixtures)
            assert accuracy >= 0.7, f"Theme accuracy {accuracy:.0%} below 70% ({correct}/{len(ra_fixtures)})"
