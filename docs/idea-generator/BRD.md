# Idea Generator — Business Requirements Document

| Field | Value |
| --- | --- |
| Status | Draft for approval |
| Version | 0.1 |
| Date | 1 October 2026 |
| Product | AI Journalist |
| Proposed workspace | Idea Generator |
| Proposed route | `/ideas` |
| Initial market | United Arab Emirates |
| Initial formats | Documentary, Expert Interview |

## 1. Executive summary

Add a third creation workspace, **Idea Generator**, alongside **New Story** and **Research**. A user selects either **Documentary** or **Expert Interview**, then clicks **I am feeling lucky**. The app researches current UAE business signals and returns exactly five distinct, evidence-backed video ideas for the selected format.

The product should combine several kinds of evidence rather than treating a single popularity metric as truth:

- UAE-specific business news, government announcements, company activity, and web research identify candidate topics.
- Google Trends validates search momentum in the UAE when an approved data path is available.
- vidIQ supplies proprietary estimates of YouTube keyword demand/competition and, where the live tool supports them, breakout/velocity signals that help assess treatment opportunities.
- Existing research methods corroborate claims and supply the factual and editorial material needed to shape an idea.

The result is not a list of generic AI brainstorms. Each idea explains **why now**, **why it matters in the UAE**, what evidence supports it, and why it can work in the chosen video format.

## 2. Product problem

The current application starts after the user already knows what story to make:

- **New Story** develops a supplied topic into documentary angles, hooks, chapters, and a script.
- **Research** investigates a supplied topic.

Users still have to discover a timely, locally relevant topic themselves. This creates three problems:

1. Topic selection depends on intuition and manual scanning across disconnected sources.
2. A topic may be newsworthy but have weak YouTube demand, or have YouTube interest without a defensible UAE business angle.
3. The existing documentary workflow does not support Expert Interview as a production format.

Idea Generator fills the upstream discovery gap. It should discover opportunities, explain the evidence, and hand a selected opportunity into the appropriate next workspace without hiding uncertainty.

## 3. Goals

### 3.1 Business goals

- Reduce the time required to find a viable UAE business video topic.
- Increase the proportion of stories based on current, corroborated audience and market signals.
- Create a repeatable editorial discovery process rather than an untraceable brainstorm.
- Encourage users to continue from discovery into Research and New Story.
- Learn which sectors, formats, and evidence signals lead to ideas users actually develop.

### 3.2 User goals

- Receive five useful ideas without writing a prompt.
- Choose whether the ideas are for a documentary or an expert interview.
- Understand why each idea is timely and UAE-relevant.
- Inspect the evidence behind an idea.
- Continue with a promising idea without copying information between workspaces.
- Return to an in-progress or completed generation after navigating away.

### 3.3 Success criteria for the MVP

- Every publishable run contains exactly five ideas of the selected format. If five ideas cannot pass the evidence gates after one recovery search, the run fails rather than padding or publishing a shorter set.
- Every idea has a clear UAE business anchor, a recent signal, and citations from at least two independent source domains.
- No more than two ideas in a result set belong to the same business sector.
- Users can see which providers participated and whether the result has full or partial signal coverage.
- Documentary ideas can be handed into New Story with their brief and sources intact.
- Expert Interview ideas can be opened as a research-backed brief; a full interview-production workflow is subject to the approval decision in section 16.
- Product actions such as **Develop in New Story** are rendered by application logic. The model does not generate a `recommended_next_steps` section or spend tokens producing one.

## 4. Non-goals for the MVP

- Predicting virality or guaranteeing video performance.
- Treating Google Trends, vidIQ, views, or VPH as proof of audience geography or editorial truth.
- Automatically publishing content, contacting guests, or booking interviews.
- Producing a finished script directly from the lucky-button run.
- Replacing editorial judgment, legal review, fact-checking, or source verification.
- Collecting private contact information about proposed interview guests.
- Supporting countries outside the UAE in the first release.
- Generating both formats in one run. One run returns five ideas for the format selected by the user.

## 5. Users and jobs to be done

### Primary user: producer or editor

> When I need the next UAE business story, I want a short list of current, defensible ideas so I can choose a topic without manually checking many platforms.

### Secondary user: researcher or journalist

> When an idea looks promising, I want to inspect the supporting signals and sources so I can judge whether the premise is real and worth deeper research.

### Secondary user: video host or interviewer

> When I choose an interview format, I want a strong editorial question, the type of expert required, and anchor questions so I know what conversation could be distinctive.

## 6. Product principles

1. **Evidence before prose.** Candidate topics are discovered and scored before the model writes ideas.
2. **UAE relevance must be explicit.** A global trend is not a UAE idea until local evidence connects it to the market.
3. **Signals have defined roles.** News discovers events; Google Trends measures relative search interest through the capabilities available to the selected adapter; vidIQ estimates YouTube opportunity. None substitutes for all the others.
4. **Uncertainty is visible.** Missing providers and weak coverage lower confidence and remain visible to the user.
5. **One click stays one click.** The MVP has fixed UAE/business/30-day defaults; tuning controls are deferred until the base workflow is validated.
6. **Metrics are calculated, not invented.** The application computes scores from stored signals; the language model does not fabricate numerical values.
7. **Actions are product UI, not generated prose.** The application owns CTAs and workflow guidance. No model call should create “recommended next steps.”
8. **Editorial policy is explicit.** The current downstream Story prompt requires UAE institutions, government, and rulers to be framed neutrally or constructively. The Idea Generator must either inherit that rule or Product must approve its replacement; it must never silently alter or omit material facts to force a topic through the rule.

## 7. Scope and core experience

### 7.1 Navigation

Add **Idea Generator** between **New Story** and **Research** in the Workspace section of the sidebar.

Proposed navigation:

1. New Story
2. Idea Generator
3. Research
4. History

The workspace uses `/ideas`. A persisted run is addressable as `/ideas?id={run_id}` so refresh, browser history, and a bookmarkable user-scoped link restore the same run.

### 7.2 Empty state

The page presents:

- Heading: **Idea Generator**
- Supporting line: **Evidence-led UAE business ideas for your next video**
- Format control:
  - Documentary, selected by default
  - Expert Interview
- Fixed MVP context:
  - Geography: UAE
  - Domain: Business
  - Trend horizon: last 30 days
- Primary button: **I am feeling lucky**

The first MVP intentionally omits **Tune my luck**. A later phase may add a validated emirate list, preferred/excluded sectors, 7/30/90-day horizons, and additional output languages without changing the default one-click path.

### 7.3 Generation experience

The click creates a persisted asynchronous run and immediately shows real workflow stages:

1. Scanning current UAE, search, and YouTube signals, with live provider sub-statuses
2. Grouping related developments
3. Verifying the strongest topics
4. Ranking distinct opportunities
5. Shaping five ideas

The user may navigate away. Returning to the run resumes status polling. Only one run may be active per user in the MVP. If the user clicks the button while another run is active, the app opens that run and explains that it is already in progress. Repeated clicks and network retries must not create duplicates.

### 7.4 Completed experience

The page displays:

- **5 Documentary ideas for UAE business**, or **5 Expert Interview ideas for UAE business**
- Generated timestamp and trend window
- Overall source coverage by provider family
- Five ranked idea cards
- A **Generate fresh set** action that creates a new run and supplies the previous result IDs as exclusions
- Recent generation history

## 8. Functional requirements

### FR-1 — Select a format

- The user can select `documentary` or `expert_interview` before starting a run.
- The chosen format is stored on the run and every generated idea.
- A successful run never mixes formats.

### FR-2 — Generate five ideas

- **I am feeling lucky** creates an asynchronous generation run.
- A completed run returns exactly five ideas.
- If quality gates cannot produce five defensible ideas, the system performs one bounded recovery search.
- If five still cannot be supported, the run fails with `insufficient_evidence`; it does not publish an incomplete or padded set.

### FR-3 — Use all applicable research methods

“All research methods” means all enabled methods that are relevant and available, not that every adapter must be called blindly for every candidate. The discovery workflow should use:

- Tavily web search
- Anthropic Search
- NewsAPI
- UAE-localized RSS and Google News RSS
- Anthropic deep research, in a bounded discovery or verification pass
- Page scraping for selected sources
- Alpha Vantage or another financial-data adapter only when a candidate includes a public company or market metric
- vidIQ MCP for proprietary estimated YouTube keyword demand and competition, plus trend/outlier/VPH signals only where the live MCP capability is confirmed
- Google Trends through an approved adapter when available
- Supadata or the existing YouTube transcript tool only for a small number of shortlisted videos where transcript evidence improves the treatment

The orchestration layer records which methods ran, failed, were skipped as inapplicable, or were unavailable.

### FR-4 — Define and validate “trending”

A candidate is “trending” only when it has:

- at least one recent momentum signal within the selected horizon; and
- a specific UAE connection; and
- corroboration from at least two independent factual or editorial source domains. vidIQ and Google Trends do not count as factual corroboration.

Examples of momentum signals include rising UAE search interest, acceleration in related reporting, a new policy or investment event, recent high VPH, or a channel-relative YouTube outlier. Lifetime views alone do not qualify.

### FR-5 — Show evidence and source coverage

Each idea shows two to four concise signal summaries. **View evidence** expands:

- provider or publisher
- direct source link where one exists
- publication or observation date
- geography and time window
- metric definition
- retrieval time
- any important caveat

The run header shows provider status as `available`, `unavailable`, `failed`, `skipped`, or `stale`.

### FR-6 — Common idea content

Every idea includes:

- rank
- working title
- selected format
- business sector
- one-sentence premise or audience promise
- why now
- UAE relevance
- central tension or editorial question
- intended audience
- two to four evidence-backed signals
- business significance
- score breakdown
- qualitative strength: Strong, Emerging, or Exploratory
- confidence and source-coverage level
- verification gaps or production risks
- citations/source references

The product should prefer qualitative strength labels in the UI. A numerical score may appear in an evidence detail view only when every component is explainable.

### FR-7 — Documentary-specific content

A documentary idea also includes:

- narrative tension
- likely protagonist or access target
- locations or visual opportunities
- proposed evidence spine
- what could change or be revealed during production

### FR-8 — Expert Interview-specific content

An expert interview idea also includes:

- interview promise
- ideal expert archetypes
- up to three named public candidates only when identity and relevance are source-verified
- the disagreement, trade-off, or tension worth exploring
- three to five anchor questions
- claims or assumptions that require challenge during the interview

The system must not imply that a guest has agreed to participate or expose non-public contact data.

### FR-9 — Act on an idea

Available actions:

- **View evidence** — opens the source detail without a new model call.
- **Open in Research** — opens an editable, prefilled Research request with the idea, questions, and citations. Research starts only after user confirmation.
- **Develop in New Story** — available for documentary ideas in the MVP; opens the New Story composer with an editable brief and evidence. A Story is created only after user confirmation, and generation does not start automatically.
- **Save** — marks the idea as saved.
- **Dismiss** — collapses the idea, records negative feedback, and offers **Undo** plus a **Show dismissed** control. The run still contains five stored ideas.
- **Copy brief** — copies a deterministic rendering of stored fields.

After a confirmed handoff, its CTA becomes a link to the created Story or Research session. Deleting the originating run removes saved/dismissed ideas and its evidence snapshot, but does not delete independent handoff resources.

These controls are application-defined. They are not generated as a “Recommended Next Steps” section and incur no output tokens.

### FR-10 — History and regeneration

- Users can view their previous runs from a recent-runs rail.
- History is user-scoped and sorted newest first.
- Opening a run restores its provider state and ideas.
- **Generate fresh set** creates a separate run and instructs ranking to penalize semantic overlap with the preceding results.
- Deleting a run requires a normal confirmation and does not delete a Story or Research session created from one of its ideas.
- **Try again** repeats the same inputs after a failed run without excluding previous candidates.
- **Retry missing sources** is shown only for a completed run with partial coverage and reattempts the unavailable provider capabilities without creating a new editorial set.
- While a fresh set is running, retained old cards are labelled **Previous set** and are never presented as partial output from the active run.
- The recent-run rail has explicit loading, empty, error, selected, running, completed, and failed states. Active runs cannot be deleted unless cancellation is implemented.

### FR-11 — Coverage and failed states

- A provider failure does not silently disappear.
- The run may continue with reduced coverage when the minimum evidence gate is still met.
- Run outcome and evidence coverage are separate. Terminal run statuses are `completed` and `failed`; `coverage_level` is `full` or `partial`.
- **Core evidence**, required for any completed run, means at least two independent factual/editorial domains per idea, including one current and reliable UAE-related source.
- **Full coverage** additionally requires a participating vidIQ capability relevant to the shortlisted topics and a Google Trends capability able to validate UAE search momentum for those topics.
- A provider that is feature-flagged off is reported as `not_configured`, does not appear in “checked” UI copy, and makes coverage partial.
- A discovery-only Google Trends BigQuery result does not count as candidate-level search validation unless the candidate actually appears in that dataset.
- Missing or partial Google Trends/vidIQ capability lowers coverage and confidence but does not by itself block a completed five-idea result.
- If five ideas cannot meet the core evidence gate, the run fails with a retry action and preserves the last successful run.

### FR-12 — No generated recommended-next-steps content

- The structured response schema must not contain `recommended_next_steps`, `next_steps`, or an equivalent prose field.
- The synthesis prompt must explicitly prohibit conclusions or recommended-next-steps sections.
- Exporters and API serializers must not synthesize such a section.
- CTAs are derived from idea state and format in frontend code.
- Tests must fail if a model response attempts to add an unsupported top-level field.

## 9. Evidence-provider roles and constraints

| Provider family | Primary role | Not sufficient to prove | MVP behavior when unavailable |
| --- | --- | --- | --- |
| UAE news, government, company, web | Discover current local events and corroborate facts | Audience demand by itself | Required evidence family; use remaining enabled research sources |
| Google Trends | Relative UAE search momentum; related queries only when the selected adapter supports them | Absolute demand, public opinion, or future performance | Continue with partial coverage |
| vidIQ | Proprietary estimated YouTube keyword demand/competition and conditionally available VPH/outlier evidence | UAE audience location unless the exact metric supports it | Continue with partial coverage |
| Financial data | Verify market/company metrics where applicable | Broad cultural interest | Skip if inapplicable |
| Video transcripts | Understand themes, claims, and coverage gaps in selected videos | Topic popularity by itself | Optional, shortlist only |

Important provider constraints:

- The official Google Trends API remains a gated alpha and is described by Google as potentially not production-ready. It cannot be a hard launch dependency until access and operating terms are confirmed.
- vidIQ offers a remote MCP endpoint and credit-metered research tools, but production use needs a provider-supported backend authorization arrangement. Installing a vidIQ connector in ChatGPT or Codex does not authorize this FastAPI application.
- Some live vidIQ tool schemas expose country-related inputs, while public help material describes narrower geography support. Country semantics must be contract-tested. A channel located in the UAE is not proof that viewers are in the UAE.
- Supadata is a transcript source, not a trend-discovery provider.
- The official Trends BigQuery dataset exposes limited top/rising lists, not arbitrary-keyword validation. It is a discovery source unless a shortlisted topic appears in its data.

## 10. Ranking and quality rules

### 10.1 Proposed score

Candidates are scored out of 100:

| Dimension | Weight |
| --- | ---: |
| UAE relevance | 20 |
| Timeliness and momentum | 20 |
| YouTube opportunity | 15 |
| Business significance | 15 |
| Editorial potential | 15 |
| Production feasibility | 10 |
| Evidence quality | 5 |

Numerical scoring is deterministic from normalized signals and evidence-linked rubric features. A bounded model-assisted extraction step may classify qualitative features such as “credible protagonist identified” or “documented stakeholder conflict,” but it cannot assign the final number or modify raw metrics.

### 10.2 Minimum candidate gates

- UAE relevance: at least 12/20
- At least two independent factual/editorial source domains; syndicated copies and duplicate press releases count once
- At least one reliable, current UAE-related source
- At least one qualifying momentum signal within the selected horizon
- No unsupported allegation or unverified causal claim
- Documentary: a plausible visual, access, or protagonist lane
- Expert Interview: at least two plausible expert archetypes, or source-verified public candidates

### 10.3 Set-level gates

- Exactly five on a normal completed run
- Maximum two ideas from one sector
- No near-duplicate premise or central question
- A calibrated semantic-similarity ceiling using a versioned similarity provider; `0.82` is a spike hypothesis, not an approved production threshold
- A mix of established and emerging signals where evidence supports it
- No idea included solely because it has high lifetime YouTube views

### 10.4 Confidence and coverage

Score, confidence, and coverage are separate:

- **Score** estimates editorial opportunity.
- **Confidence** estimates how strongly the evidence supports the premise.
- **Coverage** describes which evidence families and providers participated.

Missing provider data is not treated as zero opportunity, nor is it silently reweighted to make an idea appear stronger. The application calculates an available-signal score and lowers confidence/coverage explicitly.

## 11. Non-functional requirements

### Performance

- Run creation response: p95 under 1 second
- Full generation target: p50 under 120 seconds, p95 under 300 seconds, with a configurable run-wide deadline
- Status polling interval: approximately 3 seconds
- Source/evidence expansion: under 500 ms from stored data

### Reliability

- Persist a run before starting external calls.
- Persist stage transitions and provider outcomes.
- Detect jobs abandoned by a process restart.
- MVP may follow the current background-task/watchdog pattern; production should use a durable queue with retries and idempotent workers.
- A client-generated idempotency key prevents duplicate runs from double-clicks or network retries.

### Cost control

- Use a fixed provider call plan, never an open-ended tool loop.
- Enforce both a request-local vidIQ call ceiling and live-credit ceiling. Initial spike proposal: no more than seven paid calls and no more than 35 live credits; stop at whichever limit is reached first.
- Read the vidIQ credit balance before a run where the tool permits a zero-credit balance check.
- Cache reusable discovery results persistently across application instances.
- Use one structured synthesis call for the five ideas, plus at most one schema-repair call.
- Do not use model tokens to generate navigation, calls to action, or recommended next steps.

### Security and privacy

- Provider credentials remain server-side and are never returned to the browser.
- Every run, idea, and handoff is scoped to the authenticated user.
- Treat web pages, transcripts, and tool output as untrusted data, not prompt instructions.
- Allowlist read-only vidIQ tools. Do not permit the agent to mutate watchlists, drafts, or other account state.
- Store only public, relevant information about prospective interview guests.

### Accessibility

- Full keyboard support for format selection and idea actions
- `aria-live` status announcements during generation
- `role="alert"` for errors
- Focus moves to the result heading when a run completes
- Status never relies on color alone

## 12. Analytics and observability

### Product events

- `idea_run_started`
- `idea_run_completed`
- `idea_run_completed_partial_coverage`
- `idea_run_failed`
- `idea_viewed`
- `idea_saved`
- `idea_dismissed`
- `idea_opened_in_research`
- `idea_developed_in_story`
- `fresh_set_requested`

Event properties include selected format, horizon, sector mix, provider coverage, latency, and algorithm version. Do not send full private prompts or credentials.

### Operational metrics

- Run latency by stage and provider
- Provider success, timeout, and rate-limit rates
- Calls and credits per vidIQ run
- Model input/output tokens by run and task
- Candidate counts before/after quality gates
- Rejection reasons
- Percentage of `completed` and `failed` runs, plus full/partial coverage rate
- Cache hit ratio and cache age

### Initial product targets

Targets should be calibrated in beta. Proposed starting targets:

- At least 30% of completed runs produce an idea the user saves, researches, or develops.
- At least 15% produce a Story or Research handoff.
- Fewer than 5% of normal runs fail for internal errors.
- At least 90% of completed ideas pass citation-integrity checks.

## 13. Dependencies

- A production-authorized vidIQ credential and confirmation of relevant MCP operating terms
- A Google Trends path approved by Product and Engineering:
  - official API alpha, if access is granted;
  - verified official BigQuery dataset coverage for `AE`;
  - approved commercial provider; or
  - launch in transparent partial-coverage mode
- UAE-localized discovery sources and query configuration
- New persisted run and idea models
- A dedicated idea-generation service/agent
- A format-aware handoff contract
- A durable job runner for post-MVP reliability

## 14. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Google Trends API access is unavailable | Requested source cannot participate live | Provider abstraction; validate official BigQuery `AE`; show partial coverage; do not scrape as a production dependency |
| vidIQ geography is misinterpreted | “Trending in UAE” claim is misleading | Require UAE evidence from local sources/Trends; label metric geography; contract-test every tool |
| vidIQ credits are exhausted | Runs slow or lose YouTube evidence | Balance check, fixed call budget, persistent cache, partial-coverage mode |
| Broad “all research methods” makes runs slow and expensive | Poor UX and high cost | Parallel discovery, applicability rules, shortlist before deepening, fixed ceilings |
| Five ideas become variations of one event | Low user value | Topic clustering, semantic deduplication, sector cap, previous-run exclusions |
| Model invents metrics, guests, or sources | Editorial and trust risk | Structured evidence IDs, deterministic scoring, source validator, verified-public-person rule |
| Expert ideas flow into documentary prompts | Incorrect output | Block documentary handoff for Expert Interview until format-aware workflow exists |
| Existing UAE framing rule is applied only after handoff | Promising ideas are later rejected or materially reframed | Apply the approved rule during candidate selection; reject topics that cannot comply without misleading omission |
| Background process restarts | Lost in-flight work | Persist stages now; watchdog; durable queue before general availability |
| Existing uncommitted vidIQ work is incorporated blindly | Regression or ownership confusion | Audit, test, and land it as an explicit implementation dependency |

## 15. Delivery proposal

### Phase 0 — Provider and contract spike

- Confirm vidIQ authentication for a deployed backend.
- Snapshot and test exact tool schemas, geography semantics, credits, timeout behavior, caching rights, and multi-user commercial use.
- Apply for the Google Trends API alpha and query the official BigQuery dataset to verify whether `AE` is present.
- Decide partial-coverage behavior before UI implementation.

### Phase 1 — MVP

- New `/ideas` workspace and navigation item
- Documentary and Expert Interview selection
- Persisted asynchronous runs and history
- Fixed UAE business discovery matrix
- Multi-source gather, normalize, cluster, rank, and synthesis workflow
- Exactly five evidence-backed ideas where gates can be met
- Provider coverage and partial-state UI
- Documentary handoff to New Story
- Research handoff for both formats
- Save, dismiss, copy brief, and generate-fresh-set actions

### Phase 2 — Production hardening

- Durable job queue and retry policy
- Persistent provider cache and cost dashboard
- **Tune my luck** controls for validated emirates, sectors, exclusions, and horizons
- Arabic output plus expanded Arabic-source discovery coverage
- Feedback-informed ranking
- Shared inclusion in unified History
- Provider contract monitoring and schema-change alerts

### Phase 3 — Expert Interview production workflow

- Format field on Story
- Interview-specific outline, guest brief, question architecture, challenge questions, and interview script
- Format-aware editing and export UI
- **Develop in New Story** for Expert Interview ideas

## 16. Canonical decisions required for approval

| ID | Decision | Options | Recommended choice |
| --- | --- | --- | --- |
| D1 | Publish fewer than five? | Publish 1–4 with warning / fail the run | **Fail.** Every publishable result keeps the five-idea promise. |
| D2 | Google Trends launch path | Official alpha / verified official BigQuery discovery / licensed provider / partial coverage | **Build a capability-based adapter, apply for alpha, verify BigQuery `AE`, and allow visibly partial coverage during beta.** No unofficial scraping dependency. |
| D3 | Minimum provider policy | Require every named provider / require core factual evidence and disclose optional gaps | **Require core factual evidence; show `partial` coverage when vidIQ or candidate-level Google Trends validation is absent.** General-availability copy must describe only configured capabilities. |
| D4 | Expert Interview handoff | Full Story workflow now / editable Research brief only | **Research brief only in MVP.** Add the format-aware Story pipeline later. |
| D5 | Documentary handoff | Auto-create/start / open editable New Story prefill | **Open editable prefill; create the Story only on confirmation; never auto-start generation.** |
| D6 | Research handoff | Start automatically / open editable prefill | **Open editable prefill and start only on confirmation.** |
| D7 | Tune my luck | MVP / later phase | **Later phase.** MVP fixes UAE, business, 30 days, and English output. |
| D8 | Active runs | Multiple / one per user | **One active run per user.** Reopen it on another lucky click. |
| D9 | Output language | English only / English and Arabic | **English output in MVP with bounded English/Arabic discovery queries.** |
| D10 | Numerical score in UI | Always visible / qualitative default | **Qualitative strength by default; explainable score in evidence detail.** |
| D11 | Job runner | Current background tasks / durable queue | **Current persisted background-task/watchdog pattern for internal MVP; durable queue before general availability.** |
| D12 | Similarity implementation | Fixed uncalibrated threshold / versioned provider and benchmark | **Versioned similarity provider with a calibrated threshold from the editorial benchmark.** |
| D13 | Route/API naming | Alternatives / `/ideas` plus `/api/v1/idea-generations` | **Use `/ideas` and `/api/v1/idea-generations`.** |
| D14 | Existing UAE editorial framing rule | Inherit current neutral/constructive hard constraint / replace through a separate editorial-policy decision | **Inherit for compatibility in MVP, make it a versioned policy gate, and reject any topic that would require material fact omission.** |

The seven-call/35-credit vidIQ values are spike ceilings, not a product commitment; live measurement and provider terms determine the release budget.

## 17. MVP acceptance criteria

The MVP is accepted when:

1. Idea Generator appears between New Story and Research for authenticated users.
2. The user can select Documentary or Expert Interview and start a run with one click.
3. The API acknowledges the run asynchronously and the UI restores it after refresh/navigation.
4. The UI displays real stages and the status of vidIQ, Google Trends, news, and web-research evidence families.
5. Every completed run contains exactly five distinct ideas of the selected format; otherwise it fails with `insufficient_evidence`.
6. Every idea passes UAE, recency, citation, and source-independence gates.
7. Each idea exposes its evidence and provider caveats.
8. Documentary ideas can open an editable New Story prefill; confirmation creates a Story with copied evidence and no discovery-provider calls until the user explicitly refreshes research.
9. Both formats can open an editable Research prefill; no research starts before confirmation.
10. Expert Interview ideas cannot accidentally enter the documentary-only production flow.
11. Save, dismiss, copy, retry, regenerate, and recent-run behaviors work and are user-scoped.
12. Provider timeouts, exhausted credits, and missing Google access produce explicit partial-coverage or failed states without changing the five-idea result contract.
13. Duplicate clicks are idempotent, and a second lucky click opens the user's active run.
14. Structured run/provider records and logs capture latency, cost, provider coverage, model usage returned by providers, and quality-gate outcomes; an external analytics sink is not required for MVP acceptance.
15. The model response schema, UI, exports, and tests contain no generated “Recommended Next Steps” content.
16. The approved UAE framing policy is applied before synthesis, versioned on the run, and tested; policy compliance cannot rewrite or conceal contradictory source evidence.

## 18. Reference notes

- [vidIQ MCP](https://support.vidiq.com/en/articles/15082430-vidiq-mcp)
- [vidIQ Keyword Research](https://support.vidiq.com/en/articles/9421214-keywords-research)
- [vidIQ Outliers](https://support.vidiq.com/en/articles/9660010-outliers)
- [vidIQ features and credits](https://support.vidiq.com/en/articles/13928456-features-credits-by-plan)
- [Google Trends API alpha](https://developers.google.com/search/apis/trends)
- [Google Trends API announcement](https://developers.google.com/search/blog/2025/07/trends-api)
- [Google Trends data interpretation](https://developers.google.com/search/docs/monitor-debug/trends-start)
- [Google Trends data FAQ](https://support.google.com/trends/answer/4365533)
- [Google Trends BigQuery dataset](https://support.google.com/trends/answer/12764470)
- [International Google Trends dataset announcement](https://cloud.google.com/blog/products/data-analytics/international-google-trends-datasets-in-bigquery)
- [YouTube Data API search](https://developers.google.com/youtube/v3/docs/search/list)
- [YouTube Data API revision history](https://developers.google.com/youtube/v3/revision_history)
