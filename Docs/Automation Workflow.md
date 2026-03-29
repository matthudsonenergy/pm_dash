# PM Dashboard Automation Workflow

This document explains how automation works in the PM dashboard, what the system drafts for review, and what remains explicitly human-led.

## Operating Principle

The dashboard is designed as an exception-first PM operating system.

It separates work into three buckets:

- `Automate`: repeated, structured, low-risk workflow steps
- `Augment`: draft generation, prioritization support, and signal synthesis that still requires PM review
- `Human-led`: judgment-heavy decisions, accountability, and sensitive communications

The goal is not maximum automation. The goal is faster PM control with clear human ownership.

## What The System Automates

These workflows run without requiring PM line-by-line review of each intermediate step:

- `.mpp` import and schedule snapshot creation
- milestone slip detection from snapshot-to-snapshot comparison
- schedule freshness checks for saved project files
- stale-plan detection
- cross-project dependency refresh from imported predecessor references
- resource conflict detection across critical work
- attention queue assembly
- cockpit rollups for overdue actions, risks, decisions, and missing updates

These automations are intended to reduce manual chasing and make exceptions visible sooner.

## What The System Augments

These workflows generate drafts or recommendations, but the PM is still the approval gate:

- weekly action suggestions from follow-ups and notes
- weekly risk suggestions from blockers and risk language
- weekly decision suggestions from approvals-needed text
- weekly status summary drafts
- reminder drafts
- portfolio executive summary drafts
- outbound communication drafts such as:
  - missing weekly update prompts
  - overdue action reminders
  - approval chase notes
  - dependency chase notes
  - steering pre-read drafts

The system can prepare these items quickly, but they should be treated as review material, not final output.

## What Remains Human-Led

These responsibilities stay with the PM and should not be delegated to automation:

- final RAG or confidence judgment
- whether a slip is acceptable or requires intervention
- escalation decisions and timing
- stakeholder messaging in sensitive situations
- sponsor and executive communications
- resource tradeoff decisions across projects
- scope, budget, and schedule commitment decisions
- recovery-plan choices
- final approval of executive summaries
- final approval of outbound communication drafts

The dashboard informs these decisions. It does not own them.

## Weekly Workflow

### 1. Refresh schedules

Use the imports page to refresh saved project files.

The system will:

- load the saved `.mpp` file
- create a fresh schedule snapshot
- recompute slips, dependencies, and portfolio signals
- update refresh freshness status

The PM still owns:

- checking failed imports
- deciding whether stale data blocks reporting
- validating surprising schedule changes

### 2. Capture weekly project updates

Use each project workflow page to update:

- status summary
- blockers
- approvals needed
- follow-ups
- confidence note
- meeting notes
- status notes

The system will:

- normalize the text input
- regenerate pending suggestions for that week
- group suggestions by type
- prepare summary and reminder drafts

The PM still owns:

- deciding which suggestions become real actions, risks, or decisions
- editing wording where context or politics matter

### 3. Review the weekly cockpit

Use the cockpit as the control page for the week.

The system will surface:

- pending suggestions
- freshness gaps
- top exception items
- outbound drafts
- executive summary draft and final summary state
- project-level “why now” explainers

The PM still owns:

- intervention priority
- what gets escalated this week
- which drafts are acceptable to send or share

### 4. Work the attention queue

Use the attention queue to triage exceptions with direct next-action links.

Typical categories include:

- leadership surprise risk
- stale plan
- missing weekly update
- overdue actions
- overdue decisions
- worsening risks
- blocked cross-project dependencies
- upcoming milestones
- material slips

The system prioritizes heuristically. The PM still decides what matters first.

### 5. Finalize portfolio messaging

Generate the executive summary from the cockpit when ready.

The system will:

- summarize portfolio status
- compare against last week
- assemble top risks and decision asks
- attach source trace counts for transparency

The PM still owns:

- final overall status language
- what to emphasize or de-emphasize
- whether to accept or dismiss the draft

## Review Gates

The following items should always be treated as review-gated:

- suggestions that create actions
- suggestions that create risks
- suggestions that create decisions
- outbound communication drafts
- executive summary drafts

Nothing in the current system auto-sends external communication.

## Viewer vs Editor Responsibilities

- `Viewer`: can see portfolio, cockpit, workflow, attention, dependencies, and draft state
- `Editor`: required for imports, weekly updates, review actions, and draft acceptance/dismissal

This keeps read access broad while protecting mutating workflow steps.

## Current Safety Boundaries

The system does not:

- auto-send emails or messages
- auto-accept executive summaries
- auto-create stakeholder-facing commitments
- auto-escalate issues
- auto-resolve priority conflicts

That boundary is intentional.

## Recommended Team Usage

Use the dashboard with this cadence:

1. Refresh saved schedules at the start of the week.
2. Capture project updates on workflow pages.
3. Review suggestions and exception items in the cockpit.
4. Triage the attention queue.
5. Generate and finalize the executive summary.
6. Review any outbound drafts before sending outside the tool.

## Practical Rule

If the output changes commitments, tone, escalation posture, or leadership messaging, keep the PM in the final review loop.
