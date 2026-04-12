"""Classify VOCs: R&A relevance, sentiment, MRR tier, and thematic bucket."""

from __future__ import annotations

import re

from src.models import (
    ClassifiedVOC,
    MRRTier,
    NEGATIVE_CSAT_VALUES,
    BORDERLINE_CSAT_VALUES,
    ParsedVOC,
    RA_KEYWORDS,
    Theme,
)


def _is_ra_related(voc: ParsedVOC) -> bool:
    """Determine if a VOC is related to reporting, analytics, data quality,
    export, or recipient activity."""
    searchable = (voc.feedback + " " + (voc.impacted_product or "")).lower()

    if voc.impacted_product and voc.impacted_product.lower() in ("analytics", "analytics & reporting"):
        return True

    hit_count = sum(1 for kw in RA_KEYWORDS if kw in searchable)
    if hit_count >= 2:
        return True

    url = (voc.current_page_url or "").lower()
    ra_url_patterns = [
        "analytics", "reports", "recipient-activity",
        "click-performance", "custom-reports", "marketing-dashboard",
        "reports/export",
    ]
    if any(p in url for p in ra_url_patterns):
        if hit_count >= 1:
            return True

    return False


def _is_negative(voc: ParsedVOC) -> bool:
    """Determine if sentiment is negative based on CSAT, PRS, and text signals."""
    if voc.csat:
        csat_lower = voc.csat.strip().lower()
        if csat_lower in NEGATIVE_CSAT_VALUES:
            return True
        if csat_lower in BORDERLINE_CSAT_VALUES:
            neg_words = [
                "can't", "cannot", "removed", "missing", "broken",
                "wrong", "issue", "problem", "frustrat", "awful",
                "terrible", "rubbish", "useless", "worse", "bug",
                "destroy", "inaccurat", "discrepan", "disappear",
            ]
            if any(w in voc.feedback.lower() for w in neg_words):
                return True

    if voc.prs is not None and voc.prs <= 4:
        return True

    if voc.criticality:
        if "p0" in voc.criticality.lower() or "p1" in voc.criticality.lower():
            return True

    explicit_negative = [
        "churn", "leave", "move off", "switch", "cancel",
        "broken", "destroying", "useless", "rubbish",
    ]
    if any(w in voc.feedback.lower() for w in explicit_negative):
        return True

    return False


def _get_mrr_tier(voc: ParsedVOC) -> MRRTier:
    if voc.mrr is None or voc.mrr == 0:
        return MRRTier.FREE
    return MRRTier.HVC if voc.mrr >= 299 else MRRTier.NON_HVC


_THEME_RULES: list[tuple[Theme, list[str]]] = [
    (Theme.EXPORT_FIELDS_STRIPPED, [
        "export.*field", "export.*missing", "export.*removed",
        "no longer contain", "no longer include",
        "removed.*field", "removed.*column", "removed.*data",
        "audience field", "contact field", "contact info",
        "company.*column", "phone number.*export", "phone number.*report",
        "vital.*info", "identifier", "ids.*missing", "ids.*export",
        "bounce reason", "can't export", "stripped",
    ]),
    (Theme.DATA_ACCURACY, [
        "discrepan", "incorrect", "wrong.*number", "wrong.*data",
        "inaccurat", "doesn't match", "don't match",
        "reset to 0", "reset to zero", "metrics.*zero",
        "100%.*when", "rounding", "aggregat.*wrong",
        "not showing all", "not showing.*open", "not showing.*click",
        "glitch", "bug.*report", "all-time revenue",
        "lowered.*historical", "wrong.*figure",
    ]),
    (Theme.REPORTING_UX_REGRESSION, [
        "too many click", "can't filter", "can't find",
        "hard to find", "hard to export", "confusing.*ux",
        "confusing.*report", "confusing.*dashboard", "navigation",
        "awful.*report", "regression", "removed.*functionality",
        "worse.*report", "can't read.*report", "unintuitive",
        "keeps changing", "sort.*order.*changed", "default.*order",
        "redirect.*recipient", "click performance.*redirect",
        "can't find.*demographic",
    ]),
    (Theme.AB_MULTIVARIATE, [
        "a/b.*test", "a/b.*export", "multivariate", "multi-variate",
        "group a", "group b", "subject line.*export",
        "subject line.*missing", "preview.*a/b",
    ]),
    (Theme.BOT_MPP_CONTAMINATION, [
        "bot.*open", "bot.*click", "bot.*filter",
        "mpp", "mail privacy protection",
        "security filter.*click", "3000.*click",
        "bot.*data", "proxy.*data",
    ]),
    (Theme.DEPRECATED_FEATURES, [
        "top location.*discontinued", "top location.*removed",
        "mobile device.*data", "mobile.*device.*removed",
        "date range.*export", "date range.*campaign",
        "no longer see.*mobile", "discontinued.*feature",
        "feature.*removed",
    ]),
]


def _assign_theme(voc: ParsedVOC) -> tuple[Theme, float]:
    """Assign a thematic bucket based on keyword pattern matching.

    Returns (theme, confidence) where confidence is 0.0-1.0.
    """
    feedback_lower = voc.feedback.lower()
    best_theme = Theme.MISCELLANEOUS
    best_hits = 0

    for theme, patterns in _THEME_RULES:
        hits = sum(1 for p in patterns if re.search(p, feedback_lower))
        if hits > best_hits:
            best_hits = hits
            best_theme = theme

    if best_hits == 0:
        return Theme.MISCELLANEOUS, 0.3

    confidence = min(0.5 + best_hits * 0.15, 0.95)
    return best_theme, confidence


def classify_voc(voc: ParsedVOC) -> ClassifiedVOC:
    is_ra = _is_ra_related(voc)
    is_neg = _is_negative(voc)
    tier = _get_mrr_tier(voc)

    if is_ra and is_neg:
        theme, confidence = _assign_theme(voc)
    else:
        theme = Theme.MISCELLANEOUS
        confidence = 0.8 if not is_ra else 0.5

    return ClassifiedVOC(
        parsed=voc,
        is_ra_related=is_ra,
        is_negative=is_neg,
        mrr_tier=tier,
        theme=theme,
        confidence=confidence,
    )


def classify_all(vocs: list[ParsedVOC]) -> list[ClassifiedVOC]:
    return [classify_voc(v) for v in vocs]
