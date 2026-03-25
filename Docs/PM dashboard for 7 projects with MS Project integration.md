# **PM dashboard for 7 projects with MS Project integration**

## **Objective**

Create a single control tower that helps you manage seven projects by surfacing what needs attention, automating the repetitive parts, and preserving your judgment for tradeoffs, escalations, and stakeholder management.

## **Recommended operating model**

Use the dashboard as an **exception-management system**, not just a reporting screen.

The split should be:

* **Automate** data collection, reminders, action hygiene, schedule diffs, stale-item detection, and recurring report assembly.  
* **Augment** risk detection, status drafting, schedule-impact analysis, cross-project dependency insights, and executive summaries.  
* **Keep human-led** prioritization, escalation, recovery decisions, stakeholder messaging, and scope/resource tradeoffs.

The dashboard should answer three questions fast:

1. What is off track right now?  
2. What needs my decision this week?  
3. Which projects are likely to surprise leadership soon?

## **Feature set to include**

### **Core portfolio view**

This is the home screen across all 7 projects.

Include:

* project health by RAG status  
* milestone confidence score  
* next major milestone and days remaining  
* top 3 risks per project  
* overdue actions count  
* overdue dependencies count  
* budget or effort variance, if available  
* open decisions needing owner or approval  
* recent schedule movement  
* “needs PM attention” priority ranking

This should let you scan all 7 projects in under 2 minutes.

### **Per-project drilldown**

Each project page should show:

**Delivery**

* key milestones from MS Project  
* baseline vs current finish dates  
* critical path tasks  
* slipped tasks since last refresh  
* milestone trend over time

**Execution**

* open actions by owner/date  
* unresolved blockers  
* upcoming reviews and approvals  
* dependency map  
* late predecessor tasks affecting current work

**Risk and decisions**

* active risks and issues  
* new candidate risks detected from notes/status updates  
* decision log  
* pending escalations

**Communications**

* latest status summary  
* last steering committee notes  
* stakeholder heat map  
* recent changes in tone or confidence from updates

### **Cross-project views**

This is where the dashboard becomes much more valuable than 7 separate project trackers.

Add:

* shared resource conflicts across projects  
* overlapping milestones in the same week  
* cross-project dependencies  
* common risk themes  
* projects with repeated schedule churn  
* projects with too many overdue items  
* projects with lots of activity but no decisions  
* projects at risk of leadership surprise

A strong cross-project page helps you allocate attention, not just monitor data.

### **Attention queue**

This should be one of the most important screens.

Create a queue of:

* milestones slipping within 30 days  
* overdue decisions  
* overdue executive actions  
* risks with rising severity  
* dependencies blocked by another project  
* projects with missing status updates  
* projects with stale plans  
* tasks on critical path with low owner confidence

This turns the dashboard into a working tool, not a passive report.

### **Weekly PM cockpit**

Build a weekly operating page that helps you run your cadence.

Include:

* this week’s milestone changes  
* actions due this week  
* steering committee prep items  
* decisions to force this week  
* risks newly opened or worsened  
* tasks requiring follow-up with owners  
* draft portfolio status summary  
* reminders to send

This should support your Monday planning and Friday status cycle.

## **Task matrix**

| PM task | category | best use of ai / automation | human role | main risk | recommended workflow |
| ----- | ----- | ----- | ----- | ----- | ----- |
| MS Project schedule ingestion | Automate | Pull task, milestone, baseline, finish, predecessor, and critical path data into the dashboard on a refresh cadence | Validate mapping once and review exceptions | Bad field mapping or stale data | Scheduled import from MS Project files \-\> validation rules \-\> exception log |
| Schedule slip detection | Automate | Compare current vs prior snapshot and flag milestone or critical-path movement | Decide what matters | Too many low-value alerts | Snapshot compare \-\> only material variance shown |
| Portfolio health scoring | Augment | Calculate health from schedule variance, overdue actions, risk trend, and dependency delays | Override score when context matters | False sense of precision | System proposes score \-\> PM confirms or edits |
| Weekly status first draft | Augment | Draft project and portfolio summaries from schedule changes, RAID, and actions | Set narrative and escalation language | Polished but misleading summary | Pull structured data \-\> AI draft \-\> PM edit |
| Risk candidate detection | Augment | Scan notes and updates for blocker language, repeated slippage, or uncertainty | Confirm whether something is a real risk | Noise treated as signal | Meeting/status inputs \-\> AI suggests risks \-\> PM validates |
| RAID register maintenance | Augment | Deduplicate, rewrite, and cluster risks/issues/dependencies | Set severity, owner, and mitigation | Over-cleaning hides nuance | AI cleanup \-\> PM approves final entries |
| Action tracker hygiene | Automate | Detect missing owners/dates, duplicates, overdue tasks, stale actions | Resolve ambiguity | Wrong or duplicate tasks | Tracker sync \-\> automated checks \-\> PM exception pass |
| Reminder nudges | Automate | Send reminders for overdue tasks, upcoming reviews, and missing updates | Decide when to escalate manually | Reminder fatigue | Rule-based reminders \-\> PM handles exceptions |
| Decision log maintenance | Automate / Augment | Capture decision candidates from meetings and summarize context | Decide what counts as a decision and who owns it | Important decisions not formalized | Notes \-\> AI extracts candidate decisions \-\> PM confirms |
| Cross-project dependency view | Augment | Detect linked milestones or tasks that affect multiple projects | Decide intervention path | Weak inferred dependencies | Imported schedules \-\> dependency engine \-\> PM validates |
| Resource conflict detection | Augment | Spot people or teams assigned to conflicting critical work across projects | Negotiate priorities with leads | Incomplete resource data | Resource scan \-\> AI flags likely conflicts \-\> PM resolves |
| Steering committee prep | Augment | Draft agenda, talking points, top risks, decision asks | Set sequencing and political strategy | Weak framing | Dashboard data \-\> AI draft pack \-\> PM finalizes |
| Escalation recommendations | Keep human-led | AI can organize facts and likely impact | Decide whether, when, and how to escalate | Damaged trust or poor timing | System brief \-\> PM chooses action |
| Priority tradeoffs across 7 projects | Keep human-led | AI can show scenarios and impact options | Make actual sequencing decisions | Treating model output as authority | Dashboard shows options \-\> PM and leaders decide |
| Sensitive stakeholder communications | Keep human-led | AI can help structure drafts | Own message, tone, and timing | Credibility loss | AI prep only \-\> PM writes or heavily edits |

## **What to automate first**

Start with the highest-frequency, lowest-risk pieces.

### **Phase 1: dashboard foundation**

Automate:

* import of milestone and task data from MS Project  
* baseline vs current schedule comparisons  
* overdue action detection  
* upcoming milestone reminders  
* stale plan detection  
* project-level summary metrics

This gives you immediate visibility.

### **Phase 2: PM workflow automation**

Automate or augment:

* weekly status draft generation  
* action item extraction from meeting notes  
* RAID candidate extraction  
* decision log suggestions  
* reminder workflows  
* milestone change summaries

This reduces coordination toil.

### **Phase 3: portfolio intelligence**

Augment:

* cross-project dependency analysis  
* resource conflict detection  
* leadership surprise indicators  
* trend scoring for project health  
* portfolio executive summary drafts

This improves attention allocation and decision speed.

## **What to keep manual**

These should stay explicitly yours:

* final RAG status call  
* whether a slip is tolerable or needs escalation  
* what to present to leadership  
* how to sequence priorities across projects  
* recovery plan choices  
* resource negotiation  
* scope cuts or tradeoffs  
* sponsor messaging  
* politically sensitive risk framing

The dashboard should inform these decisions, not make them.

## **Best automations for MS Project specifically**

Assuming the main source is MS Project files, the highest-value automations are:

### **1\. Schedule snapshoting**

Every refresh, capture:

* project finish date  
* milestone dates  
* critical path tasks  
* float where available  
* top predecessor relationships  
* percent complete trends

Then compare to prior snapshots.

### **2\. Variance detection**

Auto-flag:

* milestones slipping more than X days  
* critical tasks starting late  
* tasks completed late on critical path  
* excessive schedule churn  
* variance from baseline over threshold

### **3\. Dependency alerts**

Auto-identify:

* predecessor late, successor starting soon  
* dependency owner missing  
* external dependency unresolved near milestone  
* cross-project dates that no longer align

### **4\. Confidence scoring**

Use dashboard logic to estimate delivery confidence from:

* recent slip velocity  
* number of overdue actions  
* open unresolved risks  
* dependency blockage  
* amount of rebaselining  
* status update recency

Keep this as advisory, not authoritative.

### **5\. Draft narrative generation**

Use imported schedule deltas plus risk/action changes to draft:

* project weekly status  
* portfolio weekly status  
* steering committee pre-read  
* “what changed this week” summary

## **Suggested dashboard tabs**

1. **Portfolio Overview**  
2. **Attention Queue**  
3. **Project Detail**  
4. **Milestones & Variance**  
5. **Risks / Issues / Decisions**  
6. **Dependencies**  
7. **Actions & Owners**  
8. **Weekly PM Cockpit**  
9. **Executive View**

## **Suggested metrics and signals**

### **Portfolio-level**

* projects red / yellow / green  
* milestones due in 30 / 60 / 90 days  
* slipped milestones this week  
* overdue actions by project  
* unresolved dependencies by project  
* decisions pending by project  
* risk trend by project  
* projects with no recent update  
* projects with health deteriorating over 2–4 weeks

### **Project-level**

* current finish vs baseline finish  
* critical path length or count  
* tasks slipped this week  
* % critical tasks overdue  
* open high risks  
* days since last decision  
* count of blocked tasks  
* owner response lag  
* milestone confidence trend

## **Guardrails**

* Do not let the dashboard become a passive reporting warehouse.  
* Do not auto-send sensitive status or escalation messages without PM review.  
* Do not over-alert on every schedule movement; threshold for materiality matters.  
* Do not rely on a single health score without visible drivers.  
* Do not make resource recommendations from incomplete staffing data.  
* Do not let AI-generated status hide unresolved ambiguity.  
* Do not treat MS Project as complete truth if actual execution signals live elsewhere.

## **Suggested defaults**

A practical default operating model:

* **System of record for schedule:** MS Project  
* **System of action:** dashboard action/decision/risk layers  
* **Refresh cadence:** daily for schedule imports, weekly for executive rollups  
* **Alert style:** only material exceptions  
* **PM review points:** before stakeholder distribution, before escalations, before portfolio health changes  
* **Cadence:** Monday attention review, midweek dependency check, Friday status pack review

## **Priority rollout**

Implement these first:

1. MS Project ingestion and schedule variance screen  
2. Attention queue with overdue actions, slipping milestones, and unresolved dependencies  
3. Weekly status draft generation  
4. RAID and decision-log support  
5. Cross-project dependency and resource conflict page  
6. Executive portfolio summary page

## **My recommendation on design philosophy**

Build it around **exceptions, confidence, and decisions**, not around raw task lists.

The most useful dashboard for a primary PM is not:  
 “show me everything.”

It is:

* what changed  
* what is now risky  
* what needs my intervention  
* what must be decided this week

