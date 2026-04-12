"""Unit tests for the VOC message parser."""

import pytest
from datetime import datetime
from src.parser import (
    parse_message,
    parse_all,
    deduplicate,
    _extract_mrr,
    _extract_csat,
    _extract_prs,
    _extract_feedback,
    _extract_user_id,
)
from src.models import ChannelSource, RawSlackMessage


def _make_raw(text: str, channel: ChannelSource = ChannelSource.REPORTING_FEEDBACK) -> RawSlackMessage:
    return RawSlackMessage(
        channel=channel,
        channel_id="C06SW7512P2",
        timestamp="1775928857.696529",
        datetime_utc=datetime(2026, 4, 11, 17, 34, 17),
        author="Qualtrics",
        author_id="W017BFA7JKT",
        text=text,
    )


class TestExtractMRR:
    def test_standard_format(self):
        assert _extract_mrr("*MRR:*  949") == 949.0

    def test_with_dollar_sign(self):
        assert _extract_mrr("*MRR:* $1,440") == 1440.0

    def test_null_mrr(self):
        assert _extract_mrr("*MRR:*  null") is None

    def test_zero_mrr(self):
        assert _extract_mrr("*MRR:*  0") is None

    def test_newline_format(self):
        assert _extract_mrr("*MRR*\n57000") == 57000.0

    def test_hvc_feedback_format(self):
        assert _extract_mrr("*MRR:* 576") == 576.0


class TestExtractCSAT:
    def test_terrible(self):
        assert _extract_csat("*CSAT* Terrible") == "Terrible"

    def test_with_colon(self):
        assert _extract_csat("*CSAT:* Good") == "Good"

    def test_spanish(self):
        assert _extract_csat("*CSAT:* Medianamente satisfecho") == "Medianamente satisfecho"


class TestExtractPRS:
    def test_zero(self):
        assert _extract_prs("*PRS:* 0") == 0

    def test_ten(self):
        assert _extract_prs("*PRS:* 10") == 10

    def test_absent(self):
        assert _extract_prs("No PRS here") is None


class TestExtractUserID:
    def test_standard(self):
        assert _extract_user_id("*User ID:* 59273049") == "59273049"

    def test_customer_uid(self):
        assert _extract_user_id("*Customer UID*\n7165809") == "7165809"

    def test_url_embedded(self):
        assert _extract_user_id("user_id=77161842") == "77161842"


class TestExtractFeedback:
    def test_basic_extraction(self):
        text = "*Feedback:* This is my feedback.\n\n*Fullstory:* https://example.com"
        fb = _extract_feedback(text)
        assert "This is my feedback" in fb
        assert "Fullstory" not in fb

    def test_multiline_feedback(self):
        text = "*Feedback:* Line 1\nLine 2\nLine 3\n\n*Fullstory:* link"
        fb = _extract_feedback(text)
        assert "Line 1" in fb
        assert "Line 2" in fb


class TestParseMessage:
    def test_qualtrics_badge(self):
        text = (
            "*New Survey Response from the In-App Feedback Badge*\n\n"
            "*MRR:*  949\n*Plan:* Paid \n*User ID:* 59273049\n"
            "*CSAT* Terrible\n*Feedback:* The Bounced reports are broken.\n"
            "*Fullstory:* https://example.com"
        )
        voc = parse_message(_make_raw(text))
        assert voc.mrr == 949.0
        assert voc.user_id == "59273049"
        assert voc.csat == "Terrible"
        assert "Bounced reports" in voc.feedback

    def test_hvc_escalation(self):
        text = (
            ":postal_horn: *New HVC Product Feedback Received*\n\n"
            "*Customer Name*\nWorld Central Kitchen\n"
            "*Impacted Product*\nAnalytics\n"
            "*Criticality (if specific customer request)*\n"
            "P0 (Immediate) – High churn risk\n"
            "*Customer UID*\n7165809\n*MRR*\n6664"
        )
        voc = parse_message(_make_raw(text, ChannelSource.HVC_ESCALATIONS))
        assert voc.mrr == 6664.0
        assert voc.customer_name == "World Central Kitchen"
        assert voc.user_id == "7165809"
        assert "P0" in (voc.criticality or "")


class TestDedup:
    def test_removes_exact_duplicates(self):
        text = "*User ID:* 100\n*Feedback:* Same feedback here"
        vocs = parse_all([
            _make_raw(text, ChannelSource.REPORTING_FEEDBACK),
            _make_raw(text, ChannelSource.HVC_FEEDBACK),
        ])
        deduped = deduplicate(vocs)
        assert len(deduped) == 1

    def test_keeps_different_feedback(self):
        vocs = parse_all([
            _make_raw("*User ID:* 100\n*Feedback:* Feedback one about exports"),
            _make_raw("*User ID:* 100\n*Feedback:* Feedback two about dashboards"),
        ])
        deduped = deduplicate(vocs)
        assert len(deduped) == 2

    def test_keeps_different_users(self):
        vocs = parse_all([
            _make_raw("*User ID:* 100\n*Feedback:* Same feedback text here"),
            _make_raw("*User ID:* 200\n*Feedback:* Same feedback text here"),
        ])
        deduped = deduplicate(vocs)
        assert len(deduped) == 2
