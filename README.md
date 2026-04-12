# Last Stretch VOC Analyzer

Automated daily Voice of Customer analysis agent for Reporting & Analytics feedback. Scans three Slack channels, classifies and thematically categorizes negative VOCs, calculates MRR exposure, and publishes a prioritized dashboard.

## Architecture

```
Slack Channels ──► Ingest ──► Parse ──► Dedup ──► Classify ──► Aggregate
      │                                                            │
      │                                                    LLM Evaluator
      │                                                   (review + correct)
      │                                                            │
      ▼                                                            ▼
  3 channels:                                              Re-aggregate
  • #mc-reporting-analytics-feedback                            │
  • #hvc_feedback                                               ├──► Dashboard (GitHub Pages)
  • #mc-hvc-escalations                                         └──► Slack Notification
```

### Pipeline Steps

1. **Ingest** — Read messages from 3 Slack channels (March 24 → today)
2. **Parse** — Extract MRR, CSAT, PRS, user ID, feedback text, criticality
3. **Dedup** — Remove cross-channel duplicates (same user + same feedback hash)
4. **Classify** — Tag R&A relevance, sentiment (negative/positive), MRR tier ($299+/below), thematic bucket
5. **Aggregate** — Group by theme, compute MRR exposure, priority score
6. **LLM Evaluate** — GPT-4o reviews a sample of classifications, proposes corrections
7. **Re-aggregate** — Apply corrections and rebuild the report
8. **Dashboard** — Generate static HTML published to GitHub Pages
9. **Notify** — Slack message with summary and dashboard link

### Thematic Buckets

| Theme | What It Captures |
|-------|-----------------|
| Export Fields Stripped | Audience fields (company, phone, IDs) removed from report exports |
| Data Accuracy | Metrics discrepancies, wrong data, rendering bugs |
| Reporting UX Regression | Too many clicks, missing filters, navigation issues |
| A/B & Multivariate | Missing subject lines, generic group labels |
| Bot/MPP Contamination | Bot opens and Apple MPP polluting metrics |
| Deprecated Features | Removed capabilities (location data, mobile stats) |

### Quality Controls

- **Unit tests** — Parser, classifier, aggregator, and Slack payload tests
- **Fixture-based accuracy tests** — 10 representative VOCs with expected outcomes (≥80% accuracy gate)
- **E2e pipeline tests** — Full pipeline invariants (MRR math, priority ordering, count consistency)
- **LLM evaluator** — Second-pass LLM reviews classifications, corrects errors, validates aggregation math
- **Coverage gate** — PR tests require ≥70% coverage

## How It Runs

### Primary: Cursor Agent Skill (recommended)

The agent runs directly in Cursor using Slack MCP — no API keys needed.

```
You: "Run VOC analysis"
Agent: reads Slack channels → classifies → evaluates → publishes dashboard → DMs you
```

The skill is installed at `~/.cursor/skills/last-stretch-voc-analyzer/SKILL.md`.

Trigger phrases: "run VOC analysis", "VOC report", "last stretch analysis", "R&A feedback"

### Backup: GitHub Actions

A daily cron at 7 AM PST also runs via GitHub Actions (requires secrets for Slack SDK + OpenAI).

## Dashboard

Published to GitHub Pages: https://deepakp1308.github.io/last-stretch-voc-analyzer/

## Local Development

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## License

Internal tool — Intuit Mailchimp.
