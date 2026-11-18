# SCOP Skills Catalog

This catalog is the central inventory of SCOP skills. IDs follow the official list order and stay with their skills across category changes. Dependencies and integrations are suggestions for future work. They do not establish implementation or cross-agent compatibility.

See the [status guide](STATUS.md) for advancement evidence and the [roadmap](ROADMAP.md) for the proposed implementation order.

## Summary

| Category | Total | PLANNED | PROTOTYPE — NOT LIVE VALIDATED | VALIDATED — PENDING MERGE |
| --- | ---: | ---: | ---: | ---: |
| Engineering and release | 12 | 9 | 2 | 1 |
| Governance and verification | 9 | 9 | 0 | 0 |
| Research, memory, and ML | 5 | 5 | 0 | 0 |
| Product, design, and web quality | 10 | 10 | 0 | 0 |
| Market, strategy, and growth | 14 | 14 | 0 | 0 |
| Content and media | 11 | 11 | 0 | 0 |
| Operations and productivity | 15 | 15 | 0 | 0 |
| Data and analytics | 8 | 8 | 0 | 0 |
| **Total** | **84** | **81** | **2** | **1** |

Pull Request Summary is registered under its official catalog name. Its implementation slug is `pr-source-summary`. The reported Codex validation matched 14 source references across three public GitHub PRs and passed 13 regression tests. Approval and merge are pending. [Validation report](../tests/pr-source-summary/REPORT.md)

## Engineering and release

| ID | Skill | Description | Status | Suggested dependencies and integrations |
| --- | --- | --- | --- | --- |
| SCOP-001 | Code Architect | Designs software components and documents architectural trade-offs. | PLANNED | Architecture decision records, Feature Specification Builder |
| SCOP-002 | API Design | Defines API contracts and versioning rules. | PLANNED | OpenAPI, Code Architect |
| SCOP-003 | QA Engineer | Develops risk-based test plans and acceptance checks. | PLANNED | Feature Specification Builder, issue trackers |
| SCOP-004 | Debugging Specialist | Uses logs and reproducible observations to narrow down defects. | PLANNED | Test Failure Diagnosis, debuggers |
| SCOP-005 | Code Reviewer | Reviews changes for correctness and maintainability. | PLANNED | Pull Request Summary, GitHub diffs |
| SCOP-006 | Deployment Manager | Plans deployments, rollback, and post-release checks. | PLANNED | Checklist Before Release, CI/CD |
| SCOP-007 | Checklist Before Release | Produces release readiness checks and evidence requirements. | PLANNED | QA Engineer, CI results |
| SCOP-008 | Pull Request Summary | Summarizes GitHub PRs with claim-level source references. | VALIDATED — PENDING MERGE | GitHub metadata and diffs |
| SCOP-009 | Regression Test Generator | Drafts targeted tests for defects or behavior changes. | PROTOTYPE — NOT LIVE VALIDATED | QA Engineer, test runners |
| SCOP-010 | Library Migration | Plans dependency changes and compatibility checks. | PLANNED | Documentation Research, package managers |
| SCOP-011 | Code Documentation | Drafts developer documentation from code and examples. | PLANNED | Documentation Research, repository files |
| SCOP-012 | Test Failure Diagnosis | Interprets failing test output and prioritizes likely causes. | PROTOTYPE — NOT LIVE VALIDATED | Test runners, CI artifacts |

## Governance and verification

| ID | Skill | Description | Status | Suggested dependencies and integrations |
| --- | --- | --- | --- | --- |
| SCOP-015 | Security Review | Identifies code and configuration risks and proposes mitigations. | PLANNED | Code Reviewer, dependency scanners |
| SCOP-016 | Readable Audit Log | Presents technical events as a readable audit trail. | PLANNED | Structured logs, redaction tools |
| SCOP-017 | Project Permission MCP | Defines and checks project-scoped tool permissions. | PLANNED | MCP, identity providers |
| SCOP-018 | Module Governance | Documents module ownership and review policies. | PLANNED | Project Permission MCP, ownership manifests |
| SCOP-019 | Phased Audit | Stages audits and records evidence at checkpoints. | PLANNED | Module Governance, Readable Audit Log |
| SCOP-020 | Agent Audit Report | Summarizes agent actions and policy decisions. | PLANNED | Phased Audit, Readable Audit Log |
| SCOP-021 | API Cost Review | Compares API usage and estimated spending against budgets. | PLANNED | Usage exports, provider pricing |
| SCOP-024 | Verification Loop | Rechecks outputs against acceptance criteria and records gaps. | PLANNED | QA Engineer, test runners |
| SCOP-028 | Skills Inventory | Tracks skill registrations, versions, and validation evidence. | PLANNED | SCOP catalog, repository metadata |

## Research, memory, and ML

| ID | Skill | Description | Status | Suggested dependencies and integrations |
| --- | --- | --- | --- | --- |
| SCOP-022 | Unified Memory | Defines shared formats for recording and retrieving context. | PLANNED | Project Permission MCP, storage adapters |
| SCOP-023 | Cross-Session Memory | Retrieves relevant context across authorized sessions. | PLANNED | Unified Memory, retention controls |
| SCOP-026 | Documentation Research | Finds authoritative technical documentation and cites passages. | PLANNED | Official documentation, web search |
| SCOP-027 | MLE Workflow | Organizes ML experiments, evaluation, and handoff. | PLANNED | Data Cleaning, experiment tracking |
| SCOP-060 | Deep Research | Synthesizes evidence from multiple sources and documents uncertainty. | PLANNED | Documentation Research, research databases |

## Product, design, and web quality

| ID | Skill | Description | Status | Suggested dependencies and integrations |
| --- | --- | --- | --- | --- |
| SCOP-013 | Front-end Standards | Defines front-end conventions for maintainability and usability. | PLANNED | Design System Generator, linters |
| SCOP-025 | Browser Visual Check | Checks rendered browser states for visual discrepancies. | PLANNED | Browser automation, screenshots |
| SCOP-077 | UX Research Synthesizer | Extracts themes and open questions from user research. | PLANNED | Research notes, transcripts |
| SCOP-078 | Accessibility Auditor | Identifies accessibility issues with automated and manual checks. | PLANNED | Browser Visual Check, WCAG checkers |
| SCOP-079 | Design System Generator | Drafts design tokens, components, and usage guidance. | PLANNED | UX Research Synthesizer, design tools |
| SCOP-080 | Mobile Responsiveness Auditor | Checks layout and interactions across viewport sizes. | PLANNED | Browser Visual Check, device emulation |
| SCOP-081 | Performance Optimizer | Profiles bottlenecks and proposes measurable improvements. | PLANNED | Browser Visual Check, performance profilers |
| SCOP-082 | SEO Technical Auditor | Checks crawlability, indexing signals, and structured data. | PLANNED | Browser Visual Check, site crawlers |
| SCOP-083 | Product Requirements Generator | Drafts product goals, requirements, and success measures. | PLANNED | UX Research Synthesizer, product analytics |
| SCOP-084 | Feature Specification Builder | Translates product requirements into testable behavior. | PLANNED | Product Requirements Generator, issue trackers |

## Market, strategy, and growth

| ID | Skill | Description | Status | Suggested dependencies and integrations |
| --- | --- | --- | --- | --- |
| SCOP-029 | Product Intelligence | Synthesizes usage and feedback to inform product decisions. | PLANNED | Product analytics, feedback tools |
| SCOP-030 | Market Research | Estimates market characteristics and documents source limitations. | PLANNED | Deep Research, industry datasets |
| SCOP-031 | Competitor Intelligence | Tracks competitor offerings and public product changes. | PLANNED | Market Research, public competitor sources |
| SCOP-032 | Competitive Report Builder | Builds sourced comparisons of competitors and positioning. | PLANNED | Competitor Intelligence, document tools |
| SCOP-033 | Idea Validation | Frames demand hypotheses and designs tests for them. | PLANNED | Market Research, surveys |
| SCOP-034 | Investor Materials | Drafts investor briefs and pitch materials from approved evidence. | PLANNED | Strategic Planner, financial models |
| SCOP-035 | Market Illustration | Visualizes market segments, positioning, and trends. | PLANNED | Market Research, charting libraries |
| SCOP-036 | Business Analyst | Analyzes operating data and documents business requirements. | PLANNED | Data Cleaning, spreadsheets |
| SCOP-037 | Strategic Planner | Develops strategic options, milestones, and measures. | PLANNED | Business Analyst, Market Research |
| SCOP-038 | Lead Hunter | Identifies leads against documented qualification criteria. | PLANNED | Approved public sources, CRM |
| SCOP-039 | Sales Intelligence | Summarizes account signals and sales opportunities. | PLANNED | Lead Hunter, CRM |
| SCOP-040 | Conversion Optimizer | Diagnoses funnel drop-offs and proposes experiments. | PLANNED | Product analytics, experimentation platforms |
| SCOP-041 | Customer Success AI | Surfaces account health signals and drafts follow-ups. | PLANNED | Churn Prediction, support platforms |
| SCOP-042 | Marketing Intelligence | Evaluates campaign and audience signals across channels. | PLANNED | Data Cleaning, campaign analytics |

## Content and media

| ID | Skill | Description | Status | Suggested dependencies and integrations |
| --- | --- | --- | --- | --- |
| SCOP-014 | Front-end Slides | Builds browser-based slides and checks rendering. | PLANNED | Front-end Standards, browser automation |
| SCOP-043 | Article Writer | Drafts articles from briefs and checks factual claims. | PLANNED | Documentation Research, editorial tools |
| SCOP-044 | Video Editor | Assembles footage, captions, and audio from an edit plan. | PLANNED | Media files, FFmpeg |
| SCOP-045 | Product Demo Generator | Scripts and assembles product demonstrations. | PLANNED | Browser Visual Check, screen capture |
| SCOP-046 | Changelog Video | Turns verified release notes into a short script and storyboard. | PLANNED | Pull Request Summary, release notes |
| SCOP-047 | Animated CSV Charts | Creates animated charts from labeled CSV data. | PLANNED | Data Cleaning, charting libraries |
| SCOP-048 | Video Branding | Applies approved visual and audio branding to videos. | PLANNED | Video Editor, brand assets |
| SCOP-049 | Metrics Video Generator | Turns reviewed metrics into a narrated video briefing. | PLANNED | Dashboard Generator, Animated CSV Charts |
| SCOP-050 | Screen Tutorial Generator | Creates step-by-step tutorials from recorded workflows. | PLANNED | Screen capture, Video Editor |
| SCOP-051 | Remotion Video Builder | Builds programmatic compositions and renders video. | PLANNED | Remotion, Video Branding |
| SCOP-052 | 3D Image Generator | Creates 3D illustrations from scene briefs. | PLANNED | Blender, asset libraries |

## Operations and productivity

| ID | Skill | Description | Status | Suggested dependencies and integrations |
| --- | --- | --- | --- | --- |
| SCOP-053 | Executive Assistant | Prepares briefings and organizes administrative tasks. | PLANNED | Meeting Intelligence, calendars |
| SCOP-054 | Project Manager AI | Tracks milestones, dependencies, and project risks. | PLANNED | Issue trackers, Resource Allocator |
| SCOP-055 | Meeting Intelligence | Extracts decisions, owners, and actions from meeting records. | PLANNED | Transcripts, document stores |
| SCOP-056 | Knowledge Manager | Organizes and retrieves internal knowledge with source references. | PLANNED | Unified Memory, document stores |
| SCOP-057 | Workflow Optimizer | Identifies operational bottlenecks and proposes improvements. | PLANNED | Business Process Mapper, operational data |
| SCOP-058 | Routine Organizer | Builds repeatable schedules and task sequences. | PLANNED | Task lists, calendars |
| SCOP-059 | Google Sheets & Excel | Builds spreadsheet formulas, tables, and data summaries. | PLANNED | Google Sheets API, Excel workbooks |
| SCOP-061 | SOP Generator | Documents procedures, owners, and exceptions. | PLANNED | Business Process Mapper, document templates |
| SCOP-062 | Business Process Mapper | Maps process steps, handoffs, and decisions. | PLANNED | Process interviews, diagramming tools |
| SCOP-063 | Meeting Scheduler | Finds meeting times from availability and scheduling constraints. | PLANNED | Calendar APIs, time zone data |
| SCOP-064 | Contract Analyzer | Extracts clauses, obligations, and questions for legal review. | PLANNED | Document parsing, approved contract stores |
| SCOP-065 | Invoice Manager | Extracts invoice details and compares them with purchase records. | PLANNED | OCR, accounting systems |
| SCOP-066 | Vendor Management | Tracks vendor records, renewals, and performance. | PLANNED | Contract Analyzer, procurement systems |
| SCOP-067 | Resource Allocator | Proposes assignments based on capacity and priorities. | PLANNED | Project plans, capacity data |
| SCOP-068 | Employee Onboarding | Builds role-specific onboarding plans and checklists. | PLANNED | SOP Generator, HR systems |

## Data and analytics

| ID | Skill | Description | Status | Suggested dependencies and integrations |
| --- | --- | --- | --- | --- |
| SCOP-069 | SQL Query Builder | Drafts SQL queries from questions and schema information. | PLANNED | Schema metadata, read-only database access |
| SCOP-070 | Data Cleaning | Profiles datasets and proposes reproducible cleaning steps. | PLANNED | CSV, spreadsheets, data profiling tools |
| SCOP-071 | Dashboard Generator | Builds dashboards from defined metrics and validated datasets. | PLANNED | Data Cleaning, business intelligence tools |
| SCOP-072 | Revenue Forecasting | Estimates future revenue with assumptions and uncertainty ranges. | PLANNED | Data Cleaning, revenue history |
| SCOP-073 | Customer Segmentation | Groups customers by documented attributes or behavior. | PLANNED | Data Cleaning, customer data platforms |
| SCOP-074 | Churn Prediction | Estimates churn risk and evaluates predictive performance. | PLANNED | Customer Segmentation, MLE Workflow |
| SCOP-075 | Anomaly Detection | Flags unusual patterns against documented baselines. | PLANNED | Data Cleaning, monitoring systems |
| SCOP-076 | Data Storytelling | Explains findings through narrative, charts, and source context. | PLANNED | Dashboard Generator, visualization tools |
