"""Pydantic models for structured VOC data throughout the pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Sentiment(str, Enum):
    TERRIBLE = "Terrible"
    POOR = "Poor"
    AVERAGE = "Average"
    GOOD = "Good"
    EXCELLENT = "Excellent"
    UNKNOWN = "Unknown"


class MRRTier(str, Enum):
    HVC = "HVC ($299+ MRR)"
    NON_HVC = "Non-HVC (<$299 MRR)"
    FREE = "Free / Unknown"


class Theme(str, Enum):
    EXPORT_FIELDS_STRIPPED = "Export Fields Stripped from Reports"
    DATA_ACCURACY = "Report Data Accuracy & Metrics Discrepancies"
    REPORTING_UX_REGRESSION = "Custom Reports & Dashboard UX Regression"
    AB_MULTIVARIATE = "A/B & Multivariate Test Reporting Deficiencies"
    BOT_MPP_CONTAMINATION = "Bot / MPP Data Contamination"
    DEPRECATED_FEATURES = "Deprecated Reporting Features"
    MISCELLANEOUS = "Miscellaneous / Others"


class ChannelSource(str, Enum):
    REPORTING_FEEDBACK = "mc-reporting-analytics-feedback"
    HVC_FEEDBACK = "hvc_feedback"
    HVC_ESCALATIONS = "mc-hvc-escalations"


CHANNEL_CONFIG = {
    ChannelSource.REPORTING_FEEDBACK: "C06SW7512P2",
    ChannelSource.HVC_FEEDBACK: "C051Y4H98VB",
    ChannelSource.HVC_ESCALATIONS: "C095FJ3SQF4",
}

RA_KEYWORDS = [
    "report", "reporting", "analytics", "export", "csv", "download",
    "recipient activity", "click performance", "open rate", "bounce",
    "dashboard", "marketing dashboard", "custom report", "campaign report",
    "metrics", "data", "statistics", "stats", "numbers", "figures",
    "benchmark", "unsubscribe report", "delivery rate", "multivariate",
    "a/b test", "click map", "performance report", "bot", "mpp",
    "audience field", "contact field", "company column", "phone number",
    "subject line", "group a", "group b",
]

NEGATIVE_CSAT_VALUES = {
    "terrible", "poor",
    "muy insatisfecho", "poco satisfecho",
    "pessimo", "scarso",
}

BORDERLINE_CSAT_VALUES = {
    "average",
    "medianamente satisfecho", "media",
}


class RawSlackMessage(BaseModel):
    channel: ChannelSource
    channel_id: str
    timestamp: str
    datetime_utc: datetime
    author: str
    author_id: str
    text: str
    thread_reply_count: int = 0
    reactions: list[str] = Field(default_factory=list)


class ParsedVOC(BaseModel):
    raw_message: RawSlackMessage
    user_id: Optional[str] = None
    customer_name: Optional[str] = None
    mrr: Optional[float] = None
    plan: Optional[str] = None
    csat: Optional[str] = None
    prs: Optional[int] = None
    feedback: str = ""
    current_page_url: Optional[str] = None
    criticality: Optional[str] = None
    impacted_product: Optional[str] = None
    dedup_key: str = ""


class ClassifiedVOC(BaseModel):
    parsed: ParsedVOC
    is_ra_related: bool = False
    is_negative: bool = False
    mrr_tier: MRRTier = MRRTier.FREE
    theme: Theme = Theme.MISCELLANEOUS
    confidence: float = 0.0


class ThemeBucket(BaseModel):
    theme: Theme
    vocs: list[ClassifiedVOC] = Field(default_factory=list)
    total_mrr_exposure: float = 0.0
    hvc_mrr_exposure: float = 0.0
    non_hvc_mrr_exposure: float = 0.0
    hvc_count: int = 0
    non_hvc_count: int = 0
    free_count: int = 0
    churn_signals: int = 0
    priority_score: float = 0.0


class EvaluationResult(BaseModel):
    """Output of the LLM evaluator quality gate."""
    passed: bool = False
    confidence: float = 0.0
    total_vocs_reviewed: int = 0
    corrections_made: int = 0
    issues_found: list[str] = Field(default_factory=list)
    corrections: list[dict] = Field(default_factory=list)
    summary: str = ""


class CSATDistribution(BaseModel):
    """CSAT sentiment distribution across all deduped VOCs."""
    negative_count: int = 0
    negative_pct: float = 0.0
    neutral_count: int = 0
    neutral_pct: float = 0.0
    positive_count: int = 0
    positive_pct: float = 0.0
    total: int = 0


class AnalysisReport(BaseModel):
    run_date: datetime
    date_range_start: datetime
    date_range_end: datetime
    total_raw_messages: int = 0
    total_deduped: int = 0
    total_ra_negative: int = 0
    total_miscellaneous: int = 0
    csat_distribution: Optional[CSATDistribution] = None
    theme_buckets: list[ThemeBucket] = Field(default_factory=list)
    evaluation: Optional[EvaluationResult] = None
    overall_mrr_exposure: float = 0.0
