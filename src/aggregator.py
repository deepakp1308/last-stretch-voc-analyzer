"""Aggregate classified VOCs into themed buckets with MRR exposure and priority scoring."""

from __future__ import annotations

from src.models import (
    AnalysisReport,
    ClassifiedVOC,
    MRRTier,
    Theme,
    ThemeBucket,
)
from datetime import datetime, timezone


CHURN_KEYWORDS = [
    "churn", "leave", "cancel", "switch", "move off",
    "may need to", "looking for alternative", "p0", "p1",
]


def _count_churn_signals(vocs: list[ClassifiedVOC]) -> int:
    count = 0
    for v in vocs:
        fb = v.parsed.feedback.lower()
        crit = (v.parsed.criticality or "").lower()
        if any(kw in fb or kw in crit for kw in CHURN_KEYWORDS):
            count += 1
    return count


def _compute_priority_score(bucket: ThemeBucket) -> float:
    """Priority = weighted combination of MRR exposure, volume, churn risk,
    and HVC concentration.

    Higher score = higher priority.
    """
    voc_count = len(bucket.vocs)
    mrr_score = min(bucket.total_mrr_exposure / 1000, 20)
    volume_score = min(voc_count * 0.8, 15)
    churn_score = bucket.churn_signals * 3
    hvc_ratio = bucket.hvc_count / max(voc_count, 1)
    hvc_score = hvc_ratio * 10

    return mrr_score + volume_score + churn_score + hvc_score


def build_theme_buckets(classified: list[ClassifiedVOC]) -> list[ThemeBucket]:
    """Group R&A-related negative VOCs by theme and compute aggregates."""
    ra_negative = [v for v in classified if v.is_ra_related and v.is_negative]

    buckets_map: dict[Theme, list[ClassifiedVOC]] = {}
    for v in ra_negative:
        buckets_map.setdefault(v.theme, []).append(v)

    buckets: list[ThemeBucket] = []
    for theme, vocs in buckets_map.items():
        if theme == Theme.MISCELLANEOUS:
            continue

        seen_users: set[str] = set()
        total_mrr = 0.0
        hvc_mrr = 0.0
        non_hvc_mrr = 0.0
        hvc_count = 0
        non_hvc_count = 0
        free_count = 0

        for v in vocs:
            uid = v.parsed.user_id or v.parsed.customer_name or "unknown"
            if uid in seen_users:
                continue
            seen_users.add(uid)

            mrr = v.parsed.mrr or 0
            total_mrr += mrr

            if v.mrr_tier == MRRTier.HVC:
                hvc_mrr += mrr
                hvc_count += 1
            elif v.mrr_tier == MRRTier.NON_HVC:
                non_hvc_mrr += mrr
                non_hvc_count += 1
            else:
                free_count += 1

        bucket = ThemeBucket(
            theme=theme,
            vocs=vocs,
            total_mrr_exposure=total_mrr,
            hvc_mrr_exposure=hvc_mrr,
            non_hvc_mrr_exposure=non_hvc_mrr,
            hvc_count=hvc_count,
            non_hvc_count=non_hvc_count,
            free_count=free_count,
            churn_signals=_count_churn_signals(vocs),
        )
        bucket.priority_score = _compute_priority_score(bucket)
        buckets.append(bucket)

    buckets.sort(key=lambda b: b.priority_score, reverse=True)

    for i, b in enumerate(buckets):
        b.priority_score = round(b.priority_score, 1)

    return buckets


def build_report(
    classified: list[ClassifiedVOC],
    date_start: datetime,
    date_end: datetime,
    raw_count: int,
    deduped_count: int,
) -> AnalysisReport:
    ra_negative = [v for v in classified if v.is_ra_related and v.is_negative]
    misc = [v for v in classified if not v.is_ra_related or not v.is_negative]
    buckets = build_theme_buckets(classified)

    return AnalysisReport(
        run_date=datetime.now(timezone.utc),
        date_range_start=date_start,
        date_range_end=date_end,
        total_raw_messages=raw_count,
        total_deduped=deduped_count,
        total_ra_negative=len(ra_negative),
        total_miscellaneous=len(misc),
        theme_buckets=buckets,
        overall_mrr_exposure=sum(b.total_mrr_exposure for b in buckets),
    )
