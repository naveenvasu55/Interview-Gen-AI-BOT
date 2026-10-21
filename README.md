<div align="center">

# 🤖 Ibot — AI Interview Assistant

**An LLM-powered mock-interview platform that reads a candidate's resume, conducts a personalised 5-question technical interview, and produces a scored, question-by-question evaluation — with every step persisted to MySQL.**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B?logo=streamlit&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-Responses%20%26%20Chat%20APIs-412991?logo=openai&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.x-4479A1?logo=mysql&logoColor=white)
![Presidio](https://img.shields.io/badge/Microsoft%20Presidio-PII%20masking-0078D4)

</div>

---

<a id="table-of-contents"></a>
## 📑 Table of Contents

1. [Overview](#overview)
2. [Demo](#demo)
3. [Key Features](#key-features)
4. [Tech Stack](#tech-stack)
5. [System Architecture](#system-architecture)
6. [End-to-End Flow](#end-to-end-flow)
7. [Application State Machine](#application-state-machine)
8. [Database Design](#database-design)
9. [Concurrency, Locking & Data Integrity](#concurrency-locking--data-integrity)
10. [Fallbacks & Error Handling](#fallbacks--error-handling)
11. [Performance Optimisations](#performance-optimisations)
12. [LLM & Prompt Engineering](#llm--prompt-engineering)
13. [Security & Privacy](#security--privacy)
14. [Project Structure](#project-structure)
15. [Getting Started](#getting-started)
16. [Design Decisions & Trade-offs](#design-decisions--trade-offs)
17. [Known Limitations & Roadmap](#known-limitations--roadmap)

---

<a id="overview"></a>
## 🧭 Overview

Ibot simulates a real first-round technical interview:

| Stage | What happens |
|---|---|
| **1. Profile** | The candidate uploads a resume (PDF / DOCX / TXT) **or** fills in a manual form. The resume is parsed by an LLM into a strict JSON profile. |
| **2. Review** | The candidate reviews every extracted field (name, email, phone, experience, skills, projects, summary) and can edit any of them. Edits are written to MySQL. |
| **3. Interview** | On *Confirm & Start*, the profile is **locked** and **snapshotted**. The AI asks **exactly 5** personalised questions, one at a time, with follow-ups based on previous answers. |
| **4. Evaluation** | An evaluator LLM scores each answer (0–5) and computes an overall score (0–10) calibrated to the candidate's years of experience. Scores are colour-coded, and every Q&A pair is saved. |

**The problem it solves:** candidates rarely get realistic, personalised interview practice with structured, honest feedback. Recruiters rarely get a consistent, auditable first-round screen.

---

<a id="demo"></a>
## 🎬 Demo

| Setup | Review your details |
|---|---|
| ![Setup](docs/setup.png) | ![Review](docs/review.png) |

| Interview | Feedback |
|---|---|
| ![Interview](docs/interview.png) | ![Feedback](docs/feedback.png) |

---

<a id="key-features"></a>
## ✨ Key Features

- 📄 **Multi-format resume ingestion**: PDF, DOCX and TXT.
- 🧠 **LLM resume parsing with Structured Outputs**: a strict JSON Schema guarantees a well-formed profile, with no fragile string parsing.
- ✏️ **Editable review screen**: per-field ✏️ edit with Save/Cancel, server-side validation and an immediate database update.
- 🔒 **Profile locking and snapshotting**: the profile cannot change once the interview starts, and each interview stores a frozen copy of the profile it was based on.
- 💬 **Adaptive 5-question interview**: questions are generated from the candidate's real experience and stream token-by-token.
- 🛑 **Hard question cap enforced in code, not by the prompt**: the 5th answer ends the interview deterministically, with no 6th LLM call.
- 📊 **Experience-calibrated scoring**: per-question 0–5 scores, a formula-based overall 0–10 score, and colour thresholds applied deterministically in Python.
- 🗄️ **Full audit trail in MySQL**: candidate, interview lifecycle (`in_progress → completed / ended`), score, feedback and every question/answer pair.
- 🛡️ **Optional PII masking** with Microsoft Presidio (lazy-loaded).
- ⚡ **Performance-tuned**: cached clients, connection pooling, lazy heavy imports, feedback caching and streaming.

---

<a id="tech-stack"></a>
## 🧰 Tech Stack

| Layer | Technology | Why |
|---|---|---|
| UI / App server | **Streamlit** | Fast to build interactive data/AI apps in pure Python; built-in chat components and streaming. |
| LLM | **OpenAI** (`gpt-5.6-luna`), Responses API + Chat Completions API | Structured Outputs for parsing; streaming chat for the interview. |
| Database | **MySQL 8** + `mysql-connector-python` (connection pool) | Relational integrity, transactions, row-level locks, JSON columns. |
| Document parsing | `pypdf`, `python-docx` | Lightweight text extraction. |
| PII | **Microsoft Presidio** + spaCy `en_core_web_sm` | Detects and masks names, emails and phone numbers before LLM calls (optional). |
| Browser helper | `streamlit-js-eval` | Page reload for "Restart Interview". |

---
<a id="system-architecture"></a>
## 🏗️ System Architecture

```mermaid
flowchart LR
    U["👤 Candidate<br/>(Browser)"] <--> UI

    subgraph APP["Streamlit Server (single Python process)"]
        UI["Streamlit UI<br/>stage-based rendering"]
        SS[("st.session_state<br/>stage flags · profile · messages")]
        RP["Resume Pipeline<br/>PDF / DOCX / TXT → text"]
        PII["Presidio PII Masking<br/>(lazy-loaded, optional)"]
        PF["Profile Service<br/>validate · edit · lock"]
        IV["Interview Engine<br/>5-question loop"]
        EV["Evaluator<br/>score + feedback"]
        FMT["Feedback Formatter<br/>score colours · dividers"]
        OC["OpenAI Client<br/>@cache_resource<br/>timeout + retries"]
        POOL["MySQL Connection Pool<br/>@cache_resource · 10 conns"]
    end

    UI <--> SS
    UI --> RP --> PII
    RP --> OC
    UI --> PF --> POOL
    UI --> IV --> OC
    IV --> POOL
    UI --> EV --> OC
    EV --> FMT
    EV --> POOL

    OC <--> OPENAI["☁️ OpenAI API"]
    POOL <--> DB[("🗄️ MySQL<br/>candidates<br/>interviews<br/>interview_responses")]
```

**Key architectural points**

- **Stateless script, stateful session.** Streamlit re-runs the whole script on every interaction. All progress lives in `st.session_state`, and the UI renders the screen that matches the current stage flags (see the [state machine](#application-state-machine)).
- **Process-wide shared resources.** The OpenAI client, the MySQL pool and the Presidio engines are created **once per server process** with `@st.cache_resource` and shared by all users.
- **Database as the source of truth.** Session state drives the UI, but every important transition (profile saved, interview started, completed or ended, results saved) is persisted and guarded in MySQL.

---

<a id="end-to-end-flow"></a>
## 🔄 End-to-End Flow

```mermaid
sequenceDiagram
    autonumber
    actor C as Candidate
    participant UI as Streamlit App
    participant LLM as OpenAI
    participant DB as MySQL

    C->>UI: Upload resume (or fill manual form)
    UI->>UI: Extract text (pypdf / python-docx)
    opt USE_PII_MASKING = True
        UI->>UI: Presidio detect + mask PII
    end
    UI->>LLM: Responses API + strict JSON Schema
    LLM-->>UI: Structured profile JSON
    UI->>DB: INSERT ... ON DUPLICATE KEY UPDATE (candidates)
    DB-->>UI: candidate_id, public_candidate_id

    loop Review screen (0..n edits)
        C->>UI: ✏️ Edit field → Save
        UI->>DB: SELECT ... FOR UPDATE (active interview?) → UPDATE candidates
    end

    C->>UI: Confirm & Start Interview
    UI->>DB: INSERT interviews (status='in_progress', candidate_snapshot)
    UI->>LLM: System prompt (profile) → first question
    LLM-->>UI: Question 1

    loop Answers 1..4
        C->>UI: Answer
        UI->>DB: UPDATE last_activity_at (only if in_progress)
        UI->>LLM: Full conversation (stream=True)
        LLM-->>UI: Next question (streamed)
    end

    C->>UI: Answer 5
    UI->>UI: Fixed closing message (no LLM call)
    UI->>DB: UPDATE status='completed', ended_at (only if in_progress)

    C->>UI: Get Feedback
    UI->>LLM: Evaluator prompt + transcript (stream=True)
    LLM-->>UI: Scores + feedback (cached in session)
    UI->>UI: Colour scores, add dividers
    UI->>DB: ONE transaction: score + feedback + all Q&A rows → COMMIT
```

---

<a id="application-state-machine"></a>
## 🚦 Application State Machine

The UI is a finite-state machine driven by `st.session_state` flags. Only one screen is ever active.

```mermaid
stateDiagram-v2
    [*] --> ChooseSetup
    ChooseSetup --> UploadResume: "Upload Resume"
    ChooseSetup --> ManualForm: "Manual selection"

    UploadResume --> Review: parsed + saved
    ManualForm --> Review: validated + saved

    Review --> Review: edit field (Save / Cancel)
    Review --> Interview: Confirm & Start (profile LOCKED + snapshot)

    Interview --> Interview: answer #1–#4
    Interview --> Completed: answer #5
    Interview --> Ended: End Conversation

    Completed --> Feedback: Get Feedback
    Feedback --> [*]: Restart Interview
    Ended --> [*]
```

| Flag | Meaning |
|---|---|
| `choose_setup` / `setup_mode` | Setup screen passed; which path was chosen |
| `candidate_profile_saved` / `manual_profile_saved` | Profile persisted → show review screen |
| `setup_complete` | Interview started → profile locked |
| `user_message_count` | Answers submitted (cap = 5) |
| `chat_complete` / `interview_ended` | Interview finished; chat input removed |
| `feedback_shown` / `feedback_text` | Feedback requested / cached result |
| `interview_saved` | Results persisted → never saved twice |

---

<a id="database-design"></a>
## 🗄️ Database Design

```mermaid
erDiagram
    CANDIDATES ||--o{ INTERVIEWS : "takes"
    INTERVIEWS ||--o{ INTERVIEW_RESPONSES : "contains"

    CANDIDATES {
        bigint candidate_id PK
        char public_candidate_id UK "7-digit public reference"
        varchar name
        varchar email UK "upsert key"
        varchar phone
        varchar company
        varchar setup_mode "Upload Resume | Manual selection"
        longtext extracted_resume_text
        json structured_data "full parsed/edited profile"
    }

    INTERVIEWS {
        bigint interview_id PK
        bigint candidate_id FK
        enum status "in_progress | completed | ended"
        json candidate_snapshot "frozen profile at start"
        decimal overall_score "0.0 - 10.0"
        longtext overall_feedback
        datetime created_at
        datetime last_activity_at
        datetime ended_at
    }

    INTERVIEW_RESPONSES {
        bigint response_id PK
        bigint interview_id FK
        int question_number
        text ai_question
        text user_answer
    }
```

<details>
<summary><b>📜 Reference schema (SQL)</b></summary>

```sql
CREATE TABLE candidates (
    candidate_id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    public_candidate_id   CHAR(7)       NOT NULL UNIQUE,
    name                  VARCHAR(255),
    email                 VARCHAR(255)  UNIQUE,
    phone                 VARCHAR(32),
    company               VARCHAR(255),
    setup_mode            VARCHAR(32),
    extracted_resume_text LONGTEXT,
    structured_data       JSON,
    created_at            DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)
);

CREATE TABLE interviews (
    interview_id        BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id        BIGINT NOT NULL,
    status              ENUM('in_progress','completed','ended') NOT NULL,
    candidate_snapshot  JSON NULL,
    overall_score       DECIMAL(3,1) NULL,
    overall_feedback    LONGTEXT NULL,
    created_at          DATETIME(6) NOT NULL,
    last_activity_at    DATETIME(6) NOT NULL,
    ended_at            DATETIME(6) NULL,
    CONSTRAINT fk_interviews_candidate
        FOREIGN KEY (candidate_id) REFERENCES candidates(candidate_id),
    INDEX idx_candidate_status (candidate_id, status, last_activity_at)
);

CREATE TABLE interview_responses (
    response_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    interview_id     BIGINT NOT NULL,
    question_number  INT NOT NULL,
    ai_question      TEXT NOT NULL,
    user_answer      TEXT NOT NULL,
    CONSTRAINT fk_responses_interview
        FOREIGN KEY (interview_id) REFERENCES interviews(interview_id),
    UNIQUE KEY uq_interview_question (interview_id, question_number)
);
```

> Adjust column sizes and types to match your environment.

</details>

**Why two IDs?** `candidate_id` is the internal auto-increment key and is never shown. `public_candidate_id` is a random 7-digit reference shown to the candidate, so internal row counts and sequential IDs are not exposed.

---

<a id="concurrency-locking--data-integrity"></a>
## 🔐 Concurrency, Locking & Data Integrity

This section usually gets the most interest in interviews, because it shows that the app is safe beyond the happy path.

### 1. Two-layer profile lock (UI + database)

| Layer | Mechanism | Protects against |
|---|---|---|
| **UI** | Edit controls exist only on the review screen; `save_edit` rejects any save once `setup_complete` is `True`. | Normal users editing after the start. |
| **Database** | `update_candidate_profile` runs, **in the same transaction** as the update: `SELECT ... FROM interviews WHERE candidate_id = ? AND status = 'in_progress' AND ended_at IS NULL AND last_activity_at > NOW() - INTERVAL 2 HOUR FOR UPDATE`. If an active interview exists, the edit is **rejected**. | Stale browser tabs, double clicks and race conditions (UI checks alone are never trusted). |

```mermaid
sequenceDiagram
    participant T1 as Tab A (edit profile)
    participant DB as MySQL (InnoDB)
    participant T2 as Tab B (start interview)

    T1->>DB: BEGIN
    T1->>DB: SELECT active interview ... FOR UPDATE
    Note over DB: matching rows / gap locked
    T2->>DB: INSERT interviews (in_progress)
    Note over T2,DB: waits for T1's lock
    T1->>DB: UPDATE candidates ...
    T1->>DB: COMMIT (lock released)
    DB-->>T2: INSERT proceeds
```

> The **2-hour activity window** prevents a candidate from being locked out forever by an abandoned interview (a closed tab that never reached `ended`).

### 2. Profile snapshot (audit integrity)

When the interview starts, the full profile is copied into `interviews.candidate_snapshot` (JSON). Even if the candidate later returns and edits their profile for a **new** interview, every past score stays tied to the exact profile it was evaluated against.

### 3. Idempotent, guarded state transitions

Every lifecycle update includes its precondition in the `WHERE` clause, so it can only happen once and only from a valid state:

```sql
UPDATE interviews
SET status = 'completed', ended_at = CURRENT_TIMESTAMP(6)
WHERE interview_id = ? AND status = 'in_progress' AND ended_at IS NULL;
```

- An interview **cannot be ended twice**, and `ended` and `completed` cannot overwrite each other.
- `update_interview_activity` fails (`rowcount = 0`) if the interview is no longer active, so **answers to a closed interview are rejected**.
- `ended_at = COALESCE(ended_at, CURRENT_TIMESTAMP(6))` keeps the original end time when results are saved later.

### 4. Exactly-once semantics in the app layer

| Operation | Guard |
|---|---|
| Interview row creation | Created only when `interview_id is None` → one row per session. |
| Resume processing | SHA-256 hash of the file → the same file is never re-parsed or re-saved on rerun. |
| Feedback generation | Cached in `feedback_text` → one LLM call per interview. |
| Result persistence | `interview_saved` flag → results written once. |

### 5. Atomic result save

Score, feedback and all Q&A rows are written in **one transaction**. Any failure (for example, the score can't be parsed) triggers a `ROLLBACK`, so the database never holds a half-saved interview. Because feedback is cached, the save can be retried on the next rerun **without another LLM call**.

### 6. Upsert with stable IDs

```sql
INSERT INTO candidates (...) VALUES (...)
ON DUPLICATE KEY UPDATE candidate_id = LAST_INSERT_ID(candidate_id), ...
```

A returning candidate (same email) reuses their row. The `LAST_INSERT_ID(candidate_id)` trick makes `cursor.lastrowid` return the **existing** ID, and `public_candidate_id` is never overwritten.

### 7. SQL injection safety

Every query uses **parameterised placeholders** (`%s`). No user input is ever concatenated into SQL.

---

<a id="fallbacks--error-handling"></a>
## 🛟 Fallbacks & Error Handling

| Failure | Behaviour |
|---|---|
| OpenAI key missing or empty | Client set to `None`; a clear configuration error is shown. The key is never logged. |
| Transient OpenAI/network errors | Client configured with `timeout=90s` and `max_retries=2`. |
| Scanned / empty resume | Rejected early: *"No readable text was found..."* |
| Unsupported file type | Blocked by the uploader (`pdf/docx/txt`) and validated again in code. |
| LLM returns malformed data | Prevented by **strict JSON Schema**; fields are then normalised (trimmed strings, `None` for blanks, lists guaranteed). |
| Ambiguous candidate name | The parser is instructed to return `null` instead of guessing (for example, not "Django"). |
| No summary produced | A fallback summary text is stored. |
| Idle / dropped MySQL connection | `conn.ping(reconnect=True, attempts=2)` before every use. |
| Any DB error | `ROLLBACK`, connection returned to the pool, user-friendly message, full traceback in the server log. |
| Duplicate email on edit | `IntegrityError` caught → *"This email is already linked to another candidate."* |
| Invalid edits | Validated before saving (required name, email format, phone format, numeric experience). |
| Starting with unsaved edits | *Confirm & Start* is disabled while any edit box is open. |
| LLM tries to ask a 6th question | Impossible, because the 5th answer ends the interview **in code** without calling the LLM. |
| Score missing from feedback | A tolerant regex handles Markdown and colour wrappers; if it still fails, nothing is saved (rollback) and the error is shown. |
| Wrong colour from the LLM | Impossible, because colours are applied **in Python** from fixed thresholds, not by the model. |

---

<a id="performance-optimisations"></a>
## ⚡ Performance Optimisations

Every expensive operation is wrapped in a `measure_time()` context manager that logs `[PERFORMANCE] <operation>: <seconds>`, so each optimisation below was measured, not guessed.

| # | Bottleneck | Optimisation | Impact |
|---|---|---|---|
| 1 | Presidio loaded spaCy `en_core_web_lg` (~550 MB) on **every app start**, even when unused | **Lazy import** inside a cached factory, switched to `en_core_web_sm` (~12 MB), and loaded only when `USE_PII_MASKING = True` | Removes the largest startup delay |
| 2 | Feedback **regenerated on every rerun** (any click → new 3,000-token LLM call; score changed each time) | Cached in `st.session_state.feedback_text` | 1 evaluation call per interview; stable scores; lower cost |
| 3 | New MySQL TCP + auth handshake for **every query** (including every answer) | `MySQLConnectionPool` (10 conns) cached with `@st.cache_resource` | DB calls drop from a full connect to an in-memory checkout |
| 4 | New `OpenAI()` client on every rerun | Cached client → reused HTTP connection pool | Fewer TLS handshakes |
| 5 | Long waits for LLM output | **Streaming** (`stream=True` + `st.write_stream`) for questions and feedback | Near-instant time-to-first-token for the user |
| 6 | Over-thinking on simple tasks | Reasoning effort tuned per task: `none` for questions, `low` for parsing and evaluation | Lower latency and cost |
| 7 | Re-parsing the same resume on rerun | SHA-256 file hash check | Parse once per file |
| 8 | Streamlit file watcher overhead | `.streamlit/config.toml`: `fileWatcherType = "none"` (prod), `fastReruns = true`, telemetry off | Less background work |

<!-- Tip: replace "Impact" with your own numbers from the [PERFORMANCE] logs, e.g. "Startup 14.2 s → 1.8 s". Real numbers are very persuasive in interviews. -->

---

<a id="llm--prompt-engineering"></a>
## 🧠 LLM & Prompt Engineering

| Call | API | Reasoning | Streaming | Output control |
|---|---|---|---|---|
| Resume parsing | Responses API | `low` | No | **Strict JSON Schema** (Structured Outputs) |
| First question | Chat Completions | `none` | No | `max_completion_tokens=400` |
| Follow-up questions | Chat Completions | `none` | Yes | Full conversation history as context |
| Evaluation | Chat Completions | `low` | Yes | Strict Markdown template + scoring formula |

**Prompt-design principles used**

- **Grounding:** the interviewer prompt contains the confirmed profile and is told *"Do not invent candidate experience or skills."*
- **One question at a time**, with follow-ups based on the candidate's actual answers.
- **Formula-based scoring** stops the model from "inventing" an overall score: `Overall = (Σ question scores / (n × 5)) × 10`, rounded to 1 decimal place.
- **Experience calibration:** expectations scale with the candidate's years of experience.
- **Anti-hallucination rules:** never fabricate questions, answers or technical details; a missing answer is scored as missing.
- **Deterministic post-processing:** **code**, not the model, owns the business rules (question cap, colour thresholds, dividers, score extraction). The LLM produces content; Python enforces rules.

**Colour thresholds (applied in Python)**

| Ratio | Per question (/5) | Overall (/10) | Colour |
|---|---|---|---|
| < 60 % | < 3.0 | < 6.0 | 🔴 Red: Poor |
| 60 – < 90 % | 3.0 – 4.4 | 6.0 – 8.9 | 🟠 Yellow: Average |
| ≥ 90 % | ≥ 4.5 | ≥ 9.0 | 🟢 Green: Good |

---

<a id="security--privacy"></a>
## 🛡️ Security & Privacy

- **Secrets** (OpenAI key, DB credentials) live in `.streamlit/secrets.toml`, which is **git-ignored**, and are never logged.
- **Parameterised SQL** everywhere.
- **Optional PII masking** (Presidio) before text is sent to the LLM, with custom recognisers for company names.
- **Public vs internal IDs:** internal keys are never exposed.
- **Server-side validation** of every edited field; database-level locks rather than UI-only checks.
- **Metadata-only logging** for normal operations (IDs, file-hash prefix, error types).

---

<a id="project-structure"></a>
## 📁 Project Structure

```
Interview_AI_BOT/
├── interview_app.py          # Streamlit application (all sections numbered & commented)
├── AI_Interview_icon.png     # Browser tab icon
├── requirements.txt
├── README.md
├── docs/                     # Screenshots / diagrams for this README
└── .streamlit/
    ├── config.toml           # Server/runtime settings (committed)
    └── secrets.toml          # API key + DB credentials (NOT committed)
```

**Code map (sections in `interview_app.py`)**

| Section | Responsibility |
|---|---|
| 1–4 | Imports, performance timer, page config, rerun diagnostics |
| 5 / 5.1 | Cached OpenAI client · cached MySQL connection pool |
| 6–10 | Session-state initialisation, callbacks, setup screen |
| 11–13 | Resume text extraction · JSON schema · LLM parsing |
| 14–15 | Lazy Presidio PII engine · masking |
| 16 / 16.0 / 16.1 | Candidate upsert · profile edit helpers + DB lock · review screen |
| 17 / 18 | Upload-resume path · manual-form path |
| 18.16–18.18 | Interview lifecycle DB functions · sidebar |
| 19–21 | Interview chat loop · completion · *Get Feedback* |
| 22 / 22.0 / 22.1 | Transactional result save · score colouring · evaluator prompt |
| 23–24 | Feedback rendering + persistence · run timing |

---

<a id="getting-started"></a>
## 🚀 Getting Started

<details>
<summary><b>Run it locally (5 steps)</b></summary>

**Prerequisites:** Python 3.10+, MySQL 8.x, an OpenAI API key.

```bash
# 1. Clone and install
git clone https://github.com/<your-username>/Interview_AI_BOT.git
cd Interview_AI_BOT
pip install -r requirements.txt
```

**2. Create the database:** run the SQL in [Database Design](#database-design).

**3. Add secrets** in `.streamlit/secrets.toml` (git-ignored):

```toml
OPENAI_API_KEY = "sk-..."

[mysql]
host = "localhost"
port = 3306
user = "ibot_user"
password = "********"
database = "ibot"
```

```bash
# 4. Run
streamlit run interview_app.py
```

**5. (Optional) PII masking:** set `USE_PII_MASKING = True` and run
`python -m spacy download en_core_web_sm`.

</details>

<a id="design-decisions--trade-offs"></a>
## ⚖️ Design Decisions & Trade-offs

Important concepts, with the reasoning behind each choice.

<details>
<summary><b>Why lock the profile at interview <i>start</i> instead of at the end?</b></summary>

The AI generates its questions **from** the profile. If the profile could change mid-interview, questions, answers and the score would refer to different data. Production assessment platforms work the same way: review and confirm first, then lock.
</details>

<details>
<summary><b>Why store a snapshot when the profile is already in <code>candidates</code>?</b></summary>

`candidates` is **mutable** and reused across interviews (upsert by email). The snapshot makes every interview **immutable and auditable**: you can always explain a score using the exact data the AI saw.
</details>

<details>
<summary><b>Why enforce the lock in the database if the UI already hides the buttons?</b></summary>

UI state can be stale (two tabs, double clicks, slow reruns). Only the database sees every request in order. `SELECT ... FOR UPDATE` inside the same transaction makes the check-then-update **atomic**.
</details>

<details>
<summary><b>Why apply score colours in Python instead of asking the LLM?</b></summary>

LLMs follow formatting rules *most* of the time. Business rules (thresholds, caps, layout) must be **100% deterministic**, so the model outputs plain numbers and code applies the rules. This also keeps the stored feedback clean (no colour markup in the database).
</details>

<details>
<summary><b>Why end the interview in code at answer 5 instead of telling the LLM "ask 5 questions"?</b></summary>

Prompt-only limits are not guaranteed. A counter in session state makes the cap exact, and skipping the final LLM call saves latency and cost.
</details>

<details>
<summary><b>Why a connection pool in a Streamlit app?</b></summary>

Streamlit reruns the script constantly, and the app writes to MySQL on every answer. Re-connecting each time adds a TCP + auth round-trip per action. A cached pool shared across sessions removes that cost; `ping(reconnect=True)` handles idle timeouts.
</details>

<details>
<summary><b>Why Structured Outputs (JSON Schema) for resume parsing?</b></summary>

Free-text JSON from an LLM can be malformed or missing keys. Strict schema mode guarantees valid JSON with exactly the required fields, which removes a whole class of parsing bugs.
</details>

<details>
<summary><b>Why Streamlit instead of React + FastAPI?</b></summary>

For an AI prototype, Streamlit gives chat UI, streaming and state management in pure Python, which keeps the focus on the LLM and data logic. The trade-off (single process, rerun model, limited UI control) is acceptable at this stage and is addressed in the roadmap.
</details>

---

<a id="known-limitations--roadmap"></a>
## 🧩 Known Limitations & Roadmap

Being upfront about limitations is a strength in interviews.

| Area | Current state | Planned improvement |
|---|---|---|
| Code organisation | Single-file Streamlit app | Split into `services/` (llm, db, resume, scoring) and `ui/` modules |
| Testing | Manual testing | `pytest` unit tests for validators, score regex, colouring and DB functions (with a test DB) |
| Feedback format | Score extracted from Markdown via regex | Use Structured Outputs for evaluation (JSON scores + text) → no regex dependency |
| OpenAI unavailable | Error shown at startup; later calls would still fail | Guard every LLM call when `client is None`; graceful "service unavailable" screen |
| Stale interviews | Ignored after 2 h by the lock query | Scheduled job to mark abandoned `in_progress` interviews as `ended` |
| Debug logging | Some debug prints include profile data | Structured logging with PII redaction and log levels |
| Authentication | None (identity = email) | Login / magic link; role-based recruiter dashboard |
| Scale | Single Streamlit process | Containerise (Docker), externalise state, move LLM/DB work behind an API |
| Analytics | Raw data in MySQL | Recruiter dashboard: score distributions, skill gaps, question difficulty |
| Interview modes | Text only | Voice interviews (speech-to-text), role-specific question banks, coding questions |

---

<a id="how-to-present-this-project-cheat-sheet"></a>
## 🎤 How to Present This Project (cheat sheet)

1. **Problem (30 s):** realistic, personalised interview practice with honest, structured feedback.
2. **Live demo (2 min):** upload a resume → edit a field on the review screen → answer 2–3 questions → show colour-coded feedback → show the rows in MySQL.
3. **Architecture (1 min):** walk through the [architecture diagram](#system-architecture) and the [state machine](#application-state-machine).
4. **Hardest problems solved (2 min):**
   - Race-safe profile locking with `SELECT ... FOR UPDATE` + a 2-hour stale window.
   - Exactly-once semantics in a framework that reruns the whole script on every click.
   - Moving business rules out of the LLM into deterministic code.
5. **Performance story (1 min):** "I instrumented every step, found the 550 MB spaCy model loading on startup, and fixed it with lazy loading" plus pooling and caching.
6. **What I'd do next (30 s):** modularise, add tests, Structured Outputs for evaluation, Docker.

---
