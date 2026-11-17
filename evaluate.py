# ==============================================================
# EVALUATE.PY - quality metrics for the AI Interview Bot
# ==============================================================
# Runs OUTSIDE Streamlit and never changes the app or its data.
# It reads what interview_app.py already stored in MySQL
# (candidates, interviews, interview_responses) and, optionally,
# the app's [PERFORMANCE] log lines. Most metrics are FREE.
#
#   python evaluate.py                    free metrics from MySQL
#   python evaluate.py --sample           free metrics on a built-in demo
#                                         interview (no MySQL, no OpenAI)
#   python evaluate.py --perf-log perf.log
#                                         + latency / failure metrics
#   python evaluate.py --resume-labels eval/resume_labels.json
#                                         + resume field accuracy
#   python evaluate.py --llm-tests        + PAID evaluator tests
#                                         (golden set, consistency,
#                                         experience calibration)
#
# PAID tests are protected three ways:
#   1. --max-calls (default 10): the run stops before going over it.
#   2. A plan with the number of calls is printed, and you must type
#      "yes" (or pass --yes) before anything is sent to OpenAI.
#   3. Every OpenAI answer is cached in eval/cache/, so running the
#      same test again costs nothing.
#
# Results are printed and saved to eval/results/metrics_<time>.json.
# Reports use interview / candidate IDs only - no names, emails or
# candidate answers are printed or saved.
# ==============================================================


# ==============================================================
# SECTION 1 - IMPORTS AND SETTINGS
# ==============================================================
import argparse
import ast
import hashlib
import json
import re
import statistics
import sys
import time
import tomllib
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

# STEP 1.1 - Files
BASE_DIR = Path(__file__).resolve().parent
APP_FILE = BASE_DIR / "interview_app.py"             # prompt + model are read from here
SECRETS_FILE = BASE_DIR / ".streamlit" / "secrets.toml"
EVAL_DIR = BASE_DIR / "eval"
GOLDEN_FILE = EVAL_DIR / "golden_transcripts.json"   # synthetic test interviews
CACHE_DIR = EVAL_DIR / "cache"                        # cached OpenAI answers
RESULTS_DIR = EVAL_DIR / "results"                    # saved metric reports

# STEP 1.2 - Thresholds (change here, explained in EVALUATION_METRICS.txt)
FORMULA_TOLERANCE = 0.1          # overall may differ from the formula by rounding only
GROUNDING_FLAG_THRESHOLD = 0.30  # summary words found in the real answer (below = flag)
REPETITION_THRESHOLD = 0.75      # question text similarity (above = repeated question)
EXPECTED_QUESTIONS = 5           # the app asks exactly 5 questions
CALIBRATION_JUNIOR = "1 year"    # experience values used by the calibration test
CALIBRATION_SENIOR = "8 years"

# STEP 1.3 - OpenAI settings for the PAID tests (same as interview_app.py 23.1)
FEEDBACK_REASONING_EFFORT = "low"
FEEDBACK_MAX_TOKENS = 3000
EST_INPUT_TOKENS_PER_CALL = 3000   # rough plan estimate shown before running
EST_OUTPUT_TOKENS_PER_CALL = 3000  # (upper bound = max_completion_tokens)

# Same closing message the app adds after answer 5 (interview_app.py 19.14)
APP_COMPLETION_MESSAGE = (
    'Thank you for your attempt, please click on "Get Feedback" '
    "option to view your results."
)


# ==============================================================
# SECTION 2 - READING THE APP'S SETTINGS (so tests match the app)
# ==============================================================

# STEP 2.1 - secrets.toml (read directly, no Streamlit needed)
def load_secrets():
    if not SECRETS_FILE.exists():
        raise FileNotFoundError(f"Secrets file not found: {SECRETS_FILE}")
    with SECRETS_FILE.open("rb") as file:
        return tomllib.load(file)


# STEP 2.2 - The app's exact evaluator prompt
# interview_app.py cannot be imported (it would start the Streamlit
# UI), so only the build_feedback_system_prompt() function is taken
# from its source code. The PAID tests therefore always use the SAME
# prompt as the live app - edit the prompt there, never here.
def load_feedback_prompt_builder():
    tree = ast.parse(APP_FILE.read_text(encoding="utf-8"))

    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "build_feedback_system_prompt"
        ):
            namespace = {}
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, str(APP_FILE), "exec"), namespace)
            return namespace["build_feedback_system_prompt"]

    raise RuntimeError(
        "build_feedback_system_prompt() was not found in interview_app.py"
    )


# STEP 2.3 - The app's model name (st.session_state["openai_model"] = "...")
def load_app_model_name():
    source = APP_FILE.read_text(encoding="utf-8")
    match = re.search(
        r'st\.session_state\["openai_model"\]\s*=\s*"([^"]+)"', source
    )
    if not match:
        raise RuntimeError("Model name not found in interview_app.py")
    return match.group(1)


# STEP 2.4 - MySQL connection (same settings as interview_app.py 5.1)
# ssl_* keys are optional: needed for the cloud database only.
def connect_mysql(secrets):
    import mysql.connector

    cfg = secrets["mysql"]
    ssl_options = {
        key: cfg[key]
        for key in ("ssl_ca", "ssl_verify_cert", "ssl_verify_identity")
        if key in cfg
    }
    # A relative certificate path is relative to this project folder
    if "ssl_ca" in ssl_options and not Path(ssl_options["ssl_ca"]).is_absolute():
        ssl_options["ssl_ca"] = str(BASE_DIR / ssl_options["ssl_ca"])

    return mysql.connector.connect(
        host=cfg["host"],
        port=int(cfg["port"]),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        connection_timeout=10,
        **ssl_options,
    )


# ==============================================================
# SECTION 3 - TEXT HELPERS
# ==============================================================

STOPWORDS = set("""
a an the and or but if then so to of in on at for from by with without as is are was
were be been being it its this that these those i you he she we they them their our
your my me his her what which who whom how why when where do does did done have has
had can could should would will shall may might must not no yes also just about into
over under than too very more most some any all each other such only own same both
""".split())

# Words that describe an answer instead of carrying its content
META_WORDS = set("""
candidate candidates answer answered answers explained explain explains mentioned
mention mentions described describe describes stated state states provided provide
provides discussed discuss said says noted note talked briefly brief response
responded overall question gave give gives example examples answer's
""".split())


def normalize_word(word):
    """Very small stemmer: 'configuring' / 'configured' -> 'configur'."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def content_words(text):
    """Meaningful words of a text (lower-case, stemmed, no stopwords)."""
    words = re.findall(r"[a-z0-9+#]+", (text or "").lower())
    return {
        normalize_word(word)
        for word in words
        if len(word) > 2 and word not in STOPWORDS and word not in META_WORDS
    }


def word_count(text):
    return len(re.findall(r"\S+", text or ""))


# Answers that mean "I am not answering this question"
SKIP_WORDS = re.compile(
    r"\b(skip|skipped|next|proceed|pass|move on|don'?t know|do not know|"
    r"no idea|not sure|idk|n/?a|no answer)\b",
    re.IGNORECASE,
)


def is_skip_answer(answer):
    """Empty answer, or a short answer that only asks to move on."""
    text = (answer or "").strip()
    if not text or re.fullmatch(r"[\W_]*", text):
        return True
    return word_count(text) <= 8 and bool(SKIP_WORDS.search(text))


# A summary that correctly says "no answer was given"
SKIP_ACKNOWLEDGED = re.compile(
    r"no (technical )?answer|not provided|did not (answer|provide)|"
    r"skipp|declin|no response|requested to (skip|proceed|move)|"
    r"asked to (skip|proceed|move)|without answering",
    re.IGNORECASE,
)


def percentile(values, pct):
    """Percentile with linear interpolation (pct 0-100)."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def rate(passed, total):
    return round(100 * passed / total, 1) if total else None


# ==============================================================
# SECTION 4 - PARSING THE STORED FEEDBACK TEXT
# ==============================================================
# The evaluator writes Markdown in a fixed structure (see the prompt
# in interview_app.py 22.8). These patterns read it back.

# Same pattern the app uses to save the score (interview_app.py 22.1)
OVERALL_SCORE_PATTERN = re.compile(
    r"Overall\s+Score\s*:?[^0-9\n]{0,40}?"
    r"(10(?:\.0+)?|[0-9](?:\.\d+)?)\s*/\s*10",
    re.IGNORECASE,
)
QUESTION_HEADER = re.compile(r"\*\*\s*Question\s+(\d+)\s*:\s*\*\*", re.IGNORECASE)
QUESTION_SCORE = re.compile(
    r"\*\*\s*Score\s*:\s*\*\*[^\n]*?(\d+(?:\.\d+)?)\s*/\s*5\b", re.IGNORECASE
)
ANSWER_SUMMARY = re.compile(
    r"\*\*\s*Candidate\s+Answer\s*:\s*\*\*(.*?)(?=\*\*\s*Score\s*:|\Z)",
    re.IGNORECASE | re.DOTALL,
)
REQUIRED_FIELDS = ["Candidate Answer", "Score", "Evaluation", "Expected Answer", "Improvement"]


def parse_feedback(feedback_text):
    """Split feedback into the overall score and one block per question."""
    text = feedback_text or ""
    overall_match = OVERALL_SCORE_PATTERN.search(text)

    # re.split with a group gives: [before, "1", block1, "2", block2, ...]
    parts = QUESTION_HEADER.split(text)
    questions = []

    for index in range(1, len(parts) - 1, 2):
        block = parts[index + 1]
        score_match = QUESTION_SCORE.search(block)
        summary_match = ANSWER_SUMMARY.search(block)
        missing = [
            label for label in REQUIRED_FIELDS
            if not re.search(
                r"\*\*\s*" + re.escape(label).replace(r"\ ", r"\s+") + r"\s*:\s*\*\*",
                block, re.IGNORECASE,
            )
        ]
        questions.append({
            "number": int(parts[index]),
            "score": float(score_match.group(1)) if score_match else None,
            "answer_summary": summary_match.group(1).strip() if summary_match else "",
            "missing_fields": missing,
        })

    return {
        "overall": float(overall_match.group(1)) if overall_match else None,
        "has_legend": bool(re.search(r"Score\s+Legend", text, re.IGNORECASE)),
        "questions": questions,
    }


# ==============================================================
# SECTION 5 - METRICS (all FREE: pure Python over stored data)
# ==============================================================

# --------------------------------------------------------------
# METRIC 1 - Formula adherence
# The prompt says: Overall = sum(question scores) / (n x 5) x 10,
# rounded to 1 decimal. A mismatch means the model invented the
# overall score instead of calculating it.
# --------------------------------------------------------------
def check_formula(parsed):
    scores = [q["score"] for q in parsed["questions"]]
    if parsed["overall"] is None or not scores or None in scores:
        return None   # cannot be checked (see format compliance)

    expected = round(sum(scores) / (len(scores) * 5) * 10, 1)
    difference = round(abs(parsed["overall"] - expected), 2)
    return {
        "reported": parsed["overall"],
        "expected": expected,
        "difference": difference,
        "pass": difference <= FORMULA_TOLERANCE,
    }


# --------------------------------------------------------------
# METRIC 2 - Format compliance
# Everything the app relies on is present: an extractable overall
# score (or saving fails), the legend, one block per question with
# all fields, and per-question scores between 0 and 5.
# --------------------------------------------------------------
def check_format(parsed, expected_questions):
    checks = {
        "overall_score_found": parsed["overall"] is not None,
        "score_legend_found": parsed["has_legend"],
        "question_count_ok": len(parsed["questions"]) == expected_questions,
        "all_fields_present": all(not q["missing_fields"] for q in parsed["questions"]),
        "scores_in_range": all(
            q["score"] is not None and 0 <= q["score"] <= 5
            for q in parsed["questions"]
        ),
    }
    checks["pass"] = all(checks.values())
    return checks


# --------------------------------------------------------------
# METRICS 3 + 4 - Zero-for-skip and answer-summary grounding
# 3: a skipped answer must score 0/5 and the summary must say so.
# 4: for real answers, the share of summary words that appear in
#    the candidate's actual answer. Low = possibly invented summary.
# --------------------------------------------------------------
def check_answers(parsed, answers):
    by_number = {q["number"]: q for q in parsed["questions"]}
    skip_results, grounding_scores, flagged = [], [], []

    for number, answer in answers.items():
        block = by_number.get(number)
        if block is None:
            continue

        if is_skip_answer(answer):
            skip_results.append({
                "question": number,
                "score": block["score"],
                "scored_zero": block["score"] == 0,
                "summary_acknowledges_skip": bool(
                    SKIP_ACKNOWLEDGED.search(block["answer_summary"])
                ),
            })
            continue

        summary_words = content_words(block["answer_summary"])
        if not summary_words:
            continue
        grounding = len(summary_words & content_words(answer)) / len(summary_words)
        grounding_scores.append(grounding)
        if grounding < GROUNDING_FLAG_THRESHOLD:
            flagged.append({"question": number, "grounding": round(grounding, 2)})

    return skip_results, grounding_scores, flagged


# --------------------------------------------------------------
# METRICS 5-8 - Question quality
# 5 one-question rule   6 personalisation   7 repetition   8 length
# --------------------------------------------------------------
def profile_terms(snapshot):
    """Skills, companies, roles and project names from the profile."""
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except json.JSONDecodeError:
            snapshot = {}
    snapshot = snapshot or {}
    terms = set()

    def add(value):
        for piece in re.split(r"[,/;|\n]", str(value or "")):
            piece = piece.strip().lower()
            if 2 <= len(piece) <= 40:
                terms.add(piece)

    skills = snapshot.get("skills")
    for skill in skills if isinstance(skills, list) else [skills]:
        add(skill)

    for key in ("company", "current_role", "position"):
        add(snapshot.get(key))

    for job in snapshot.get("experience") or []:
        if isinstance(job, dict):
            add(job.get("company"))
            add(job.get("role"))

    # Project descriptions are long: use the name before " - " / ":" / "("
    for project in snapshot.get("projects") or []:
        name = re.split(r"\s[-–:]\s|:|\(", str(project))[0].strip()
        if word_count(name) <= 6:
            add(name)

    return terms


def check_questions(questions, snapshot):
    """questions: {question_number: question text}"""
    terms = profile_terms(snapshot)
    texts = [questions[n] for n in sorted(questions)]

    multi = [
        n for n in sorted(questions) if questions[n].count("?") > 1
    ]

    personalised = []
    for n in sorted(questions):
        lowered = questions[n].lower()
        matched = sorted(
            term for term in terms
            if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", lowered)
        )
        personalised.append({"question": n, "matched_terms": matched})

    repeated = []
    numbers = sorted(questions)
    for i in range(len(numbers)):
        for j in range(i + 1, len(numbers)):
            similarity = SequenceMatcher(
                None, texts[i].lower(), texts[j].lower()
            ).ratio()
            if similarity >= REPETITION_THRESHOLD:
                repeated.append({
                    "questions": [numbers[i], numbers[j]],
                    "similarity": round(similarity, 2),
                })

    lengths = [word_count(text) for text in texts]
    return {
        "count": len(texts),
        "multi_question": multi,
        "personalised": personalised,
        "personalised_count": sum(1 for p in personalised if p["matched_terms"]),
        "profile_terms_available": len(terms),
        "repeated_pairs": repeated,
        "words_avg": round(statistics.mean(lengths), 1) if lengths else None,
        "words_max": max(lengths) if lengths else None,
    }


# --------------------------------------------------------------
# METRIC 9 - Resume parsing: "not invented" check (no labels needed)
# Email, phone, current company and name stored by the LLM parser
# must literally appear in the extracted resume text.
# --------------------------------------------------------------
def digits_only(value):
    return re.sub(r"\D", "", str(value or ""))


def squash(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def check_resume_not_invented(structured, resume_text):
    text = squash(resume_text)
    text_digits = digits_only(resume_text)
    results = {}

    for field in ("name", "email", "company"):
        value = squash(structured.get(field))
        if value:
            results[field] = value in text

    phone = digits_only(structured.get("phone_number") or structured.get("phone"))
    if len(phone) >= 7:
        # Compare the last 10 digits: the app adds "+91-" style prefixes
        results["phone"] = phone[-10:] in text_digits

    return results


# --------------------------------------------------------------
# METRIC 10 - Resume parsing accuracy against hand-made labels
# --------------------------------------------------------------
def normalize_skill(skill):
    return re.sub(r"\s+", " ", str(skill).strip().lower())


def check_resume_against_label(structured, label):
    result = {}

    for field in ("name", "email"):
        if label.get(field) is not None:
            result[f"{field}_correct"] = squash(structured.get(field)) == squash(label[field])

    if label.get("phone") is not None:
        parsed = digits_only(structured.get("phone_number") or structured.get("phone"))
        result["phone_correct"] = parsed[-10:] == digits_only(label["phone"])[-10:]

    if label.get("total_experience") is not None:
        try:
            parsed_years = float(structured.get("total_experience"))
            result["experience_error_years"] = round(
                abs(parsed_years - float(label["total_experience"])), 2
            )
        except (TypeError, ValueError):
            result["experience_error_years"] = None

    if label.get("skills") is not None:
        parsed_skills = structured.get("skills") or []
        if isinstance(parsed_skills, str):
            parsed_skills = parsed_skills.split(",")
        parsed_set = {normalize_skill(s) for s in parsed_skills if str(s).strip()}
        true_set = {normalize_skill(s) for s in label["skills"]}
        hits = len(parsed_set & true_set)
        precision = hits / len(parsed_set) if parsed_set else 0.0
        recall = hits / len(true_set) if true_set else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result.update({
            "skills_precision": round(precision, 2),
            "skills_recall": round(recall, 2),
            "skills_f1": round(f1, 2),
        })

    return result


# ==============================================================
# SECTION 6 - EVALUATING STORED INTERVIEWS (FREE)
# ==============================================================

def evaluate_interview(interview):
    """All free metrics for ONE completed interview.

    interview = {"interview_id", "feedback", "snapshot",
                 "questions": {n: text}, "answers": {n: text}}
    """
    parsed = parse_feedback(interview["feedback"])
    expected = len(interview["answers"]) or EXPECTED_QUESTIONS
    skip_results, grounding, flagged = check_answers(parsed, interview["answers"])

    return {
        "interview_id": interview["interview_id"],
        "formula": check_formula(parsed),
        "format": check_format(parsed, expected),
        "skips": skip_results,
        "grounding_scores": grounding,
        "grounding_flagged": flagged,
        "questions": check_questions(interview["questions"], interview["snapshot"]),
        "question_scores": [q["score"] for q in parsed["questions"]],
    }


def summarize_interviews(results):
    """Combine per-interview results into the headline numbers."""
    formula = [r["formula"] for r in results if r["formula"] is not None]
    formats = [r["format"] for r in results]
    skips = [s for r in results for s in r["skips"]]
    grounding = [g for r in results for g in r["grounding_scores"]]
    questions = [r["questions"] for r in results]
    total_questions = sum(q["count"] for q in questions)

    return {
        "interviews_evaluated": len(results),
        "formula_adherence_rate": rate(sum(f["pass"] for f in formula), len(formula)),
        "formula_checked": len(formula),
        "formula_max_difference": max((f["difference"] for f in formula), default=None),
        "format_compliance_rate": rate(sum(f["pass"] for f in formats), len(formats)),
        "format_failures_by_check": {
            check: sum(1 for f in formats if not f[check])
            for check in ("overall_score_found", "score_legend_found",
                          "question_count_ok", "all_fields_present", "scores_in_range")
        },
        "skipped_answers": len(skips),
        "zero_for_skip_rate": rate(sum(s["scored_zero"] for s in skips), len(skips)),
        "skip_acknowledged_rate": rate(
            sum(s["summary_acknowledges_skip"] for s in skips), len(skips)
        ),
        "summary_grounding_avg": round(statistics.mean(grounding), 2) if grounding else None,
        "summaries_flagged_low_grounding": sum(len(r["grounding_flagged"]) for r in results),
        "one_question_rule_rate": rate(
            total_questions - sum(len(q["multi_question"]) for q in questions),
            total_questions,
        ),
        "personalisation_rate": rate(
            sum(q["personalised_count"] for q in questions), total_questions
        ),
        "repeated_question_pairs": sum(len(q["repeated_pairs"]) for q in questions),
        "question_words_avg": round(
            statistics.mean([q["words_avg"] for q in questions if q["words_avg"]]), 1
        ) if any(q["words_avg"] for q in questions) else None,
        "question_words_max": max((q["words_max"] or 0 for q in questions), default=None),
    }


# ==============================================================
# SECTION 7 - LOADING DATA FROM MYSQL (read-only)
# ==============================================================

def load_from_mysql(secrets, last_n=None):
    conn = connect_mysql(secrets)
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT interview_id, status, overall_score, overall_feedback,
                   created_at, ended_at, candidate_snapshot
            FROM interviews
            ORDER BY interview_id
            """
        )
        interviews = cursor.fetchall()
        if last_n:
            interviews = interviews[-last_n:]

        cursor.execute(
            """
            SELECT interview_id, question_number, ai_question, user_answer
            FROM interview_responses
            ORDER BY interview_id, question_number
            """
        )
        responses = cursor.fetchall()

        cursor.execute(
            """
            SELECT candidate_id, setup_mode, extracted_resume_text, structured_data
            FROM candidates
            ORDER BY candidate_id
            """
        )
        candidates = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    return interviews, responses, candidates


def build_interview_records(interviews, responses):
    """Interviews that have feedback AND saved question/answer pairs."""
    by_interview = {}
    for row in responses:
        record = by_interview.setdefault(row["interview_id"], {"questions": {}, "answers": {}})
        record["questions"][row["question_number"]] = row["ai_question"]
        record["answers"][row["question_number"]] = row["user_answer"]

    records = []
    for row in interviews:
        qa = by_interview.get(row["interview_id"])
        if row["overall_feedback"] and qa:
            records.append({
                "interview_id": row["interview_id"],
                "feedback": row["overall_feedback"],
                "snapshot": row["candidate_snapshot"],
                "questions": qa["questions"],
                "answers": qa["answers"],
            })
    return records


# --------------------------------------------------------------
# METRIC 11 - System / product metrics from the interviews table
# --------------------------------------------------------------
def system_metrics(interviews):
    statuses = {}
    for row in interviews:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1

    finished = statuses.get("completed", 0) + statuses.get("ended", 0)

    durations = []
    for row in interviews:
        if row["status"] == "completed" and row["created_at"] and row["ended_at"]:
            minutes = (row["ended_at"] - row["created_at"]).total_seconds() / 60
            if minutes >= 0:
                durations.append(minutes)

    scores = [float(row["overall_score"]) for row in interviews if row["overall_score"] is not None]
    buckets = {"0-2": 0, "2-4": 0, "4-6": 0, "6-8": 0, "8-10": 0}
    for score in scores:
        key = ("0-2" if score < 2 else "2-4" if score < 4 else
               "4-6" if score < 6 else "6-8" if score < 8 else "8-10")
        buckets[key] += 1

    return {
        "interviews_total": len(interviews),
        "status_counts": statuses,
        "completion_rate": rate(statuses.get("completed", 0), finished),
        "feedback_saved": sum(1 for row in interviews if row["overall_feedback"]),
        "duration_minutes_median": round(statistics.median(durations), 1) if durations else None,
        "duration_minutes_p95": round(percentile(durations, 95), 1) if durations else None,
        "overall_score_avg": round(statistics.mean(scores), 2) if scores else None,
        "overall_score_distribution": buckets,
    }


def resume_metrics(candidates, labels):
    not_invented = {}
    for row in candidates:
        if row["setup_mode"] != "Upload Resume" or not row["extracted_resume_text"]:
            continue
        structured = row["structured_data"]
        if isinstance(structured, str):
            structured = json.loads(structured)
        for field, found in check_resume_not_invented(structured or {}, row["extracted_resume_text"]).items():
            stats = not_invented.setdefault(field, {"checked": 0, "found_in_resume": 0})
            stats["checked"] += 1
            stats["found_in_resume"] += int(found)

    for stats in not_invented.values():
        stats["rate"] = rate(stats["found_in_resume"], stats["checked"])

    accuracy = None
    if labels is not None:
        structured_by_id = {}
        for row in candidates:
            data = row["structured_data"]
            structured_by_id[row["candidate_id"]] = (
                json.loads(data) if isinstance(data, str) else (data or {})
            )
        per_candidate = [
            {"candidate_id": label["candidate_id"],
             **check_resume_against_label(structured_by_id[label["candidate_id"]], label)}
            for label in labels
            if label.get("candidate_id") in structured_by_id
        ]
        accuracy = {"labelled_candidates": len(per_candidate), "per_candidate": per_candidate}
        for key in ("name_correct", "email_correct", "phone_correct"):
            values = [c[key] for c in per_candidate if key in c]
            accuracy[key.replace("_correct", "_accuracy")] = rate(sum(values), len(values))
        errors = [c["experience_error_years"] for c in per_candidate
                  if c.get("experience_error_years") is not None]
        accuracy["experience_mae_years"] = round(statistics.mean(errors), 2) if errors else None
        for key in ("skills_precision", "skills_recall", "skills_f1"):
            values = [c[key] for c in per_candidate if key in c]
            accuracy[key + "_avg"] = round(statistics.mean(values), 2) if values else None

    return {"not_invented": not_invented, "accuracy": accuracy}


# ==============================================================
# SECTION 8 - LATENCY AND FAILURES FROM THE APP LOG (FREE)
# ==============================================================
# Save the app's terminal output to a file, e.g. in PowerShell:
#   streamlit run interview_app.py 2>&1 | Tee-Object -FilePath perf.log

PERF_LINE = re.compile(r"\[PERFORMANCE\] (.+?):\s*([\d.]+) seconds")
RERUN_LINE = re.compile(r"\[PERFORMANCE\] Script run \d+ completed in ([\d.]+) seconds")
FAILURE_MARKERS = {
    "score_not_extracted": "Overall score was not found",
    "interview_save_failed": "Interview save failed",
    "first_question_failed": "First question failed",
    "resume_processing_failed": "Resume processing failed",
    "openai_client_failed": "OpenAI client initialization failed",
    "python_tracebacks": "Traceback (most recent call last)",
}


def perf_log_metrics(log_path):
    timings, failures = {}, {name: 0 for name in FAILURE_MARKERS}

    for line in Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines():
        rerun = RERUN_LINE.search(line)
        if rerun:
            timings.setdefault("Script rerun (whole page)", []).append(float(rerun.group(1)))
            continue
        match = PERF_LINE.search(line)
        if match:
            timings.setdefault(match.group(1).strip(), []).append(float(match.group(2)))
        for name, marker in FAILURE_MARKERS.items():
            if marker in line:
                failures[name] += 1

    return {
        "latency_seconds": {
            name: {
                "count": len(values),
                "p50": round(percentile(values, 50), 3),
                "p95": round(percentile(values, 95), 3),
                "max": round(max(values), 3),
            }
            for name, values in sorted(timings.items())
        },
        "failures": failures,
    }


# ==============================================================
# SECTION 9 - PAID EVALUATOR TESTS (OpenAI, capped and cached)
# ==============================================================
# Uses synthetic interviews from eval/golden_transcripts.json, so no
# real candidate data is sent to OpenAI.
#   Golden ranking       : all_skipped < weak < decent < excellent,
#                          and all_skipped must score exactly 0/10.
#   Consistency          : the same transcript scored N times -> std dev.
#   Experience calibration: same answers, 1 vs 8 years of experience ->
#                          the junior should score the same or higher.

class BudgetExceeded(Exception):
    pass


class FeedbackRunner:
    """Calls the evaluator exactly like the app does, with a cache."""

    def __init__(self, api_key, model, prompt_builder, max_calls):
        self.api_key = api_key
        self.model = model
        self.prompt_builder = prompt_builder
        self.max_calls = max_calls
        self.calls_made = 0
        self.cache_hits = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._client = None

    def _cache_file(self, experience, history, run):
        key = json.dumps([self.model, self.prompt_builder(experience), history, run])
        return CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")

    def is_cached(self, experience, history, run):
        return self._cache_file(experience, history, run).exists()

    def feedback(self, experience, history, run=1):
        cache_file = self._cache_file(experience, history, run)
        if cache_file.exists():
            self.cache_hits += 1
            return json.loads(cache_file.read_text(encoding="utf-8"))["feedback"]

        if self.calls_made >= self.max_calls:
            raise BudgetExceeded(f"--max-calls {self.max_calls} reached")

        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, timeout=120, max_retries=1)

        started = time.perf_counter()
        # Same request as interview_app.py 23.1 (not streamed, so the
        # token usage is returned and can be reported)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.prompt_builder(experience)},
                {
                    "role": "user",
                    "content": (
                        "This is the interview you need to evaluate. "
                        "You are only a tool for evaluation and should "
                        f"not engage in conversation : {history}"
                    ),
                },
            ],
            reasoning_effort=FEEDBACK_REASONING_EFFORT,
            max_completion_tokens=FEEDBACK_MAX_TOKENS,
        )
        self.calls_made += 1

        usage = response.usage
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

        feedback = response.choices[0].message.content or ""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "model": self.model,
            "experience": experience,
            "run": run,
            "seconds": round(time.perf_counter() - started, 2),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "feedback": feedback,
        }, indent=2), encoding="utf-8")
        return feedback


def transcript_to_history(transcript):
    """Same text format the app sends: 'role : content' per line,
    ending with the app's fixed closing message."""
    lines = []
    for turn in transcript["turns"]:
        lines.append(f"assistant : {turn['question']}")
        lines.append(f"user : {turn['answer']}")
    lines.append(f"assistant : {APP_COMPLETION_MESSAGE}")
    return "\n".join(lines)


def plan_llm_tests(golden, consistency_id, consistency_runs, calibration_id):
    """List of (test name, transcript id, experience, run number)."""
    plan = [("golden", t["id"], t["experience"], 1) for t in golden["transcripts"]]
    by_id = {t["id"]: t for t in golden["transcripts"]}
    for run in range(2, consistency_runs + 1):   # run 1 = the golden call
        plan.append(("consistency", consistency_id, by_id[consistency_id]["experience"], run))
    plan.append(("calibration", calibration_id, CALIBRATION_JUNIOR, 1))
    plan.append(("calibration", calibration_id, CALIBRATION_SENIOR, 1))
    return plan


def run_llm_tests(runner, golden, plan):
    by_id = {t["id"]: t for t in golden["transcripts"]}
    scores = {}   # (test, id, experience, run) -> parsed

    for test, transcript_id, experience, run in plan:
        history = transcript_to_history(by_id[transcript_id])
        text = runner.feedback(experience, history, run)
        parsed = parse_feedback(text)
        scores[(test, transcript_id, experience, run)] = {
            "overall": parsed["overall"],
            "formula": check_formula(parsed),
            "format_ok": check_format(parsed, len(by_id[transcript_id]["turns"]))["pass"],
        }

    # Golden ranking
    golden_scores = {
        t["id"]: scores[("golden", t["id"], t["experience"], 1)]["overall"]
        for t in golden["transcripts"]
    }
    order = golden["expected_order"]
    ranked = [golden_scores[i] for i in order]
    ranking_ok = None not in ranked and all(a < b for a, b in zip(ranked, ranked[1:]))
    zero_id = golden["must_score_zero"]

    # Consistency (run 1 is the golden call for the same transcript)
    consistency_id = next(p[1] for p in plan if p[0] == "consistency") \
        if any(p[0] == "consistency" for p in plan) else None
    consistency = None
    if consistency_id:
        runs = [golden_scores[consistency_id]] + [
            v["overall"] for k, v in scores.items()
            if k[0] == "consistency" and k[1] == consistency_id
        ]
        runs = [r for r in runs if r is not None]
        consistency = {
            "transcript": consistency_id,
            "scores": runs,
            "std_dev": round(statistics.pstdev(runs), 2) if len(runs) > 1 else None,
            "range": round(max(runs) - min(runs), 1) if runs else None,
        }

    # Calibration
    calibration_id = next(p[1] for p in plan if p[0] == "calibration")
    junior = scores[("calibration", calibration_id, CALIBRATION_JUNIOR, 1)]["overall"]
    senior = scores[("calibration", calibration_id, CALIBRATION_SENIOR, 1)]["overall"]

    formula_results = [v["formula"] for v in scores.values() if v["formula"]]
    return {
        "golden_scores": golden_scores,
        "expected_order": order,
        "ranking_correct": ranking_ok,
        "all_skipped_scored_zero": golden_scores.get(zero_id) == 0,
        "consistency": consistency,
        "calibration": {
            "transcript": calibration_id,
            f"score_with_{CALIBRATION_JUNIOR.replace(' ', '_')}": junior,
            f"score_with_{CALIBRATION_SENIOR.replace(' ', '_')}": senior,
            "junior_scored_same_or_higher": (
                junior is not None and senior is not None and junior >= senior
            ),
        },
        "llm_formula_adherence_rate": rate(
            sum(f["pass"] for f in formula_results), len(formula_results)
        ),
        "llm_format_compliance_rate": rate(
            sum(v["format_ok"] for v in scores.values()), len(scores)
        ),
        "openai_calls_made": runner.calls_made,
        "cache_hits": runner.cache_hits,
        "tokens_in": runner.tokens_in,
        "tokens_out": runner.tokens_out,
    }


# ==============================================================
# SECTION 10 - BUILT-IN SAMPLE INTERVIEW (for --sample)
# ==============================================================
# A made-up interview with deliberate problems, so every metric has
# something to show: question 3 is skipped but scored 1/5, question 5
# repeats question 1, and the overall score does not match the
# question scores.

SAMPLE_INTERVIEW = {
    "interview_id": "SAMPLE",
    "snapshot": {
        "skills": ["Java", "Spring Boot", "REST APIs", "MySQL"],
        "company": "Capgemini",
        "current_role": "Software Engineer",
        "projects": ["RBC Banking Portal - payments microservices"],
        "total_experience": 3,
    },
    "questions": {
        1: "Can you describe your role in the RBC Banking Portal project at Capgemini?",
        2: "How do you secure REST APIs in Spring Boot?",
        3: "How would you tune a slow MySQL query?",
        4: "What is the difference between @Component and @Bean? When would you use each?",
        5: "Could you describe your role in the RBC Banking Portal project at Capgemini?",
    },
    "answers": {
        1: "I built payment microservices with Spring Boot and integrated them with REST APIs.",
        2: "I use Spring Security with JWT tokens, role based access and HTTPS.",
        3: "skip",
        4: "@Component marks a class for scanning; @Bean is a method in a configuration class.",
        5: "Same as before, I worked on payment microservices.",
    },
    "feedback": """**Overall Score:** 7.0/10

**Feedback:** Solid answers on Spring Security; one question skipped.

**Score Legend:** :red[Red — Poor] | :orange[Yellow — Average] | :green[Green — Good]

**Question 1:** Can you describe your role in the RBC Banking Portal project at Capgemini?

**Candidate Answer:** Built payment microservices with Spring Boot and REST APIs.

**Score:** 3.5/5

**Evaluation:** Clear but brief.

**Expected Answer:** Responsibilities, stack, impact.

**Improvement:** Add measurable outcomes.

**Question 2:** How do you secure REST APIs in Spring Boot?

**Candidate Answer:** Uses Spring Security with JWT tokens and role based access.

**Score:** 4/5

**Evaluation:** Good coverage.

**Expected Answer:** Filters, JWT validation, method security.

**Improvement:** Mention token expiry handling.

**Question 3:** How would you tune a slow MySQL query?

**Candidate Answer:** No technical answer was provided; the candidate skipped the question.

**Score:** 1/5

**Evaluation:** Not answered.

**Expected Answer:** EXPLAIN, indexes, query rewrite.

**Improvement:** Attempt an answer.

**Question 4:** What is the difference between @Component and @Bean? When would you use each?

**Candidate Answer:** Explained Kubernetes deployment pipelines and Docker image caching.

**Score:** 3/5

**Evaluation:** Partly correct.

**Expected Answer:** Scanning vs explicit factory methods.

**Improvement:** Give an example.

**Question 5:** Could you describe your role in the RBC Banking Portal project at Capgemini?

**Candidate Answer:** Worked on payment microservices.

**Score:** 2/5

**Evaluation:** Repeats the earlier answer.

**Expected Answer:** New details.

**Improvement:** Add depth.
""",
}


# ==============================================================
# SECTION 11 - REPORT
# ==============================================================

def print_section(title):
    print("\n" + "=" * 62)
    print(title)
    print("=" * 62)


def print_interview_report(summary, per_interview):
    print_section("EVALUATOR + QUESTION QUALITY (free)")
    lines = [
        ("Interviews evaluated", summary["interviews_evaluated"]),
        ("1  Formula adherence rate (%)", summary["formula_adherence_rate"]),
        ("   Largest overall-vs-formula difference", summary["formula_max_difference"]),
        ("2  Format compliance rate (%)", summary["format_compliance_rate"]),
        ("   Failures by check", summary["format_failures_by_check"]),
        ("3  Skipped answers found", summary["skipped_answers"]),
        ("   Zero-for-skip rate (%)", summary["zero_for_skip_rate"]),
        ("   Skip acknowledged in summary (%)", summary["skip_acknowledged_rate"]),
        ("4  Summary grounding (avg 0-1)", summary["summary_grounding_avg"]),
        ("   Summaries flagged (possibly invented)", summary["summaries_flagged_low_grounding"]),
        ("5  One-question rule (%)", summary["one_question_rule_rate"]),
        ("6  Personalisation rate (%)", summary["personalisation_rate"]),
        ("7  Repeated question pairs", summary["repeated_question_pairs"]),
        ("8  Question words (avg / max)",
         f'{summary["question_words_avg"]} / {summary["question_words_max"]}'),
    ]
    for label, value in lines:
        print(f"{label:<44} {value}")

    # Details for anything that failed, by interview ID only
    for result in per_interview:
        problems = []
        if result["formula"] and not result["formula"]["pass"]:
            f = result["formula"]
            problems.append(f"formula: reported {f['reported']} vs expected {f['expected']}")
        failed_checks = [k for k, v in result["format"].items() if k != "pass" and not v]
        if failed_checks:
            problems.append("format: " + ", ".join(failed_checks))
        for skip in result["skips"]:
            if not skip["scored_zero"]:
                problems.append(f"Q{skip['question']} skipped but scored {skip['score']}/5")
        for flag in result["grounding_flagged"]:
            problems.append(f"Q{flag['question']} summary grounding {flag['grounding']}")
        if result["questions"]["multi_question"]:
            problems.append(f"multiple questions in Q{result['questions']['multi_question']}")
        for pair in result["questions"]["repeated_pairs"]:
            problems.append(f"Q{pair['questions'][0]} and Q{pair['questions'][1]} "
                            f"repeat (similarity {pair['similarity']})")
        if problems:
            print(f"\n  Interview {result['interview_id']}:")
            for problem in problems:
                print(f"    - {problem}")


def print_dict_section(title, data):
    print_section(title)
    print(json.dumps(data, indent=2, default=str))


def save_results(results):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"metrics_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return path


# ==============================================================
# SECTION 12 - MAIN
# ==============================================================

def parse_args():
    parser = argparse.ArgumentParser(description="AI Interview Bot evaluation metrics")
    parser.add_argument("--sample", action="store_true",
                        help="Use the built-in demo interview (no MySQL, no OpenAI).")
    parser.add_argument("--last", type=int, default=None,
                        help="Only evaluate the last N interviews.")
    parser.add_argument("--perf-log", default=None,
                        help="App terminal log with [PERFORMANCE] lines.")
    parser.add_argument("--resume-labels", default=None,
                        help="JSON file with hand-checked resume fields.")
    parser.add_argument("--llm-tests", action="store_true",
                        help="Run the PAID evaluator tests (golden, consistency, calibration).")
    parser.add_argument("--max-calls", type=int, default=10,
                        help="Hard limit on new OpenAI calls (default 10).")
    parser.add_argument("--consistency-runs", type=int, default=3,
                        help="How many times the consistency transcript is scored (default 3).")
    parser.add_argument("--consistency-id", default="decent",
                        help="Golden transcript used for consistency (default: decent).")
    parser.add_argument("--calibration-id", default="decent",
                        help="Golden transcript used for calibration (default: decent).")
    parser.add_argument("--model", default=None,
                        help="Override the model (default: the one in interview_app.py).")
    parser.add_argument("--price-in", type=float, default=None,
                        help="USD per 1M input tokens (to print an exact cost).")
    parser.add_argument("--price-out", type=float, default=None,
                        help="USD per 1M output tokens (to print an exact cost).")
    parser.add_argument("--yes", action="store_true",
                        help="Do not ask for confirmation before PAID calls.")
    return parser.parse_args()


def main():
    args = parse_args()
    results = {"generated_at": datetime.now().isoformat(timespec="seconds")}
    secrets = None

    # ---- Free metrics: stored interviews ----
    if args.sample:
        records = [SAMPLE_INTERVIEW]
        interviews = candidates = None
        results["source"] = "built-in sample interview"
    else:
        secrets = load_secrets()
        interviews, responses, candidates = load_from_mysql(secrets, args.last)
        records = build_interview_records(interviews, responses)
        results["source"] = "MySQL"

    per_interview = [evaluate_interview(record) for record in records]
    if per_interview:
        summary = summarize_interviews(per_interview)
        results["interview_metrics"] = summary
        results["interview_details"] = per_interview
        print_interview_report(summary, per_interview)
    else:
        print("\nNo completed interviews with saved feedback and answers yet.")

    if interviews is not None:
        results["system_metrics"] = system_metrics(interviews)
        print_dict_section("11  SYSTEM / PRODUCT METRICS (free)", results["system_metrics"])

    if candidates is not None:
        labels = None
        if args.resume_labels:
            labels = json.loads(Path(args.resume_labels).read_text(encoding="utf-8"))
        results["resume_metrics"] = resume_metrics(candidates, labels)
        print_dict_section("9-10  RESUME PARSING (free)", results["resume_metrics"])

    if args.perf_log:
        results["performance"] = perf_log_metrics(args.perf_log)
        print_dict_section("12-13  LATENCY + FAILURES FROM LOG (free)", results["performance"])

    # ---- PAID tests ----
    if args.llm_tests:
        golden = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
        secrets = secrets or load_secrets()
        runner = FeedbackRunner(
            api_key=secrets["OPENAI_API_KEY"],
            model=args.model or load_app_model_name(),
            prompt_builder=load_feedback_prompt_builder(),
            max_calls=args.max_calls,
        )
        by_id = {t["id"]: t for t in golden["transcripts"]}
        plan = plan_llm_tests(golden, args.consistency_id,
                              args.consistency_runs, args.calibration_id)
        new_calls = sum(
            1 for _, tid, exp, run in plan
            if not runner.is_cached(exp, transcript_to_history(by_id[tid]), run)
        )

        print_section("14-16  PAID EVALUATOR TESTS - PLAN")
        print(f"Model                 : {runner.model}")
        print(f"Planned calls         : {len(plan)} ({len(plan) - new_calls} cached = free)")
        print(f"NEW OpenAI calls      : {new_calls}  (limit --max-calls {args.max_calls})")
        print(f"Estimated tokens      : <= {new_calls * EST_INPUT_TOKENS_PER_CALL:,} in, "
              f"<= {new_calls * EST_OUTPUT_TOKENS_PER_CALL:,} out")

        if new_calls > args.max_calls:
            print("\nStopped: more new calls than --max-calls. Raise the limit or "
                  "lower --consistency-runs.")
            sys.exit(1)

        if new_calls and not args.yes:
            if input("Type 'yes' to send these calls to OpenAI: ").strip().lower() != "yes":
                print("Cancelled - nothing was sent.")
                sys.exit(0)

        results["llm_tests"] = run_llm_tests(runner, golden, plan)
        if args.price_in is not None and args.price_out is not None:
            results["llm_tests"]["cost_usd"] = round(
                runner.tokens_in / 1e6 * args.price_in
                + runner.tokens_out / 1e6 * args.price_out, 4
            )
        print_dict_section("14-16  PAID EVALUATOR TESTS - RESULTS", results["llm_tests"])

    path = save_results(results)
    print(f"\nSaved: {path}")


if __name__ == "__main__":
    main()
