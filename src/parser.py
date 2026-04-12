"""Parse raw Slack messages into structured VOC records."""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from src.models import ChannelSource, ParsedVOC, RawSlackMessage


def _extract_field(text: str, label: str) -> Optional[str]:
    """Extract a labeled field value from structured Slack message text."""
    patterns = [
        rf"\*{re.escape(label)}\*[:\s]*\s*(.+?)(?:\n|\*|$)",
        rf"\*{re.escape(label)}:?\*\s*(.+?)(?:\n|$)",
        rf"{re.escape(label)}:\s*(.+?)(?:\n|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().strip("*").strip()
            if val and val.lower() not in ("null", "n/a", "na", ""):
                return val
    return None


def _extract_mrr(text: str) -> Optional[float]:
    """Extract MRR value from text, handling multiple formats."""
    patterns = [
        r"\*MRR:?\*\s*\$?([\d,]+(?:\.\d+)?)",
        r"\*MRR\*\s*\n?\s*\$?([\d,]+(?:\.\d+)?)",
        r"MRR:\s*\$?([\d,]+(?:\.\d+)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).replace(",", "")
            try:
                mrr = float(val)
                return mrr if mrr > 0 else None
            except ValueError:
                continue
    return None


def _extract_csat(text: str) -> Optional[str]:
    """Extract CSAT rating from text."""
    patterns = [
        r"\*CSAT:?\*\s*(.+?)(?:\n|$)",
        r"\*CSAT\*\s+(\w+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().strip("*").strip()
            if val and val.lower() not in ("null", ""):
                return val
    return None


def _extract_prs(text: str) -> Optional[int]:
    """Extract PRS (Product Recommendation Score) value."""
    m = re.search(r"\*PRS:?\*\s*(\d+)", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _extract_feedback(text: str) -> str:
    """Extract the feedback body text."""
    patterns = [
        r"\*Feedback:?\*\s*(.+?)(?:\n\*(?:Fullstory|FS Session|CC\*|Supportive)|_+|---+|\Z)",
        r"\*Feedback:?\*\s*(.+?)(?:\n\n|\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            val = m.group(1).strip()
            val = re.sub(r"<https?://[^|>]+\|?[^>]*>", "", val).strip()
            if len(val) > 5:
                return val
    return text[:500] if len(text) > 20 else ""


def _extract_user_id(text: str) -> Optional[str]:
    """Extract user/customer UID."""
    patterns = [
        r"\*(?:User ID|Customer UID):?\*\s*(\d+)",
        r"user_id=(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _extract_customer_name(text: str) -> Optional[str]:
    return _extract_field(text, "Customer Name")


def _extract_criticality(text: str) -> Optional[str]:
    return _extract_field(text, "Criticality (if specific customer request)")


def _extract_impacted_product(text: str) -> Optional[str]:
    return _extract_field(text, "Impacted Product")


def _extract_plan(text: str) -> Optional[str]:
    m = re.search(r"\*Plan:?\*\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip("*").strip()
    m = re.search(r"\|\s*\*?(Free|Paid|Essentials|Standard|Premium|Pay As You Go)[^|]*\*?\s*\|", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _build_dedup_key(user_id: Optional[str], feedback: str) -> str:
    """Create a dedup key from user_id + normalized feedback hash."""
    uid = user_id or "unknown"
    norm = re.sub(r"\s+", " ", feedback.lower().strip())[:200]
    h = hashlib.md5(norm.encode()).hexdigest()[:12]
    return f"{uid}:{h}"


def parse_message(msg: RawSlackMessage) -> ParsedVOC:
    text = msg.text
    user_id = _extract_user_id(text)
    feedback = _extract_feedback(text)

    return ParsedVOC(
        raw_message=msg,
        user_id=user_id,
        customer_name=_extract_customer_name(text),
        mrr=_extract_mrr(text),
        plan=_extract_plan(text),
        csat=_extract_csat(text),
        prs=_extract_prs(text),
        feedback=feedback,
        criticality=_extract_criticality(text),
        impacted_product=_extract_impacted_product(text),
        dedup_key=_build_dedup_key(user_id, feedback),
    )


def parse_all(messages: list[RawSlackMessage]) -> list[ParsedVOC]:
    return [parse_message(m) for m in messages if len(m.text) > 30]


def deduplicate(vocs: list[ParsedVOC]) -> list[ParsedVOC]:
    """Remove duplicate VOCs across channels (same user + same feedback)."""
    seen: dict[str, ParsedVOC] = {}
    for v in vocs:
        key = v.dedup_key
        if key not in seen:
            seen[key] = v
    return list(seen.values())
