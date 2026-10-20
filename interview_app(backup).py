# ============================================================
# 1. IMPORT REQUIRED LIBRARIES
# ============================================================
from openai import OpenAI
import streamlit as st
from streamlit_js_eval import streamlit_js_eval
from pypdf import PdfReader
from docx import Document
import json
import re
import time
import hashlib
import mysql.connector
import re
from decimal import Decimal
import secrets

# ============================================================
# 2. PERFORMANCE HELPER
# ============================================================
from contextlib import contextmanager

@contextmanager
def measure_time(operation_name):
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        print(
            f"[PERFORMANCE] {operation_name}: "
            f"{elapsed:.3f} seconds"
        )

# ============================================================
# 3. STREAMLIT PAGE CONFIGURATION
 # Sets the browser tab title and icon.
 # Also displays the main title of the application.
# ============================================================
st.set_page_config(
    page_title="Ibot",
    page_icon="AI_Interview_icon.png"
)

if "openai_model" not in st.session_state:
        st.session_state["openai_model"] = "gpt-5.6-luna"

st.title("Interview phase")
st.subheader(
        f"Powered by Gen AI : "
        f"{st.session_state['openai_model']}"
    )

st.caption("Interview powered assistant")

# ============================================================
# 4. TEMPORARY DIAGNOSTIC: CHECK SCRIPT RERUNS
# ============================================================
if "_run_count" not in st.session_state:
    st.session_state["_run_count"] = 0

st.session_state["_run_count"] += 1

# Start timing this particular script run
script_start_time = time.perf_counter()

st.caption(
    f"Script runs: {st.session_state['_run_count']}"
)

st.caption(f"File watcher: {st.get_option('server.fileWatcherType')}")

# # ========================================================
# # 5. CREATE OPENAI CLIENT
#   # The API key is retrieved from Streamlit secrets.
# # ========================================================
# try:
#     api_key = st.secrets["OPENAI_API_KEY"]

#     if not api_key or not api_key.strip():
#         raise ValueError("OpenAI API key is empty.")
#     client = OpenAI(api_key=api_key)
#     print("OpenAI client initialized successfully.")
# except Exception as e:
#     client = None
#     print(f"OpenAI client initialization failed: {type(e).__name__}")
#     st.error(
#         "OpenAI configuration is missing or invalid. "
#         "Please check your application secrets."
#     )

# ========================================================
# 5. CREATE OPENAI CLIENT (CACHED)
#   PERFORMANCE: the client (and its HTTP connection pool) is
#   created once and reused on every rerun and by every user.
# ========================================================

@st.cache_resource(show_spinner=False)
def get_openai_client(api_key):
    # timeout   -> avoid hanging forever on a slow request
    # max_retries -> automatic retry on transient network errors
    return OpenAI(api_key=api_key, timeout=90, max_retries=2)

try:
    api_key = st.secrets["OPENAI_API_KEY"]
    if not api_key or not api_key.strip():
        raise ValueError("OpenAI API key is empty.")
    client = get_openai_client(api_key)
except Exception as e:
    client = None
    print(f"OpenAI client initialization failed: {type(e).__name__}")
    st.error(
        "OpenAI configuration is missing or invalid. "
        "Please check your application secrets."
    )

# ============================================================
# 5.1 MYSQL CONNECTION POOL (CACHED)
#   PERFORMANCE: opening a new MySQL connection for every query
#   costs a TCP + auth handshake each time. A pool keeps
#   connections open and hands them out instantly.
#   conn.close() on a pooled connection returns it to the pool
#   (it does NOT actually disconnect).
# ============================================================
from mysql.connector import pooling

@st.cache_resource(show_spinner=False)
def get_mysql_pool():
    cfg = st.secrets["mysql"]
    return pooling.MySQLConnectionPool(
        pool_name="ibot_pool",
        pool_size=10,               # max simultaneous connections
        pool_reset_session=True,    # clean session state on reuse
        host=cfg["host"],
        port=int(cfg["port"]),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        connection_timeout=10,
    )


def get_db_connection():
    conn = get_mysql_pool().get_connection()
    # Revive the connection if MySQL closed it after being idle
    conn.ping(reconnect=True, attempts=2, delay=1)
    return conn

# ============================================================================
# 6. INITIALIZE SESSION STATE VARIABLES
  # Streamlit reruns the entire Python script whenever the user
  # interacts with the application.
  # st.session_state allows us to preserve information between these reruns.
  # These variables control the different stages of the interview.
  # Gives the user choice to select the setup Upload Resume/Manual selection
# ============================================================================
if "choose_setup" not in st.session_state:
    st.session_state.choose_setup = False

#Store which choice user selected
if "setup_mode" not in st.session_state:
    st.session_state.setup_mode = None

# Process the manual section if user opted
if "setup_complete" not in st.session_state:
    st.session_state.setup_complete = False

# Keeps track of how many answers the user has submitted.
if "user_message_count" not in st.session_state:
    st.session_state.user_message_count = 0

# Controls whether the feedback section should be displayed.
if "feedback_shown" not in st.session_state:
    st.session_state.feedback_shown = False

# Stores the complete conversation between the user and AI.
if "messages" not in st.session_state:
    st.session_state.messages = []

# Checks whether the interview has finished.
if "chat_complete" not in st.session_state:
    st.session_state.chat_complete = False

# Stores the parse resume JSON format.
if "resume_jsonextract_complete" not in st.session_state:
    st.session_state.resume_jsonextract_complete = False

if "candidate_data" not in st.session_state:
    st.session_state.candidate_data = None

# Stores generated feedback so it is NOT regenerated on every rerun
if "feedback_text" not in st.session_state:
    st.session_state.feedback_text = None

def complete_resume_processing():
    st.session_state.resume_jsonextract_complete = True

# ============================================================
# 7. FUNCTION TO Choose THE SETUP 
  # This function is called when the user clicks "Next".
# ============================================================
def setup_choose():
    # Save the selected setup mode before leaving the selectbox page
    st.session_state.setup_mode = st.session_state.setup_mode_widget

    # Move to the next setup stage
    st.session_state.choose_setup = True

# =================================================================
# 8. FUNCTION TO MARK THE SETUP AS COMPLETE
 # This function is called when the user clicks "Start Interview".
# =================================================================
def complete_setup():
    # Close any open edit boxes so nothing stays editable
    for field, _, _ in PROFILE_FIELDS:
        st.session_state[f"editing_{field}"] = False

    st.session_state.setup_complete = True

# ============================================================
# 9. FUNCTION TO SHOW FEEDBACK
  # This function changes feedback_shown to True when the 
  # "Get Feedback" button is clicked.
# ============================================================
def show_feedback():
    st.session_state.feedback_shown = True

# ===============================================================
# 10. Setup selection Form
  # This form gives the user the choice to select the setup type
# ===============================================================
if not st.session_state.choose_setup:
        st.header("Choose mode of setup", divider="rainbow")
        st.selectbox(
            "Choose setup",
            (
                "Upload Resume",
                "Manual selection",
            ),
        key="setup_mode_widget"
        )
        st.info(
                """
                NOTE : If you choose "Manual selection" You have to enter/choose
                Name , Experience , Skills , Company , level, postion in the next page
                after selecting Next button.
                """,         
            )

        if st.button(
        "Next",
        on_click=setup_choose
    ):
         st.write("Selection complete... Starting Interview...")

# ============================================================
# 11. EXTRACT TEXT FROM RESUME
# This function supports:
#     PDF
#     DOCX
#     TXT
# The function checks the uploaded file's extension
# and uses the appropriate method to extract the text.
# ============================================================
def extract_resume_text(uploaded_file):
    file_name = uploaded_file.name.lower()

    # --------------------------------------------------------
    # 11.1 PDF
    # --------------------------------------------------------
    if file_name.endswith(".pdf"):
        reader = PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    # --------------------------------------------------------
    # 11.2 DOCX
    # --------------------------------------------------------
    elif file_name.endswith(".docx"):
        document = Document(uploaded_file)
        text = ""
        for paragraph in document.paragraphs:
            text += paragraph.text + "\n"
        return text
    # --------------------------------------------------------
    # 11.3 TXT
    # --------------------------------------------------------
    elif file_name.endswith(".txt"):
        text = uploaded_file.read().decode("utf-8")
        return text
    # --------------------------------------------------------
    # 11.4 UNSUPPORTED FILE
    # --------------------------------------------------------
    else:
        raise ValueError(
            "Unsupported file type. "
            "Please upload a PDF, DOCX, or TXT file."
        )

# ============================================================
# 12. Define schema for structured resume data
# ============================================================
resume_schema = {
                "type": "object",
                "properties": {
                    "name": {
                        "type": ["string", "null"]
                    },

                    "email": {
                        "type": ["string", "null"]
                    },

                    "phone_number": {
                        "type": ["string", "null"]
                    },

                    "company": {
                        "type": ["string", "null"]
                    },
    
                    "total_experience": {
                        "type": ["number", "null"]
                    },
    
                    "current_role": {
                        "type": ["string", "null"]
                    },
    
                    "skills": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    },

                    "summary": {
                         "type": "string"
                    },
    
                    "experience": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "company": {
                                    "type": ["string", "null"]
                                },
                                "role": {
                                    "type": ["string", "null"]
                                },
                                "duration": {
                                    "type": ["string", "null"]
                                }
                            },
                            "required": [
                                "company",
                                "role",
                                "duration"
                            ],
                            "additionalProperties": False
                        }
                    },
    
                    "projects": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    }
                },
    
                "required": [
                    "name",
                    "email",
                    "phone_number",
                    "company",
                    "total_experience",
                    "current_role",
                    "skills",
                    "experience",
                    "projects",
                    "summary"
                ],
    
                "additionalProperties": False
            }

# ============================================================
# 13. Parse Resume with LLM
# ============================================================
def parse_resume_with_llm(resume_text, client):
    if not resume_text or not resume_text.strip():
        raise ValueError(
            "No readable text was found in the resume. "
            "Please upload a text-based PDF, DOCX, or TXT file."
        )
    
    with st.status("Analyzing your resume"):
        response = client.responses.create(
        model="gpt-5.6-luna",
        # PERFORMANCE: extraction is a simple task; low reasoning
        # effort is much faster with no real loss in accuracy
        reasoning={"effort": "low"},
        instructions="""
        You are a precise resume information extraction system.

        Extract information only from the supplied resume.

        Rules:
        1. The candidate's name must be the actual person's
           name, not a programming language, framework,
           project, company, or job title.
        2. Use the resume's heading and contact section to
           identify the candidate's name.
        3. Do not treat Django, Python, Java, or other
           technical terms as a person's name.
        4. If the name is ambiguous, return null.
        5. Extract email and phone only when supported
           by the resume.
        6. Calculate total professional experience from
           employment dates when reasonably possible.
           Do not add overlapping periods twice.
        7. Do not invent missing details.
        8. Extract skills, roles, companies, and projects.
        9. Write a 4-6 sentence summary, prioritising in this order:
           (a) Name, Email and phone number,
           (b) current role and total years of experience,
           (c) core technical skills,
           (d) most significant projects and measurable outcomes,
           (e) domain / industry exposure,
           (f) education or certifications, if present.
           Do not add unsupported claims.
        10. Return only the required structured output.
        """,

        input=resume_text,
        text={
            "format": {
                "type": "json_schema",
                "name": "resume",
                "strict": True,
                "schema": resume_schema
            }
        }
      )

        if not response.output_text:
           raise ValueError("The resume parser returned no output.")

        data = json.loads(response.output_text)

         # Normalize optional fields.
        data["name"] = (
            data.get("name").strip()
            if isinstance(data.get("name"), str)
            and data["name"].strip()
            else None
        )

        data["email"] = (
            data.get("email").strip()
            if isinstance(data.get("email"), str)
            and data["email"].strip()
            else None
        )

        data["phone_number"] = (
            data.get("phone_number").strip()
            if isinstance(data.get("phone_number"), str)
            and data["phone_number"].strip()
            else None
        )

        # Ensure consistent list fields.
        for field in ("skills", "projects", "experience"):
            if not isinstance(data.get(field), list):
                data[field] = []

        data["summary"] = (
            data.get("summary") or
            "No summary could be generated from the available resume text."
        )
    return data    
    # return response.output_text

# # ==================================================================
# # 14. Define PII Services
#   # This section imports the necessary packages to run PII Service
# # ==================================================================
# from presidio_analyzer import (
#     AnalyzerEngine,
#     Pattern,
#     PatternRecognizer
#     )
# from presidio_anonymizer import AnonymizerEngine

# @st.cache_resource
# def get_pii_engines():
#  analyzer = AnalyzerEngine()
#  anonymizer = AnonymizerEngine()

#  company_recognizer = PatternRecognizer(
#     supported_entity="COMPANY",
#     patterns=[
#         Pattern(
#             name="tcs",
#             regex=r"\bTCS\b",
#             score=0.95
#         ),
#         Pattern(
#             name="infosys",
#             regex=r"\bInfosys\b",
#             score=0.95
#         ),
#         Pattern(
#             name="accenture",
#             regex=r"\bAccenture\b",
#             score=0.95
#         ),
#         Pattern(
#             name="capgemini",
#             regex=r"\bCapgemini Technology Services\b",
#             score=0.95
#         )
#     ],
#     supported_language="en"
#   )
 
#  analyzer.registry.add_recognizer(company_recognizer)
#  return analyzer, anonymizer

# # Initialize PII services with a spinner
# with st.spinner("Initializing application... Please wait"):
#  with measure_time("PII engine initialization"):
#    analyzer, anonymizer = get_pii_engines()

# # ============================================================
# # 15. Mask the sensitive Information using PII
#   # This analyzer detects and Mask the important information
# # ============================================================
# def mask_resume_pii(resume_text):
#     # Detect PII entities
#     results = analyzer.analyze(
#         text=resume_text,
#         language="en",
#         entities=[
#             "EMAIL_ADDRESS",
#             "PHONE_NUMBER",
#             "PERSON",
#             "COMPANY"
#         ]
#     )

#     # Capture detected entity values before masking
#     detected_entities = {}

#     for result in results:
#         entity_value = resume_text[result.start:result.end]
#         entity_type = result.entity_type

#         detected_entities.setdefault(entity_type, [])
#         if entity_value not in detected_entities[entity_type]:
#             detected_entities[entity_type].append(entity_value)

#     # Mask detected PII
#     masked_text = anonymizer.anonymize(
#         text=resume_text,
#         analyzer_results=results
#     ).text

#     return masked_text, detected_entities

# ============================================================
# 14. PII SERVICES (LAZY-LOADED)
#   PERFORMANCE:
#   - Presidio + spaCy are imported ONLY inside the function, so
#     the app starts without loading them.
#   - Uses the small spaCy model (en_core_web_sm ~12 MB) instead of
#     the default en_core_web_lg (~550 MB).
#   - Loaded only when masking is actually enabled.
#   One-time install:  python -m spacy download en_core_web_sm
# ============================================================

# Set to True only if you send masked_resume_text to the LLM.
# Currently the original resume_text is sent, so masking is skipped.
USE_PII_MASKING = False

@st.cache_resource(show_spinner="Loading privacy engine (first time only)...")
def get_pii_engines():
    # Heavy imports kept inside the function (lazy import)
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine

    # Use the small spaCy model instead of the large default one
    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    ).create_engine()

    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine,
        supported_languages=["en"],
    )
    anonymizer = AnonymizerEngine()

    company_recognizer = PatternRecognizer(
        supported_entity="COMPANY",
        patterns=[
            Pattern(name="tcs", regex=r"\bTCS\b", score=0.95),
            Pattern(name="infosys", regex=r"\bInfosys\b", score=0.95),
            Pattern(name="accenture", regex=r"\bAccenture\b", score=0.95),
            Pattern(
                name="capgemini",
                regex=r"\bCapgemini Technology Services\b",
                score=0.95,
            ),
        ],
        supported_language="en",
    )
    analyzer.registry.add_recognizer(company_recognizer)
    return analyzer, anonymizer


# ============================================================
# 15. MASK SENSITIVE INFORMATION USING PII
# ============================================================
def mask_resume_pii(resume_text):
    # Engines are created on the first call only (cached afterwards)
    analyzer, anonymizer = get_pii_engines()

    results = analyzer.analyze(
        text=resume_text,
        language="en",
        entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "COMPANY"],
    )

    detected_entities = {}
    for result in results:
        entity_value = resume_text[result.start:result.end]
        detected_entities.setdefault(result.entity_type, [])
        if entity_value not in detected_entities[result.entity_type]:
            detected_entities[result.entity_type].append(entity_value)

    masked_text = anonymizer.anonymize(
        text=resume_text,
        analyzer_results=results,
    ).text

    return masked_text, detected_entities

# ============================================================
# 16 SAVE CANDIDATE PROFILE AFTER RESUME PROCESSING
# ============================================================

def generate_candidate_reference():
    return str(secrets.randbelow(9_000_000) + 1_000_000)

def save_candidate_profile(
    candidate_data,
    setup_mode,
    extracted_resume_text=None
):
    connection = None
    cursor = None
    public_id = generate_candidate_reference()

    try:
        # connection = mysql.connector.connect(
        #     host=st.secrets["mysql"]["host"],
        #     port=st.secrets["mysql"]["port"],
        #     user=st.secrets["mysql"]["user"],
        #     password=st.secrets["mysql"]["password"],
        #     database=st.secrets["mysql"]["database"]
        # )

        # Reuse a pooled connection instead of opening a new one
        connection = get_db_connection()

        cursor = connection.cursor()

        name = candidate_data.get("name")
        email = candidate_data.get("email")
        phone = candidate_data.get("phone_number")
        company = candidate_data.get("company")

        # Convert the Python dictionary to JSON text for MySQL
        structured_json = json.dumps(
            candidate_data,
            ensure_ascii=False
        )

        cursor.execute(
            """
            INSERT INTO candidates (
                public_candidate_id,
                name,
                email,
                phone,
                company,
                setup_mode,
                extracted_resume_text,
                structured_data
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                candidate_id = LAST_INSERT_ID(candidate_id),
                name = VALUES(name),
                phone = VALUES(phone),
                company = VALUES(company),
                setup_mode = VALUES(setup_mode),
                extracted_resume_text =
                    VALUES(extracted_resume_text),
                structured_data = VALUES(structured_data)
            """,
            (
                # public_id,
                # name,
                # email,
                # phone,
                # company,
                # setup_mode,
                # extracted_resume_text,
                # structured_json

                public_id,
                candidate_data.get("name"),
                candidate_data.get("email"),
                candidate_data.get("phone_number")
                    or candidate_data.get("phone"),
                candidate_data.get("company"),
                setup_mode,
                extracted_resume_text,
                json.dumps(candidate_data, ensure_ascii=False)
            )
        )

        candidate_id = cursor.lastrowid

        cursor.execute(
                    """
                    SELECT public_candidate_id
                    FROM candidates
                    WHERE candidate_id = %s
                    """,
                    (candidate_id,)
                )

        public_id = cursor.fetchone()[0]

        connection.commit()

        print(
            "Candidate profile saved successfully | "
            f"Candidate ID: {public_id} | "
            f"Setup mode: {setup_mode}"
        )

        return candidate_id, public_id

    except Exception:
        if connection and connection.is_connected():
            connection.rollback()
        raise

    finally:
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


# ============================================================
# CANDIDATE PROFILE HELPERS (sidebar view + edit)
# ============================================================
PROFILE_FIELDS = [
    # (field key in candidate_data, label, input kind)
    ("name", "Name", "text"),
    ("email", "Email", "text"),
    ("phone_number", "Phone number", "text"),
    ("total_experience", "Experience (years)", "number"),
    ("skills", "Skills", "skills"),
    ("projects", "Projects", "projects"),
    ("summary", "Summary", "summary"),
]


def experience_years(value):
    """Return experience as a number, e.g. '3.5 years in Python' -> 3.5."""
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def as_list(value, separator=","):
    """Normalise a list or a delimited string into a clean list of strings."""
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = value.split(separator)
    else:
        items = []
    return [str(item).strip() for item in items if str(item).strip()]


def field_to_input_value(field, kind, data):
    """Value used to pre-fill the edit widget."""
    value = data.get(field)
    if kind == "number":
        return min(experience_years(value) or 0.0, 60.0)
    if kind == "skills":
        return ", ".join(as_list(value, ","))
    if kind == "projects":
        return "\n".join(as_list(value, "\n"))
    if field == "phone_number":
        return value or data.get("phone") or ""
    return value or ""


def input_to_field_value(field, kind, raw):
    """Validate and convert the edited widget value."""
    if kind == "number":
        return float(raw)
    if kind == "skills":
        return as_list(raw, ",")
    if kind == "projects":
        return as_list(raw, "\n")

    text = (raw or "").strip()
    if field == "name" and not text:
        raise ValueError("Name cannot be empty.")
    if field == "email" and not re.fullmatch(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text
    ):
        raise ValueError("Please enter a valid email address.")
    if field == "phone_number" and not re.fullmatch(
        r"\+?[0-9][0-9\- ]{6,18}", text
    ):
        raise ValueError(
            "Phone may contain only digits, spaces, '-' and a leading '+'."
        )
    return text or None


def update_candidate_profile(candidate_id, candidate_data):
    """
        Write the edited profile back to the candidates table.
        Server-side lock: refused while this candidate has an ACTIVE
        interview. Interviews abandoned (tab closed) for 2+ hours are
        ignored so a returning candidate is not blocked forever.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT interview_id
            FROM interviews
            WHERE candidate_id = %s
              AND status = 'in_progress'
              AND ended_at IS NULL
              AND last_activity_at > NOW() - INTERVAL 2 HOUR
            LIMIT 1
            FOR UPDATE
            """,
            (candidate_id,),
        )

        # Lock the interview row and confirm it is still active
        # cursor.execute(
        #     """
        #     SELECT status
        #     FROM interviews
        #     WHERE interview_id = %s
        #       AND candidate_id = %s
        #       AND status = 'in_progress'
        #       AND ended_at IS NULL
        #     FOR UPDATE
        #     """,
        #     (interview_id, candidate_id),
        # )
        
        if cursor.fetchone() is not None:
            raise ValueError("An interview is in progress; your profile is locked.")

        cursor.execute(
            """
            UPDATE candidates
            SET name = %s,
                email = %s,
                phone = %s,
                company = %s,
                structured_data = %s
            WHERE candidate_id = %s
            """,
            (
                candidate_data.get("name"),
                candidate_data.get("email"),
                candidate_data.get("phone_number")
                    or candidate_data.get("phone"),
                candidate_data.get("company"),
                json.dumps(candidate_data, ensure_ascii=False, default=str),
                candidate_id,
            ),
        )
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def build_interview_system_prompt(candidate_data):
    candidate_context = json.dumps(candidate_data, indent=2, default=str)
    return f"""
                You are an expert HR interviewer.

                Candidate information:

                {candidate_context}

                Ask exactly ONE question at a time.
                Base questions on the candidate's actual information.
                Do not invent candidate experience or skills.
                Ask follow-up questions based on their answers.
                """


# ---------------- Edit button callbacks ----------------
def start_edit(field, kind):
    st.session_state[f"input_{field}"] = field_to_input_value(
        field, kind, st.session_state.candidate_data
    )
    st.session_state[f"editing_{field}"] = True


def cancel_edit(field):
    st.session_state[f"editing_{field}"] = False


def save_edit(field, label, kind):
    updated = dict(st.session_state.candidate_data)

    try:
        # LOCK: no profile changes once the interview has ended
        if st.session_state.get("setup_complete"):
            st.session_state[f"editing_{field}"] = False
            raise ValueError("The interview has started; your profile is locked.")

        value = input_to_field_value(
            field, kind, st.session_state.get(f"input_{field}")
        )
        updated[field] = value
        if field == "phone_number":
            updated["phone"] = value

        candidate_id = st.session_state.get("candidate_id")
        if candidate_id is None:
            raise ValueError("Candidate ID is missing; cannot save.")

        update_candidate_profile(candidate_id, updated)
        # if st.session_state.get("interview_ended"):
        #     st.session_state[f"editing_{field}"] = False
        #     raise ValueError("The interview has ended; the profile is locked.")
        
        # value = input_to_field_value(
        #     field, kind, st.session_state.get(f"input_{field}")
        # )
        # updated[field] = value
        # if field == "phone_number":
        #     updated["phone"] = value

        # candidate_id = st.session_state.get("candidate_id")
        # interview_id = st.session_state.get("interview_id")
        # if candidate_id is None or interview_id is None:
        #     raise ValueError("Candidate or interview ID is missing; cannot save.")

        # update_candidate_profile(candidate_id,interview_id, updated)
        st.session_state.candidate_data = updated

        # Keep the interviewer's context in sync with the edited profile
        messages = st.session_state.get("messages") or []
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] = build_interview_system_prompt(updated)

        st.session_state[f"editing_{field}"] = False
        st.session_state.profile_notice = ("success", f"{label} updated.")

    except ValueError as e:
        st.session_state.profile_notice = ("error", str(e))
    except mysql.connector.IntegrityError:
        st.session_state.profile_notice = (
            "error", "This email is already linked to another candidate."
        )
    except Exception as e:
        print(f"Profile update failed: {type(e).__name__}")
        st.session_state.profile_notice = (
            "error", f"Could not save {label}. Please try again."
        )


# ---------------- Rendering ----------------
def render_profile_value(field, kind, data):
    value = data.get(field)

    if kind == "number":
        years = experience_years(value)
        st.markdown(f"{years:g} years" if years is not None else "_Not provided_")
    elif kind == "skills":
        skills = as_list(value, ",")
        st.markdown(" ".join(f"`{s}`" for s in skills) if skills else "_Not provided_")
    elif kind == "projects":
        projects = as_list(value, "\n")
        st.markdown("\n".join(f"- {p}" for p in projects) if projects else "_Not provided_")
    else:
        if field == "phone_number":
            value = value or data.get("phone")
        st.markdown(value or "_Not provided_")


def render_profile_field(field, label, kind):
    data = st.session_state.candidate_data or {}
    editing = st.session_state.get(f"editing_{field}", False)

    label_col, button_col = st.columns([4, 1], vertical_alignment="center")
    label_col.markdown(f"**{label}**")

    if not editing:
        button_col.button(
            "✏️",
            key=f"edit_btn_{field}",
            help=f"Edit {label}",
            on_click=start_edit,
            args=(field, kind),
        )
        render_profile_value(field, kind, data)
        return

    input_key = f"input_{field}"
    if kind == "number":
        st.number_input(
            label, key=input_key, min_value=0.0, max_value=60.0,
            step=0.5, label_visibility="collapsed",
        )
    elif kind == "skills":
        st.text_area(
            label, key=input_key, placeholder="Comma-separated, e.g. Python, SQL",
            label_visibility="collapsed",
        )
    elif kind == "projects":
        st.text_area(
            label, key=input_key, placeholder="One project per line",
            label_visibility="collapsed",
        )
    elif kind == "summary":
        st.text_area(label, key=input_key, height=220, label_visibility="collapsed")
    else:
        st.text_input(label, key=input_key, label_visibility="collapsed")

    save_col, cancel_col = st.columns(2)
    save_col.button(
        "Save", key=f"save_btn_{field}", type="primary",
        use_container_width=True, on_click=save_edit, args=(field, label, kind),
    )
    cancel_col.button(
        "Cancel", key=f"cancel_btn_{field}",
        use_container_width=True, on_click=cancel_edit, args=(field,),
    )

# ============================================================
# 16.1 PROFILE REVIEW SCREEN (SHARED BY UPLOAD + MANUAL)
#   The candidate reviews and edits the profile BEFORE the
#   interview starts. The AI generates its questions from this
#   profile, so it is locked once the interview begins.
# ============================================================
def render_profile_review(start_button_key):
    # Two blank lines before the review section
    st.write("")
    st.write("")

    st.subheader("Review your details", divider="rainbow")
    st.caption(
        "Please check your details. You can edit any field now. "
        "Once the interview starts, your profile is locked."
    )

    # Success / error message from the last Save click
    notice = st.session_state.pop("profile_notice", None)
    if notice:
        level, text = notice
        (st.success if level == "success" else st.error)(text)

    for field, label, kind in PROFILE_FIELDS:
        # Summary only exists for resume uploads
        if field == "summary" and st.session_state.setup_mode != "Upload Resume":
            continue
        with st.container(border=True):
            render_profile_field(field, label, kind)

    # Block starting while an edit box is still open (unsaved changes)
    any_editing = any(
        st.session_state.get(f"editing_{field}", False)
        for field, _, _ in PROFILE_FIELDS
    )
    if any_editing:
        st.warning("Save or cancel your open edits before starting the interview.")

    st.button(
        "Confirm & Start Interview",
        type="primary",
        key=start_button_key,
        on_click=complete_setup,
        disabled=any_editing,
        use_container_width=True,
    )
# ============================================================
# 17. Choice 1 - Resume Upload and display extracted resume data
  # This form gives the option to upload the resume
# ============================================================
if (st.session_state.choose_setup and 
    st.session_state.setup_mode == "Upload Resume" 
    and not st.session_state.setup_complete
) : 
    st.header("Upload Resume", divider="rainbow") 
    uploaded_resume = st.file_uploader( 
        "Upload your resume", 
        type=["pdf", "docx", "txt"],
        key="resume_uploader"
    )  
    if uploaded_resume: 
        st.success("Resume uploaded successfully!")

        # Identify this uploaded file to avoid reprocessing it on
        # every Streamlit rerun.
        file_hash = hashlib.sha256(
        uploaded_resume.getvalue()
        ).hexdigest()

        # Process only if this file has not already been processed
        if st.session_state.get("processed_resume_hash") != file_hash:
           
            try :
              # Extract text from the uploaded PDF
              with measure_time("Resume text extraction"):
                 resume_text = extract_resume_text(uploaded_resume)

            #   # Detect amd mask PII
            #   with st.spinner("Detecting and masking sensitive information..."):
            #         with measure_time("PII detection and masking"):
            #             masked_resume_text, detected_entities = mask_resume_pii(resume_text)

                # Detect and mask PII ONLY when enabled
                # (skipping it saves several seconds per resume)
                 if USE_PII_MASKING:
                  with st.spinner("Detecting and masking sensitive information..."):
                      with measure_time("PII detection and masking"):
                          masked_resume_text, detected_entities = mask_resume_pii(resume_text)

              # Send masked text to the LLM
              with measure_time("OpenAI resume parsing"):
                # resume_json = parse_resume_with_llm(
                candidate_data = parse_resume_with_llm(
                 resume_text, # Use this when you want to pass the same exact orignial resume data without masking
                 # masked_resume_text, # Use this when you want to pass the masked resume data
                 client
              ) 
                
              # Convert the response into a Python dictionary
            #   with measure_time("Resume JSON parsing"):
            #       candidate_data = json.loads(resume_json)

              # Restore detected personal details into the structured data
            #   with measure_time("Resume JSON parsing"):
            #     candidate_data["name"] = (
            #     detected_entities.get("PERSON", [None])[0]
            #   )
            #   candidate_data["email"] = (
            #     detected_entities.get("EMAIL_ADDRESS", [None])[0]
            #   )
            #   candidate_data["phone_number"] = (
            #     detected_entities.get("PHONE_NUMBER", [None])[0]
            #   )

              # Format the extracted phone number
              phone_number = candidate_data.get("phone_number")

              if phone_number:
                   phone_number = str(phone_number).strip()

                   if phone_number.startswith("+"):
                       # Country code is already present
                       full_phone = phone_number
                   elif phone_number.startswith("91") and len(phone_number) == 12:
                    # Indian country code is present without "+"
                       full_phone = f"+{phone_number[:2]}-{phone_number[2:]}"
                   else:
                       # Keep the number unchanged when the country code is unknown
                       full_phone = phone_number

                   candidate_data["phone_number"] = full_phone
                   candidate_data["phone"] = full_phone

              # Store structured data in session state
              st.session_state.candidate_data = candidate_data

              # Save resume and structured data to MySQL
              with st.spinner("Saving candidate profile..."):
               with measure_time("MySQL candidate profile save - Resume"):
                  candidate_id, public_id = save_candidate_profile(
                  candidate_data=candidate_data,
                  setup_mode="Upload Resume",
                  extracted_resume_text=resume_text
              )

              # Preserve the ID for the interview-saving function
              st.session_state.candidate_id = candidate_id
              st.session_state.public_candidate_id = public_id
              st.session_state.candidate_data = candidate_data

              # Mark processing complete only after successful saving
              st.session_state.processed_resume_hash = file_hash
              st.session_state.candidate_profile_saved = True

              # Log only metadata, not the resume or personal details
              print(
                 "Resume processing completed successfully | "
                 f"Candidate ID: {public_id} | "
                 f"File hash: {file_hash[:12]}"
              )

              # Mark resume processing as complete
              complete_resume_processing()

            except Exception as e:
              st.session_state.candidate_profile_saved = False

              # Print the complete error and line number in the terminal
              import traceback
              traceback.print_exc()

              # Log the error type, not the resume or personal information
              print(f"Resume processing failed: {type(e).__name__}")

              st.error(
                  "We couldn't save your resume details. "
                  "Please check the application console for details."
              )
              st.stop()

        # ------------------------------------------------------------
        # 17.1 REVIEW EXTRACTED DETAILS BEFORE STARTING
        #   Shown only after the resume was parsed AND saved.
        # ------------------------------------------------------------
        if st.session_state.get("candidate_profile_saved", False):
            render_profile_review(start_button_key="start_resume_interview")      

        # # Keep your existing Start Interview button below this block.
        # if st.session_state.get("candidate_profile_saved", False):
        #     if st.button(
        #         "Start Interview",
        #         on_click=complete_setup,
        #         key="start_resume_interview"
        #     ):
        #       pass

# ==================================================================
# 18. Choice 2 - Manaul Selection "PERSONAL INFORMATION FORM"
  # This section is displayed only BEFORE the interview starts and 
  # if user chooses the setup as "Manual selection".
  # The user enters:
  # - Name
  # - Experience
  # - Skills
# ==================================================================
if  (
    st.session_state.choose_setup 
    and st.session_state.setup_mode == "Manual selection"  
    and not st.session_state.setup_complete 
    # Hide the form once it was submitted; the review screen takes over
    and not st.session_state.get("manual_profile_saved", False)
):
    st.subheader("Personal informaton", divider="rainbow")

    # Initialize defaults before creating widgets
    defaults = {
        "name": "",
        "email": "",
        "phone_number": "",
        "experience": "",
        "skills": "",
        "level": "Junior",
        "position": "Data Scientist",
        "company": "Netflix",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    with st.form("interview_setup_form") :

       # --------------------------------------------------------
       # 18.1 Name input
       # --------------------------------------------------------
        st.text_input(
            "Name",
            max_chars=40,
            placeholder="Enter your name",
            key="name"
        )

        # --------------------------------------------------------
        # 18.2 Email input
        # --------------------------------------------------------
        st.text_input(
            "Email",
            max_chars=40,
            placeholder="Enter your email",
            key="email"
        )

        # --------------------------------------------------------
        # 18.3 Phone number input
              # Country code and phone number
        # --------------------------------------------------------
        phone_col1, phone_col2 = st.columns([1, 2])

        with phone_col1:
            st.selectbox(
              "Country code",
              options=[
                "+91",  # India
                "+1",   # US/Canada
                "+33",  # France
                "+44",  # UK
                "+61",  # Australia
                "+81",  # Japan
                "+49",  # Germany
                "+971", # UAE
            ],
            key="phone_country_code",
            )

        with phone_col2:
           st.text_input(
           "Phone number",
           max_chars=10,
           placeholder="10-digit mobile number",
           key="phone_number",
        )

        # --------------------------------------------------------
        # 18.4 Experience input
        # --------------------------------------------------------
        st.text_area(
            "Experience",
            max_chars=300,
            placeholder="Describe your experience",
            key="experience"
        )

        # --------------------------------------------------------
        # 18.5 Skills input
        # --------------------------------------------------------
        st.text_area(
            "Skills",
            max_chars=100,
            placeholder="List your skills",
            key="skills"
        )

        # --------------------------------------------------------
        # 18.6 COMPANY AND POSITION INFORMATION
        # --------------------------------------------------------
        st.subheader("Company and Position", divider="rainbow")

        # --------------------------------------------------------
        # 18.7 Create two columns for Level and Position
        # --------------------------------------------------------
        col1, col2 = st.columns(2)

        # --------------------------------------------------------
        # 18.8 Interview level selection
        # --------------------------------------------------------
        with col1:
            st.radio(
                "Choose level",
                key="level",
                options=["Junior", "Mid-level", "Senior"],
            )

        # --------------------------------------------------------
        # 18.9 Position selection
        # --------------------------------------------------------
        with col2:
            st.selectbox(
                "Choose a position",
                options = [
                    "Data Scientist",
                    "Full Stack Developer",
                    "ML Engineer",
                    "Sales executive",
                    "Nodejs developer",
                    "SD L1 Analyst",
                    "SD Lead",
                    "SD Manager",
                    "Service Delivery Manager",
                    "Front end Developer(React/Angular)",
                    "dot net Developer"
                ],
                key="position",
            )

        # --------------------------------------------------------
        # 18.10 Company selection
        # --------------------------------------------------------
        st.selectbox(
            "Choose a Company",
            options = [
                "Amazon",
                "Meta",
                "Udemy",
                "365 Company",
                "Netflix",
                "LinkedIn",
                "Spotify",
                "Capgemini Technology Services",
                "IBM",
                "Accenture",
                "TCS",
                "Infosys",
            ],
            key="company",
        )

        # -------------------------------------------------------------------------
        # 18.11 FORM SUBMIT AND START INTERVIEW 
           # Clicking this button changes setup_complete to True.
           # This causes Streamlit to rerun and enter the interview section below.
        # -------------------------------------------------------------------------
        submitted = st.form_submit_button(
            "Start Interview",
            type="primary",
        )

    # ------------------------------------------------------------------
    # 18.12 FORM VALIDATION CHECKS
    # ------------------------------------------------------------------
    if submitted:
         email = st.session_state["email"].strip()
         phone = st.session_state["phone_number"].strip()

         # Require an email address ending in .com
         email_pattern = (
             r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.com$"
         )

         # Require exactly 10 digits
         phone_pattern = r"^[0-9]{10}$"

         email_valid = re.fullmatch(email_pattern, email) is not None
         phone_valid = re.fullmatch(phone_pattern, phone) is not None

         if not email_valid:
          st.error(
            "Please enter a valid email address ending in "
            ".com, for example name@gmail.com."
        )
         if not phone_valid:
          st.error(
            "Phone number must contain exactly 10 digits "
            "without spaces or special characters."
        )
         if email_valid and phone_valid:
          phone_number = st.session_state.get("phone_number", "").strip()
          country_code = st.session_state.get("phone_country_code", "+91")

          full_phone = f"{country_code}-{phone_number}"

          st.session_state.candidate_data = {
            "name": st.session_state["name"].strip(),
            "email": email,
            "phone": full_phone,
            "phone_number": full_phone,
            "total_experience": st.session_state["experience"],
            "current_role": st.session_state["position"],
            "skills": st.session_state["skills"],
            "level": st.session_state["level"],
            "position": st.session_state["position"],
            "company": st.session_state["company"],
          }

          # --------------------------------------------------------------
          # 18.13 PRINT THE INFORMATION ENTERED BY THE USER TO THE CONSOLE
          # --------------------------------------------------------------
          candidate = st.session_state.candidate_data
          print("\n========== CANDIDATE INFORMATION ==========")
          print(f"Name: {candidate['name']}")
          print(f"Email: {candidate['email']}")
          print(f"Phone: {candidate['phone']}")
          print(f"Experience: {candidate['total_experience']}")
          print(f"Skills: {candidate['skills']}")
          print(
                f"Position: {candidate['level']} "
                f"{candidate['position']} at {candidate['company']}"
            )
          print("===========================================\n")

          # --------------------------------------------------------------
          # 18.14 SAVE CANDIDATE PROFILE TO MYSQL
          # --------------------------------------------------------------
          try:
             with st.spinner("Saving candidate profile..."):
              with measure_time("MySQL candidate profile save - Manual"):
                candidate_id, public_id = save_candidate_profile(
                candidate_data=st.session_state.candidate_data,
                setup_mode="Manual selection",
                extracted_resume_text=None
             )

             # Preserve the ID for the interview-saving function
             st.session_state.candidate_id = candidate_id
             st.session_state.public_candidate_id = public_id
             st.session_state.candidate_profile_saved = True
            #  st.session_state.candidate_id = candidate_id

             print(
                "Manual candidate profile saved successfully | "
                f"Candidate ID: {candidate_id}"
             )

            #  # Mark setup complete only after successful saving
            #  st.session_state.setup_complete = True
            #  st.rerun()

             # Go to the review screen (do NOT start the interview yet)
             st.session_state.manual_profile_saved = True
             st.rerun()
       
          except Exception as e:
            st.session_state.candidate_profile_saved = False
            print(
                "Candidate profile save failed: "
                f"{type(e).__name__}"
            )
            st.error(
                "We couldn't save your candidate details. "
                "Please try again."
            )

          # ==================================================================
          # 18.15 MANUAL SELECTION: REVIEW DETAILS BEFORE STARTING
          #   Shown after the manual form is saved. The candidate can also
          #   add Projects here (the form doesn't have that field).
          # ==================================================================
          if (
            st.session_state.choose_setup
            and st.session_state.setup_mode == "Manual selection"
            and not st.session_state.setup_complete
            and st.session_state.get("manual_profile_saved", False)
          ):
            render_profile_review(start_button_key="start_manual_interview")

# def get_db_connection():
#     return mysql.connector.connect(
#         host=st.secrets["mysql"]["host"],
#         port=st.secrets["mysql"]["port"],
#         user=st.secrets["mysql"]["user"],
#         password=st.secrets["mysql"]["password"],
#         database=st.secrets["mysql"]["database"],
#     )

# # ============================================================
# # CANDIDATE PROFILE HELPERS (sidebar view + edit)
# # ============================================================
# PROFILE_FIELDS = [
#     # (field key in candidate_data, label, input kind)
#     ("name", "Name", "text"),
#     ("email", "Email", "text"),
#     ("phone_number", "Phone number", "text"),
#     ("total_experience", "Experience (years)", "number"),
#     ("skills", "Skills", "skills"),
#     ("projects", "Projects", "projects"),
#     ("summary", "Summary", "summary"),
# ]


# def experience_years(value):
#     """Return experience as a number, e.g. '3.5 years in Python' -> 3.5."""
#     if isinstance(value, (int, float, Decimal)):
#         return float(value)
#     match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
#     return float(match.group()) if match else None


# def as_list(value, separator=","):
#     """Normalise a list or a delimited string into a clean list of strings."""
#     if isinstance(value, list):
#         items = value
#     elif isinstance(value, str):
#         items = value.split(separator)
#     else:
#         items = []
#     return [str(item).strip() for item in items if str(item).strip()]


# def field_to_input_value(field, kind, data):
#     """Value used to pre-fill the edit widget."""
#     value = data.get(field)
#     if kind == "number":
#         return min(experience_years(value) or 0.0, 60.0)
#     if kind == "skills":
#         return ", ".join(as_list(value, ","))
#     if kind == "projects":
#         return "\n".join(as_list(value, "\n"))
#     if field == "phone_number":
#         return value or data.get("phone") or ""
#     return value or ""


# def input_to_field_value(field, kind, raw):
#     """Validate and convert the edited widget value."""
#     if kind == "number":
#         return float(raw)
#     if kind == "skills":
#         return as_list(raw, ",")
#     if kind == "projects":
#         return as_list(raw, "\n")

#     text = (raw or "").strip()
#     if field == "name" and not text:
#         raise ValueError("Name cannot be empty.")
#     if field == "email" and not re.fullmatch(
#         r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text
#     ):
#         raise ValueError("Please enter a valid email address.")
#     if field == "phone_number" and not re.fullmatch(
#         r"\+?[0-9][0-9\- ]{6,18}", text
#     ):
#         raise ValueError(
#             "Phone may contain only digits, spaces, '-' and a leading '+'."
#         )
#     return text or None


# def update_candidate_profile(candidate_id, interview_id, candidate_data):
#     """
#         Write the edited profile back to the candidates table.
#         Server-side lock: allowed ONLY while this candidate's current
#         interview is still in progress. The UI hides the edit controls,
#         but this check is what actually enforces the rule.
#     """
#     conn = get_db_connection()
#     cursor = conn.cursor()

#     try:
#         # Lock the interview row and confirm it is still active
#         cursor.execute(
#             """
#             SELECT status
#             FROM interviews
#             WHERE interview_id = %s
#               AND candidate_id = %s
#               AND status = 'in_progress'
#               AND ended_at IS NULL
#             FOR UPDATE
#             """,
#             (interview_id, candidate_id),
#         )

#         if cursor.fetchone() is None:
#             raise ValueError("The interview has ended; the profile is locked.")

#         cursor.execute(
#             """
#             UPDATE candidates
#             SET name = %s,
#                 email = %s,
#                 phone = %s,
#                 company = %s,
#                 structured_data = %s
#             WHERE candidate_id = %s
#             """,
#             (
#                 candidate_data.get("name"),
#                 candidate_data.get("email"),
#                 candidate_data.get("phone_number")
#                     or candidate_data.get("phone"),
#                 candidate_data.get("company"),
#                 json.dumps(candidate_data, ensure_ascii=False, default=str),
#                 candidate_id,
#             ),
#         )
#         conn.commit()

#     except Exception:
#         conn.rollback()
#         raise

#     finally:
#         cursor.close()
#         conn.close()


# def build_interview_system_prompt(candidate_data):
#     candidate_context = json.dumps(candidate_data, indent=2, default=str)
#     return f"""
#                 You are an expert HR interviewer.

#                 Candidate information:

#                 {candidate_context}

#                 Ask exactly ONE question at a time.
#                 Base questions on the candidate's actual information.
#                 Do not invent candidate experience or skills.
#                 Ask follow-up questions based on their answers.
#                 """


# # ---------------- Edit button callbacks ----------------
# def start_edit(field, kind):
#     st.session_state[f"input_{field}"] = field_to_input_value(
#         field, kind, st.session_state.candidate_data
#     )
#     st.session_state[f"editing_{field}"] = True


# def cancel_edit(field):
#     st.session_state[f"editing_{field}"] = False


# def save_edit(field, label, kind):
#     updated = dict(st.session_state.candidate_data)

#     try:
#         # LOCK: no profile changes once the interview has ended
#         if st.session_state.get("interview_ended"):
#             st.session_state[f"editing_{field}"] = False
#             raise ValueError("The interview has ended; the profile is locked.")
        
#         value = input_to_field_value(
#             field, kind, st.session_state.get(f"input_{field}")
#         )
#         updated[field] = value
#         if field == "phone_number":
#             updated["phone"] = value

#         candidate_id = st.session_state.get("candidate_id")
#         interview_id = st.session_state.get("interview_id")
#         if candidate_id is None or interview_id is None:
#             raise ValueError("Candidate or interview ID is missing; cannot save.")

#         update_candidate_profile(candidate_id,interview_id, updated)
#         st.session_state.candidate_data = updated

#         # Keep the interviewer's context in sync with the edited profile
#         messages = st.session_state.get("messages") or []
#         if messages and messages[0]["role"] == "system":
#             messages[0]["content"] = build_interview_system_prompt(updated)

#         st.session_state[f"editing_{field}"] = False
#         st.session_state.profile_notice = ("success", f"{label} updated.")

#     except ValueError as e:
#         st.session_state.profile_notice = ("error", str(e))
#     except mysql.connector.IntegrityError:
#         st.session_state.profile_notice = (
#             "error", "This email is already linked to another candidate."
#         )
#     except Exception as e:
#         print(f"Profile update failed: {type(e).__name__}")
#         st.session_state.profile_notice = (
#             "error", f"Could not save {label}. Please try again."
#         )


# # ---------------- Rendering ----------------
# def render_profile_value(field, kind, data):
#     value = data.get(field)

#     if kind == "number":
#         years = experience_years(value)
#         st.markdown(f"{years:g} years" if years is not None else "_Not provided_")
#     elif kind == "skills":
#         skills = as_list(value, ",")
#         st.markdown(" ".join(f"`{s}`" for s in skills) if skills else "_Not provided_")
#     elif kind == "projects":
#         projects = as_list(value, "\n")
#         st.markdown("\n".join(f"- {p}" for p in projects) if projects else "_Not provided_")
#     else:
#         if field == "phone_number":
#             value = value or data.get("phone")
#         st.markdown(value or "_Not provided_")


# def render_profile_field(field, label, kind):
#     data = st.session_state.candidate_data or {}
#     editing = st.session_state.get(f"editing_{field}", False)

#     label_col, button_col = st.columns([4, 1], vertical_alignment="center")
#     label_col.markdown(f"**{label}**")

#     if not editing:
#         button_col.button(
#             "✏️",
#             key=f"edit_btn_{field}",
#             help=f"Edit {label}",
#             on_click=start_edit,
#             args=(field, kind),
#         )
#         render_profile_value(field, kind, data)
#         return

#     input_key = f"input_{field}"
#     if kind == "number":
#         st.number_input(
#             label, key=input_key, min_value=0.0, max_value=60.0,
#             step=0.5, label_visibility="collapsed",
#         )
#     elif kind == "skills":
#         st.text_area(
#             label, key=input_key, placeholder="Comma-separated, e.g. Python, SQL",
#             label_visibility="collapsed",
#         )
#     elif kind == "projects":
#         st.text_area(
#             label, key=input_key, placeholder="One project per line",
#             label_visibility="collapsed",
#         )
#     elif kind == "summary":
#         st.text_area(label, key=input_key, height=220, label_visibility="collapsed")
#     else:
#         st.text_input(label, key=input_key, label_visibility="collapsed")

#     save_col, cancel_col = st.columns(2)
#     save_col.button(
#         "Save", key=f"save_btn_{field}", type="primary",
#         use_container_width=True, on_click=save_edit, args=(field, label, kind),
#     )
#     cancel_col.button(
#         "Cancel", key=f"cancel_btn_{field}",
#         use_container_width=True, on_click=cancel_edit, args=(field,),
#     )


def create_interview_record(candidate_id, candidate_data):
    """
    Create an interview row when the interview actually starts.
    candidate_snapshot freezes the exact profile used for this
    interview, so later profile edits never change its history.

    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO interviews (
                candidate_id,
                status,
                candidate_snapshot,
                created_at,
                last_activity_at
            )
            VALUES (
                %s,
                'in_progress',
                %s,
                CURRENT_TIMESTAMP(6),
                CURRENT_TIMESTAMP(6)
            )
            """,
            (
                candidate_id,
                json.dumps(candidate_data, ensure_ascii=False, default=str),
             
            ),
        )

        interview_id = cursor.lastrowid
        conn.commit()
        return interview_id

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def update_interview_activity(interview_id):
    """Record activity when a candidate submits an answer."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE interviews
            SET last_activity_at = CURRENT_TIMESTAMP(6)
            WHERE interview_id = %s
              AND status = 'in_progress'
              AND ended_at IS NULL
            """,
            (interview_id,),
        )

        if cursor.rowcount == 0:
            raise ValueError("Interview is no longer active.")

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

# ============================================================
# SAVE & CLOSE SESSION IN MYSQL AFTER END CONVERSATION BUTTON IS CLICKED
# ============================================================

def end_interview_record(interview_id, final_status="ended"):
    """End an interview exactly once."""
    if final_status not in ("ended", "completed"):
        raise ValueError("Invalid interview status.")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE interviews
            SET status = %s,
                ended_at = CURRENT_TIMESTAMP(6)
            WHERE interview_id = %s
              AND status = 'in_progress'
              AND ended_at IS NULL
            """,
            (final_status, interview_id),
        )

        conn.commit()
        return cursor.rowcount == 1

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

# ============================================================
# INTERVIEW LIFECYCLE STATE
# ============================================================

if "interview_id" not in st.session_state:
    st.session_state.interview_id = None

if "interview_ended" not in st.session_state:
    st.session_state.interview_ended = False

if "interview_saved" not in st.session_state:
    st.session_state.interview_saved = False


# Create exactly one interview row for this session.
if (
    st.session_state.setup_complete
    and st.session_state.get("candidate_id") is not None
    and st.session_state.interview_id is None
):
    try:
        st.session_state.interview_id = (
            create_interview_record(
                st.session_state.candidate_id,
                st.session_state.candidate_data,   # frozen profile snapshot
            )
        )
    except Exception:
        st.error(
            "Unable to create the interview record. "
            "Please retry."
        )
        st.stop()

# # ============================================================
# # SIDEBAR — END INTERVIEW
# # ============================================================

# with st.sidebar:
#     st.subheader("Interview")

#     if st.session_state.setup_complete:
#         candidate_data = (
#             st.session_state.get("candidate_data") or {}
#         )

#         st.caption(
#             f"Candidate: "
#             f"{candidate_data.get('name') or 'Candidate'}"
#         )

#         st.caption(
#             f"Interview ID: "
#             f"{st.session_state.interview_id or 'Not created'}"
#         )

#         # NEW: Display the 7-digit public candidate reference
#         st.caption(
#             f"Candidate ID: "
#             f"{st.session_state.get('public_candidate_id') or 'Not available'}"
#         )

#         if st.session_state.interview_ended:
#             st.info("This interview has ended.")

#         elif st.button(
#             "End Conversation",
#             key="end_interview_button",
#             use_container_width=True,
#         ):
#             try:
#                 interview_id = st.session_state.interview_id

#                 if interview_id is None:
#                     raise ValueError(
#                         "No interview record exists."
#                     )

#                 end_interview_record(
#                     interview_id,
#                     final_status="ended",
#                 )

#                 st.session_state.interview_ended = True
#                 st.session_state.chat_complete = True

#                 st.rerun()

#             except Exception:
#                 st.error(
#                     "Unable to end the interview. "
#                     "Please try again."
#                 )

with st.sidebar:
    st.subheader("Interview")

    if st.session_state.setup_complete:
        candidate_data = st.session_state.get("candidate_data") or {}

        st.caption(f"Candidate: {candidate_data.get('name') or 'Candidate'}")
        st.caption(f"Interview ID: {st.session_state.interview_id or 'Not created'}")
        st.caption(
            f"Candidate ID: "
            f"{st.session_state.get('public_candidate_id') or 'Not available'}"
        )

        if st.session_state.interview_ended:
            st.info("This interview has ended.")

        elif st.button(
            "End Conversation",
            key="end_interview_button",
            use_container_width=True,
        ):
            try:
                interview_id = st.session_state.interview_id
                if interview_id is None:
                    raise ValueError("No interview record exists.")

                end_interview_record(interview_id, final_status="ended")
                st.session_state.interview_ended = True
                st.session_state.chat_complete = True
                st.rerun()

            except Exception:
                st.error("Unable to end the interview. Please try again.")

        #  # ------------------------------------------------------------
        # # CANDIDATE PROFILE (EDITABLE ONLY WHILE INTERVIEW IS ACTIVE)
        # #   Once the interview ends or completes, the profile is
        # #   locked: the score/feedback must match the profile the
        # #   candidate was interviewed with (audit integrity).
        # # ----------------------------------------------------------
        # if not st.session_state.interview_ended:

        #     # Two blank lines before the profile section
        #     st.write("")
        #     st.write("")

        #     st.subheader("Candidate profile")

        #     notice = st.session_state.pop("profile_notice", None)
        #     if notice:
        #         level, text = notice
        #         (st.success if level == "success" else st.error)(text)

        # for field, label, kind in PROFILE_FIELDS:
        #     # Summary only exists for resume uploads
        #     if field == "summary" and st.session_state.setup_mode != "Upload Resume":
        #         continue
        #     with st.container(border=True):
        #         render_profile_field(field, label, kind)

# ============================================================
# 19. INTERVIEW / CHATBOT SECTION
   # This section runs only when:
   # 1. Setup is complete
   # 2. Feedback has NOT been shown
   # 3. Chat is NOT complete
   # This is the main interactive chatbot section.
# ============================================================
if (
    st.session_state.setup_complete 
    and not st.session_state.feedback_shown
    and not st.session_state.chat_complete
):

    # --------------------------------------------------------
    # 19.1 Display initial interview greeting
    # --------------------------------------------------------
    candidate_name = (
    st.session_state.candidate_data.get("name")
    )
    st.info(
        f"""
        Hi {candidate_name}, thank you for appling for this role,
        very excited to take interview for you.. Here's your first question!
        """,
        icon="👏"
    )

    # ------------------------------------------------------------------
    # 19.2 SELECT THE OPENAI MODEL
        # The model name is stored in session_state so it can
        # persist between Streamlit reruns.
    # ------------------------------------------------------------------
    if "openai_model" not in st.session_state:
        st.session_state["openai_model"] = "gpt-5.6-luna"

    # ------------------------------------------------------------------
    # 19.3 CREATE THE INITIAL SYSTEM MESSAGE
       # This tells the AI what role it should play.
           # It also gives the AI information about:
           # - Candidate name
           # - Experience
           # - Skills
           # - Job level
           # - Position
           # - Company
           # This message is NOT displayed to the user.
    # ------------------------------------------------------------------

    if not st.session_state.messages:
        st.session_state.messages = [
            {
                "role": "system",
                "content": build_interview_system_prompt(
                    st.session_state.candidate_data
                ),
            }
        ]
    # if not st.session_state.messages:
    #     if st.session_state.setup_mode == "Upload Resume":
    #        candidate_data = st.session_state.candidate_data
    #     else:
    #     # Create the SAME candidate_data structure from the manually entered information.
    #      candidate_data = {
    #         "name": st.session_state["name"],
    #         "email": st.session_state["email"],
    #         "phone": (
    #             st.session_state["phone_country_code"]
    #             + st.session_state["phone_number"]
    #         ),
    #         "total_experience": st.session_state["experience"],
    #         "current_role": st.session_state["position"],
    #         "skills": st.session_state["skills"],
    #         "level": st.session_state["level"],
    #         "position": st.session_state["position"],
    #         "company": st.session_state["company"]
    #     }
         
    #     # Store it in session state so it persists during the interview.
    #      st.session_state.candidate_data = candidate_data

    #     # Convert candidate data to JSON
    #     candidate_context = json.dumps(
    #     st.session_state.candidate_data,
    #     indent=2
    #     )
    #     st.session_state.messages = [
    #         {
              
    #             "role": "system",
    #             "content": f"""
    #             You are an expert HR interviewer.

    #             Candidate information:

    #             {candidate_context}

    #             Ask exactly ONE question at a time.
    #             Base questions on the candidate's actual information.
    #             Do not invent candidate experience or skills.
    #             Ask follow-up questions based on their answers.
    #             """
    #         }
    #     ]

        # ------------------------------------------------------------------------
        # 19.4 GENERATE FIRST INTERVIEW QUESTION
            # The candidate has not answered anything yet.
            # Therefore we ask OpenAI to generate the  first interview question.
        # ------------------------------------------------------------------------
        with st.spinner("Preparing your interview questions..."):
         with measure_time("OpenAI first interview question"):
            first_response = client.chat.completions.create(
            model=st.session_state["openai_model"],
            messages=st.session_state.messages,
            reasoning_effort="none",
            max_completion_tokens=400
            )
        
        # Extract the AI's first question.
        first_question = (
            first_response.choices[0].message.content
        )

        # ------------------------------------------------------------------
        # 19.5 SAVE FIRST AI QUESTION
           # We MUST save the AI question into messages.
           # Otherwise, when the user answers, OpenAI won't
           # know what question the user was answering.
        # ------------------------------------------------------------------
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": first_question
            }
        )
    
    # ------------------------------------------------------------------
    # 19.6 DISPLAY PREVIOUS CHAT HISTORY
      # This runs on EVERY Streamlit rerun. 
      # It loops through the complete messages list and
      # displays every user and assistant message.
      # The system message is skipped because it is an
      # internal instruction and should not be visible.
    # ------------------------------------------------------------------
    for message in st.session_state.messages:
         if message["role"] != "system":
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # ------------------------------------------------------------------------------
    # 19.7 GET USER'S ANSWER
     # This is one of the MOST IMPORTANT parts of your interactive chatbot.
     # st.chat_input() displays the chat input box.
     # The program waits for the user to type an answer.
     # Once the user submits the answer, the code inside this "if" block executes.
    # ------------------------------------------------------------------------------
    # if not st.session_state.chat_complete:
    if (
    not st.session_state.chat_complete
    and not st.session_state.interview_ended
    ):
     
     prompt = st.chat_input(
        "Your answer..",
        max_chars=2000,
        key="interview_chat_input",
     )
     
     if prompt :    
            # ------------------------------------------------
            # 19.8 SAVE USER'S ANSWER
                  # The user's answer is added to the conversation history.
            # ------------------------------------------------

            candidate_id = st.session_state.get("candidate_id")
            interview_id = st.session_state.get("interview_id")

            print("DEBUG candidate_id:", repr(candidate_id))
            print("DEBUG interview_id:", repr(interview_id))

            if interview_id is None:
                st.error("No active interview record exists.")
                st.stop()

            try:
                update_interview_activity(interview_id)
            except Exception:
                st.error(
                    "Unable to save interview activity. "
                    "Please retry your answer."
                )
                st.stop()

            st.session_state.messages.append(
                {
                    "role": "user",
                    "content": prompt
                }
            )

            # ------------------------------------------------
            # 19.9 DISPLAY USER'S ANSWER
               # Shows the answer in the chat interface.
            # ------------------------------------------------
            with st.chat_message("user"):
                st.markdown(prompt)

            # ------------------------------------------------------------------
            # 19.10 INCREMENT ANSWER COUNT
              # We increment the count immediately after saving the answer.
                        # Example:
                        # Before answer 1:
                        # count = 0
                        # After answer 1:
                        # count = 1
                        #
                        # ...
                        #
                        # After answer 5:
                        #count = 5
            # ------------------------------------------------------------------
            st.session_state.user_message_count += 1

            # ---------------------------------------------------------------------
            # 19.11 CHECK WHETHER THIS WAS THE 5TH ANSWER
                # This is the most important part.
                # If count is LESS than 5:
                #  Ask OpenAI for another question.
                # If count is 5:
                #  DO NOT call OpenAI. Instead show the fixed completion message.
            # ---------------------------------------------------------------------
            if st.session_state.user_message_count < 5:
            
                # -----------------------------------------
                # 19.12 GENERATE NEXT INTERVIEW QUESTION
                # -----------------------------------------
               with st.chat_message("assistant"):
                 with measure_time("OpenAI next interview question"):
                    stream = client.chat.completions.create(

                        # The selected OpenAI model
                        model=st.session_state["openai_model"],

                        # Send the entire conversation history
                        messages=[
                            {
                                "role": m["role"],
                                "content": m["content"]
                            }
                            for m in st.session_state.messages
                        ],

                        # Disable reasoning for this request
                        reasoning_effort="none",

                        # Limit response length
                        max_completion_tokens=400,

                        # Stream the response gradually
                        stream=True
                    )

                    # Display the AI response as it is generated
                    response = st.write_stream(stream)

                 # ------------------------------------------------
                 # 19.13 SAVE AI RESPONSE TO CHAT HISTORY
                    # The AI's response is saved so that it can be
                    # sent back to OpenAI during the next question.
                 # ------------------------------------------------
                    st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": response
                    }
                )         
            else :
                # --------------------------------------------------------------------------
                # 19.14 5TH ANSWER - END THE INTERVIEW
                    # IMPORTANT:
                    # There is NO OpenAI API call here. We simply create a fixed message.
                    # This prevents AI from asking a 6th question.
                # --------------------------------------------------------------------------
                completion_message = (
                    'Thank you for your attempt, '
                    'please click on "Get Feedback" '
                    'option to view your results.'
                )

                # ------------------------------------------------------------------
                # 19.15 Save the completion message to history.
                    # This means it will still appear after the Streamlit rerun.
                # ------------------------------------------------------------------
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": completion_message
                    }
                )

                # ------------------------------------------------------------------
                # 19.16 MARK INTERVIEW AS COMPLETE
                  # The candidate has submitted the fifth answer.
                  # Save the completion timestamp to MySQL.
                # ------------------------------------------------------------------

                interview_id = st.session_state.get("interview_id")

                if interview_id is not None:
                    try:
                        end_interview_record(
                            interview_id,
                            final_status="completed",
                        )

                        st.session_state.interview_ended = True
                        st.session_state.chat_complete = True

                    except Exception:
                        st.error(
                            "Your answers were received, but we could not "
                            "save the interview completion status. Please retry."
                        )
                        st.stop()
                else:
                    st.error("No active interview record exists.")
                    st.stop()
                
                # Refresh to remove the chat input immediately
                st.rerun()

# ------------------------------------------------------------------
# 20 INTERVIEW COMPLETION STATUS
  # disable the input field after interview completion
# ------------------------------------------------------------------    
if st.session_state.chat_complete:
      st.text_input(
        "Interview completed",
        value="Thank you for the attempt , You have completed all 5 answers. Click on 'Feeback' button to proceed",
        disabled=True,
        key="completed_interview_input",
    )

# ================================================================
# 21. GET FEEDBACK BUTTON
   # This section appears after the user has submitted 5 answers. 
   # The user can then click "Get Feedback".
# ================================================================
if (
    st.session_state.chat_complete
    and st.session_state.user_message_count >= 5
    and not st.session_state.feedback_shown
):
    if st.button( "Get Feedback", type="primary"):
        show_feedback()
        st.rerun()

# ====================================================================
# 22. Saves the entire data in Database(MySQL)
    # This section runs and saves after the user gets the feedback.
# ====================================================================
import mysql.connector
import re
from decimal import Decimal

def save_interview_to_mysql(
    candidate_data,
    messages,
    feedback_text
):
    connection = None
    cursor = None

    try:
        # Extract the overall score from the feedback
        score_match = re.search(
            r"Overall\s+Score\s*:\s*\*{0,2}\s*"
            r"(10(?:\.0+)?|[0-9](?:\.\d+)?)\s*/\s*10",
            feedback_text,
            re.IGNORECASE
        )
        if not score_match:
            print("Feedback received:", repr(feedback_text[:500]))
            raise ValueError(
                "Could not extract the overall score."
                "Expected format: Overall Score: 0.0/10"
            )
        score = Decimal(score_match.group(1))
        if not Decimal("0") <= score <= Decimal("10"):
            raise ValueError("Score must be between 0 and 10.")

        # MySQL connection establishment properties
        with measure_time("MySQL connection"):
        #   connection = mysql.connector.connect(
        #     host=st.secrets["mysql"]["host"],
        #     port=st.secrets["mysql"]["port"],
        #     user=st.secrets["mysql"]["user"],
        #     password=st.secrets["mysql"]["password"],
        #     database=st.secrets["mysql"]["database"]
        # )

        # Reuse a pooled connection instead of opening a new one
            connection = get_db_connection()

        cursor = connection.cursor()
        
        # 1. Save candidate details
        name = candidate_data.get("name")
        email = candidate_data.get("email")

        # Get phone number from all supported candidate-data sources
        candidate_data = candidate_data or {}

        phone = (
            candidate_data.get("phone_number") 
            or candidate_data.get("phone") 
            or st.session_state.get("phone_number")
            or st.session_state.get("phone")
        )
        company = candidate_data.get("company")

        # Debug BEFORE executing SQL
        print("Candidate data:", repr(candidate_data))
        print("Phone value:", repr(phone))
        print("Phone type:", type(phone).__name__)
        print("Phone length:", len(str(phone)) if phone is not None else 0)

        if not phone:
            print("Candidate data received:", repr(candidate_data))
            print("Session phone_number:", repr(
               st.session_state.get("phone_number")
            ))
            print("Session phone:", repr(st.session_state.get("phone")))
            raise ValueError(
                  "Phone number is missing. Check candidate_data and session state."
            )
        
        # Reuse the existing candidate ID
        candidate_id = st.session_state.get("candidate_id")

        if candidate_id is None:
              raise ValueError("Candidate ID is missing from session state.")

        # Update the existing candidate instead of inserting a duplicate
        with measure_time("MySQL candidate insert/update"):
         cursor.execute(
            """
            UPDATE candidates
            SET phone = %s
            WHERE candidate_id = %s
            """,
          (phone, candidate_id)
        )

        # Keep the existing candidate_id; do not reassign it.
        print(f"Updated phone for candidate ID: {candidate_id}")
        
        # Save the overall interview result
        interview_id = st.session_state.get("interview_id")
        candidate_id = st.session_state.get("candidate_id")

        if interview_id is None:
            raise ValueError("Interview ID is missing.")

        if candidate_id is None:
            raise ValueError("Candidate ID is missing.")
        
        with measure_time("MySQL interview update"):
        # Verify that the interview belongs to this candidate.
            cursor.execute(
                            """
                                SELECT interview_id
                                FROM interviews
                                WHERE interview_id = %s
                                AND candidate_id = %s
                            """,
                            (interview_id, candidate_id),
                )

            interview_row = cursor.fetchone()

            if interview_row is None:
                raise ValueError(
                    f"No interview found for interview_id={interview_id}, "
                    f"candidate_id={candidate_id}. "
                    "Check the IDs in the interviews table."
            )

            # Update the existing interview record exactly once.
            cursor.execute(
                            """
                                UPDATE interviews
                                SET overall_score = %s,
                                    overall_feedback = %s,
                                    status = 'completed',
                                    ended_at = COALESCE(
                                        ended_at,
                                        CURRENT_TIMESTAMP(6)
                                    )
                                WHERE interview_id = %s
                                AND candidate_id = %s
                            """,
                (
                    score,
                    feedback_text,
                    interview_id,
                    candidate_id,
                ),
            )


        #  # Update the interview row created at the beginning.
        #     interview_id = st.session_state.get("interview_id")

        #     if interview_id is None:
        #         raise ValueError("Interview ID is missing.")

        #     cursor.execute(
        #                     """
        #                         UPDATE interviews
        #                             SET overall_score = %s,
        #                             overall_feedback = %s,
        #                             status = 'completed',
        #                             ended_at = COALESCE(
        #                                 ended_at,
        #                                 CURRENT_TIMESTAMP(6)
        #                             )
        #                         WHERE interview_id = %s
        #                         AND candidate_id = %s
        #                     """,
        #                     (
        #                         score,
        #                         feedback_text,
        #                         interview_id,
        #                         candidate_id,
        #                     ),
        #                 )   

        #     if cursor.rowcount == 0:
        #         print("DEBUG update rowcount:", cursor.rowcount)
        #     # A zero row count can also mean unchanged values.
        #          # Confirm that this interview belongs to this candidate.
        #     cursor.execute(
        #         """
        #         SELECT interview_id
        #         FROM interviews
        #         WHERE interview_id = %s
        #           AND candidate_id = %s
        #         """,
        #         (interview_id, candidate_id),
        #     )

        #     if cursor.fetchone() is None:
        #         raise ValueError(
        #             f"Interview {interview_id} was not found "
        #             f"for candidate {candidate_id}."
        #         )

        #     # Update the existing interview row.
        #     cursor.execute(
        #         """
        #         UPDATE interviews
        #         SET overall_score = %s,
        #             overall_feedback = %s,
        #             status = 'completed',
        #             ended_at = COALESCE(
        #                 ended_at,
        #                 CURRENT_TIMESTAMP(6)
        #             )
        #         WHERE interview_id = %s
        #           AND candidate_id = %s
        #         """,
        #         (
        #             score,
        #             feedback_text,
        #             interview_id,
        #             candidate_id,
        #         ),
        #     )
        # #         cursor.execute(
        # #                         """
        # #                             SELECT interview_id
        # #                             FROM interviews
        # #                             WHERE interview_id = %s
        # #                             AND candidate_id = %s
        # #                         """,
        # #                 (interview_id, candidate_id),
        # # )

        # if cursor.fetchone() is None:
        #     raise ValueError(
        #         "The interview record does not exist."
        #     )
      
        # # cursor.execute(
        # #     """
        # #     INSERT INTO interviews (
        # #         candidate_id,
        # #         overall_score,
        # #         overall_feedback,
        # #         status
        # #     )
        # #     VALUES (%s, %s, %s, %s)
        # #     """,
        # #     (
        # #         candidate_id,
        # #         score,
        # #         feedback_text,
        # #         "completed"
        # #     )
        # # )
        # # interview_id = cursor.lastrowid

        # Pair each AI question with the user's answer
        responses = []
        pending_question = None
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role == "system":
                continue
            if role == "assistant":
                # Ignore the fixed completion message
                if "click on" in content.lower() and \
                   "get feedback" in content.lower():
                    continue
                pending_question = content
            elif role == "user" and pending_question:
                responses.append((
                    interview_id,
                    len(responses) + 1,
                    pending_question,
                    content
                ))
                pending_question = None

        # Save all question-answer pairs
        if not responses:
            raise ValueError(
                "No question-and-answer pairs were found "
                "in the interview messages."
            )

        print(
            f"DEBUG: Saving {len(responses)} responses "
            f"for interview_id={interview_id}"
        )

        # if responses:
        cursor.executemany(
                """
                        INSERT INTO interview_responses (
                            interview_id,
                            question_number,
                            ai_question,
                            user_answer
                        )
                        VALUES (%s, %s, %s, %s)
                """,
                responses,
            )

            # Commit the interview update and responses together.
        with measure_time("MySQL transaction commit"):
             connection.commit()

        return {
            "success": True,
            "candidate_id": candidate_id,
            "interview_id": interview_id,
            "responses_saved": len(responses)
        }
    except Exception:
        if connection and connection.is_connected():
            connection.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


# ============================================================
# 22.1 FEEDBACK PROMPT BUILDER
# ============================================================

def build_feedback_system_prompt(total_experience):

    return f"""
    You are a professional technical interview evaluator. Evaluate the candidate strictly based on the actual interview conversation and the candidate's stated experience.
    
    **CANDIDATE EXPERIENCE**
    
     The candidate's experience is: {total_experience}
    
     Adjust expectations for technical depth, problem-solving, communication, and practical knowledge according to this experience.
    
    **OUTPUT REQUIREMENTS**
    
    **1. OVERALL SCORE**
    
        Start with:
        
        **Overall Score:** **[X/10 and the appropriate color label]**
        
        Evaluate each question individually on a scale of 0 to 5. Calculate the overall score using the average of all question scores, converted to a scale of 10:
        
        Overall Score = (Sum of all question scores / (Number of questions × 5)) × 10
        
        Round the final score to one decimal place. Do not independently invent an overall score that conflicts with the individual scores. If all five answers receive 0/5, the overall score must be 0/10.
        
    **2. OVERALL FEEDBACK**
    
        Write:
        
        **Feedback:**
        
        Provide specific strengths, weaknesses, and actionable improvements. Avoid generic advice. Base conclusions only on the conversation.
        
    **3. SCORE LEGEND**
    
        Display this exact legend:
        
        **Score Legend:** :red[Red — Poor] | :orange[Yellow — Average] | :green[Green — Good]
        
        Use the following thresholds for individual question scores:
        
            - Below 3.0/5: :red[Red (Poor)]
            - 3.0/5 to below 4.5/5: :orange[Yellow (Average)]
            - 4.5/5 and above: :green[Green (Good)]
        
        Use the following thresholds for Overall score:
                                                
            - Below 3.0/5: :**red[Red (Poor)]**
            - 3.0/5 to below 4.5/5: :**orange[Yellow (Average)]**
            - 4.5/5 and above: :**green[Green (Good)]**
    
    **4. QUESTION-BY-QUESTION EVALUATION**
    
        Evaluate every actual AI interview question in the conversation. If five questions were asked, evaluate all five. Never invent missing questions or answers.
        
        For each question, follow this exact structure:
        
        **Question 1:** [Original AI question]
        
        **Candidate Answer:** [Brief, accurate summary of the actual answer. If the candidate skipped the question, explicitly state that no technical answer was provided.]
        
        **Score:** [X/5 and the appropriate color label]
        
        **Evaluation:** [Specific strengths and shortcomings supported by the candidate's answer.]
        
        **Expected Answer:** [What a candidate with the stated experience would reasonably be expected to explain.]
        
        **Improvement:** [Concrete recommendation for improving the answer.]
        
        Repeat this structure for every actual question, preserving the original question order.
    
    **5. FORMATTING REQUIREMENTS**
    
        - Use Markdown bold formatting for all section labels and field labels, including Overall Score, Feedback, Score Legend, Question 1, Candidate Answer, Score, Evaluation, Expected Answer, and Improvement.
        - Use Streamlit-compatible Markdown color syntax for colored labels. For example:
        - `:red[Score: 0/5 — Red (Poor)]`
        - `:orange[Score: 3.5/5 — Yellow (Average)]`
        - `:green[Score: 5/5 — Green (Good)]`
        - Do not use HTML tags.
        - Keep each question's evaluation clearly separated with blank lines.
        - Make the output readable, consistent, and suitable for display in a Streamlit application.
    
    **6. EVALUATION RULES**
    
        - Be fair, evidence-based, and consistent.
        - Do not award points for claims unsupported by the answer.
        - Consider the candidate's stated experience.
        - If an answer is missing, explicitly state that it was not provided and score accordingly.
        - Do not fabricate technical details, questions, or candidate responses.
        - Keep feedback concise but useful.
        - Return feedback only. Do not ask follow-up questions.
                                               
    """

# ============================================================
# 23. FEEDBACK SECTION
   # This section appears after the user clicks "Get Feedback".
# ============================================================
if st.session_state.feedback_shown:
    st.subheader("Feedback")

    # -----------------------------------------------------------------------
    # 23.1 GENERATE FEEDBACK ONLY ONCE
    # PERFORMANCE: without this, every rerun (any button click)
    # called OpenAI again (slow, costly, and changed the score).
    # -----------------------------------------------------------------------

    if st.session_state.feedback_text is None:
        total_experience = st.session_state.candidate_data.get(
               "total_experience", "unspecified"
        )
        
        conversation_history = "\n".join(
            f"{msg['role']} : {msg['content']}"
            for msg in st.session_state.messages
            if msg["role"] != "system"   # no need to send the system prompt
        )

        with st.spinner("Evaluating your interview performance..."):
            with measure_time("OpenAI feedback generation"):

                # PERFORMANCE: stream so the user sees feedback
                # appear immediately instead of waiting for all of it    
                stream = client.chat.completions.create(
                    model = st.session_state["openai_model"],
                    messages = [
                        {
                            "role" : "system",
                            "content" : build_feedback_system_prompt(total_experience),            
                        },
                        {   
                                "role" : "user",
                                "content":(
                                    "This is the interview you need to evaluate. "
                                    "You are only a tool for evaluation and should "           
                                    f"not engage in conversaion : {conversation_history}"
                                ),
                        },
                    ],
                    reasoning_effort="low",
                    max_completion_tokens=3000,
                    stream=True,
                )

                # write_stream renders as it arrives and returns the full text
                st.session_state.feedback_text = st.write_stream(stream)
    else:
        # Already generated: just display the stored feedback
        st.markdown(st.session_state.feedback_text)

    feedback_text = st.session_state.feedback_text
    st.write(feedback_text)

    # Save the interview only once per session
    if "interview_saved" not in st.session_state:
     st.session_state.interview_saved = False

    if not st.session_state.interview_saved:
        try:
            # Refresh candidate data without overwriting existing values with blanks
            candidate_data = st.session_state.candidate_data

            # candidate_data.update({
            #     "name": st.session_state.get("name")
            #         or candidate_data.get("name", ""),
            #     "email":st.session_state.get("email")
            #         or candidate_data.get("email", ""),
            #     "company": st.session_state.get("company")
            #         or candidate_data.get("company", ""),
            # })

            phone = (
                     candidate_data.get("phone_number")
                     or candidate_data.get("phone")
                    )

            if phone:
                phone = str(phone).strip()
                   # Keep an existing hyphen if it is already present
                if phone.startswith("+") and "-" in phone:
                   full_phone = phone
                elif phone.startswith("+91") and len(phone) == 13:
                   full_phone = f"+91-{phone[3:]}"
                else:
                   full_phone = phone

                candidate_data["phone"] = full_phone
                candidate_data["phone_number"] = full_phone

            print(
                "Candidate data being saved:",
                repr(st.session_state.candidate_data)
            )
        
            result = save_interview_to_mysql(
                candidate_data=st.session_state.candidate_data,
                messages=st.session_state.messages,
                feedback_text=feedback_text
            )
        
            # Mark as saved only after the database function succeeds
            st.session_state.interview_saved = True

            # Use the candidate ID returned by the save function for logging
            print(f"Candidate ID: {result['candidate_id']}")

            # Log the interview save result
            print(
              "Interview saved successfully | "
              f"Candidate ID: {result['candidate_id']} | "
              f"Interview ID: {result['interview_id']} | "
              f"Responses saved: {result['responses_saved']}"
            )
        
        except Exception as e:
           st.error("Failed to save interview results.")
           st.exception(e)

    # -----------------------------------------------------------------------------------------
    # 23.2 Reload/restart interview button
            # Install "stream-js-eval" using "pip install stream-js-eval" and then import it.
            # It helps to execute javaScript commands directly from Streamlit,
            # allowing advanced features like page refresh and browser interaction.
    # -----------------------------------------------------------------------------------------
    if st.button("Restart Interview" , type="primary") :
       streamlit_js_eval(js_expressions = "parent.window.location.reload()")

# ============================================================
# 24. SCRIPT EXECUTION TIME
# ============================================================

script_elapsed_time = time.perf_counter() - script_start_time

print(
    f"[PERFORMANCE] Script run "
    f"{st.session_state['_run_count']} completed in "
    f"{script_elapsed_time:.3f} seconds"
)





# Updated code on 20/10/26 at 4:56pm IST


# ##########################################################################
#  AI INTERVIEW BOT ("Ibot") - STREAMLIT APPLICATION
# --------------------------------------------------------------------------
#  OVERALL FLOW OF THE APP
#    1. Candidate chooses a setup mode: "Upload Resume" or "Manual selection".
#    2a. Upload Resume  -> text is extracted -> parsed by the LLM into JSON
#                       -> saved to MySQL (candidates table).
#    2b. Manual         -> candidate fills a form -> saved to MySQL.
#    3. "Review your details" screen -> candidate can edit every field
#       (edits are written back to MySQL).
#    4. "Confirm & Start Interview" -> profile is LOCKED, an interview row
#       is created (with a frozen snapshot of the profile).
#    5. The AI asks 5 questions, one at a time (chat interface).
#    6. After the 5th answer the interview is marked "completed".
#    7. "Get Feedback" -> the LLM scores the interview -> result + every
#       question/answer pair is saved to MySQL.
#
#  IMPORTANT STREAMLIT CONCEPT
#    Streamlit re-runs this ENTIRE file from top to bottom on every user
#    interaction (button click, text input, etc.). Anything that must
#    survive between runs is stored in st.session_state.
#
#  NOTE: Lines marked "OLD VERSION - kept for reference" are commented-out
#        code from earlier versions. They are NOT executed.
# ##########################################################################


# ============================================================
# 1. IMPORT REQUIRED LIBRARIES
# ============================================================
from openai import OpenAI                          # OpenAI API client (LLM calls)
import streamlit as st                             # Web UI framework
from streamlit_js_eval import streamlit_js_eval    # Run JavaScript in the browser (page reload)
from pypdf import PdfReader                        # Read text from PDF resumes
from docx import Document                          # Read text from DOCX resumes
import json                                        # Convert dict <-> JSON text
import re                                          # Regular expressions (validation, parsing)
import time                                        # Timing for performance logs
import hashlib                                     # SHA-256 hash to detect re-uploaded files
import mysql.connector                             # MySQL database driver
import re                                          # (duplicate import - harmless)
from decimal import Decimal                        # Exact decimal numbers for scores
import secrets                                     # Secure random numbers (public candidate ID)

# ============================================================
# 2. PERFORMANCE HELPER
#   A small context manager that measures how long a block of
#   code takes and prints it to the terminal.
#   Usage:
#       with measure_time("Some operation"):
#           ...code...
#   Output:  [PERFORMANCE] Some operation: 0.123 seconds
# ============================================================
from contextlib import contextmanager

@contextmanager
def measure_time(operation_name):
    start = time.perf_counter()          # Start the timer
    try:
        yield                            # Run the code inside the "with" block
    finally:
        # Always runs, even if the block raised an error
        elapsed = time.perf_counter() - start
        print(
            f"[PERFORMANCE] {operation_name}: "
            f"{elapsed:.3f} seconds"
        )

# ============================================================
# 3. STREAMLIT PAGE CONFIGURATION
#   - Sets the browser tab title and icon.
#   - Stores the OpenAI model name in session state.
#   - Displays the main title, subtitle and caption of the app.
#   NOTE: st.set_page_config must be the first Streamlit call.
# ============================================================
st.set_page_config(
    page_title="Ibot",
    page_icon="AI_Interview_icon.png"
)

# --------------------------------------------------------
# 3.1 Store the model name once so it persists across reruns
# --------------------------------------------------------
if "openai_model" not in st.session_state:
        st.session_state["openai_model"] = "gpt-5.6-luna"

# --------------------------------------------------------
# 3.2 Page headings
# --------------------------------------------------------
st.title("Interview phase")
st.subheader(
        f"Powered by Gen AI : "
        f"{st.session_state['openai_model']}"
    )

st.caption("Interview powered assistant")

# ============================================================
# 4. TEMPORARY DIAGNOSTIC: CHECK SCRIPT RERUNS
#   Counts how many times Streamlit has re-run this script in
#   the current browser session and starts a timer for this run.
#   Useful while debugging performance; can be removed later.
# ============================================================

# --------------------------------------------------------
# 4.1 Rerun counter (stored in session state)
# --------------------------------------------------------
if "_run_count" not in st.session_state:
    st.session_state["_run_count"] = 0

st.session_state["_run_count"] += 1

# --------------------------------------------------------
# 4.2 Start timing this particular script run
#     (printed at the very end - see Section 24)
# --------------------------------------------------------
script_start_time = time.perf_counter()

st.caption(
    f"Script runs: {st.session_state['_run_count']}"
)

# --------------------------------------------------------
# 4.3 TEMPORARY: confirms .streamlit/config.toml is loaded.
#     Shows "none" or "auto". Remove once verified.
# --------------------------------------------------------
st.caption(f"File watcher: {st.get_option('server.fileWatcherType')}")

# ========================================================
# 5. CREATE OPENAI CLIENT (CACHED)
#   - The API key is read from .streamlit/secrets.toml.
#   - PERFORMANCE: @st.cache_resource creates the client (and its
#     HTTP connection pool) ONCE and reuses it on every rerun and
#     for every user, instead of building a new client each time.
# ========================================================

# --------------------------------------------------------
# 5.0.1 Cached client factory
# --------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_openai_client(api_key):
    # timeout     -> avoid hanging forever on a slow request
    # max_retries -> automatic retry on transient network errors
    return OpenAI(api_key=api_key, timeout=90, max_retries=2)

# --------------------------------------------------------
# 5.0.2 Read the API key and create the client
#     If the key is missing/empty, client = None and an error
#     message is shown on the page.
# --------------------------------------------------------
try:
    api_key = st.secrets["OPENAI_API_KEY"]
    if not api_key or not api_key.strip():
        raise ValueError("OpenAI API key is empty.")
    client = get_openai_client(api_key)
except Exception as e:
    client = None
    # Log only the error type (never the key itself)
    print(f"OpenAI client initialization failed: {type(e).__name__}")
    st.error(
        "OpenAI configuration is missing or invalid. "
        "Please check your application secrets."
    )

# ============================================================
# 5.1 MYSQL CONNECTION POOL (CACHED)
#   PERFORMANCE: opening a new MySQL connection for every query
#   costs a TCP + authentication handshake each time. A pool
#   keeps connections open and hands them out instantly.
#   conn.close() on a pooled connection returns it to the pool
#   (it does NOT actually disconnect).
#   Credentials come from the [mysql] section of secrets.toml.
# ============================================================
from mysql.connector import pooling

# --------------------------------------------------------
# 5.1.1 Create the pool once (shared by all users/reruns)
# --------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_mysql_pool():
    cfg = st.secrets["mysql"]
    return pooling.MySQLConnectionPool(
        pool_name="ibot_pool",
        pool_size=10,               # max simultaneous connections
        pool_reset_session=True,    # clean session state on reuse
        host=cfg["host"],
        port=int(cfg["port"]),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        connection_timeout=10,      # seconds to wait when connecting
    )


# --------------------------------------------------------
# 5.1.2 Borrow a connection from the pool
#       Used by every database function in this app.
#       Always call conn.close() afterwards to return it.
# --------------------------------------------------------
def get_db_connection():
    conn = get_mysql_pool().get_connection()
    # Revive the connection if MySQL closed it after being idle
    conn.ping(reconnect=True, attempts=2, delay=1)
    return conn

# ============================================================================
# 6. INITIALIZE SESSION STATE VARIABLES
#   Streamlit reruns the entire Python script whenever the user
#   interacts with the application.
#   st.session_state preserves information between these reruns.
#   These flags control which stage/screen of the app is shown.
#   Each one is created only once (the first time the page loads).
# ============================================================================

# True after the user clicks "Next" on the setup-mode screen
if "choose_setup" not in st.session_state:
    st.session_state.choose_setup = False

# Which setup the user selected: "Upload Resume" or "Manual selection"
if "setup_mode" not in st.session_state:
    st.session_state.setup_mode = None

# True after "Confirm & Start Interview" -> interview screen is shown,
# and the candidate profile becomes locked
if "setup_complete" not in st.session_state:
    st.session_state.setup_complete = False

# Number of answers the candidate has submitted (interview ends at 5)
if "user_message_count" not in st.session_state:
    st.session_state.user_message_count = 0

# True after the user clicks "Get Feedback"
if "feedback_shown" not in st.session_state:
    st.session_state.feedback_shown = False

# Full conversation history (system prompt + AI questions + user answers)
if "messages" not in st.session_state:
    st.session_state.messages = []

# True when the interview is finished (5 answers or "End Conversation")
if "chat_complete" not in st.session_state:
    st.session_state.chat_complete = False

# True after the uploaded resume has been parsed into JSON
if "resume_jsonextract_complete" not in st.session_state:
    st.session_state.resume_jsonextract_complete = False

# The candidate profile (dict) - from the resume parser or the manual form
if "candidate_data" not in st.session_state:
    st.session_state.candidate_data = None

# Stores generated feedback so it is NOT regenerated on every rerun
if "feedback_text" not in st.session_state:
    st.session_state.feedback_text = None

# --------------------------------------------------------
# 6.1 Mark resume parsing as complete
# --------------------------------------------------------
def complete_resume_processing():
    st.session_state.resume_jsonextract_complete = True

# ============================================================
# 7. FUNCTION TO CHOOSE THE SETUP
#   Callback for the "Next" button on the setup-mode screen.
#   Saves the selected mode and moves to the next stage.
# ============================================================
def setup_choose():
    # Save the selected setup mode before leaving the selectbox page
    # (the selectbox widget's own key disappears once it is hidden)
    st.session_state.setup_mode = st.session_state.setup_mode_widget

    # Move to the next setup stage
    st.session_state.choose_setup = True

# =================================================================
# 8. FUNCTION TO MARK THE SETUP AS COMPLETE
#   Callback for the "Confirm & Start Interview" button.
#   From this point the candidate profile is LOCKED.
#   NOTE: PROFILE_FIELDS is defined later in the file (Section 16.0).
#         That is fine because this function only runs when the
#         button is clicked, after the whole script has been loaded.
# =================================================================
def complete_setup():
    # Close any open edit boxes so nothing stays editable
    for field, _, _ in PROFILE_FIELDS:
        st.session_state[f"editing_{field}"] = False

    # Switch the app to the interview screen
    st.session_state.setup_complete = True

# ============================================================
# 9. FUNCTION TO SHOW FEEDBACK
#   Called when the "Get Feedback" button is clicked.
#   Switches the app to the feedback screen (Section 23).
# ============================================================
def show_feedback():
    st.session_state.feedback_shown = True

# ===============================================================
# 10. SETUP SELECTION SCREEN
#   First screen of the app. Shown only until "Next" is clicked.
#   The user chooses between "Upload Resume" and "Manual selection".
# ===============================================================
if not st.session_state.choose_setup:
        st.header("Choose mode of setup", divider="rainbow")

        # --------------------------------------------------------
        # 10.1 Setup mode dropdown
        #      Value is stored in st.session_state.setup_mode_widget
        # --------------------------------------------------------
        st.selectbox(
            "Choose setup",
            (
                "Upload Resume",
                "Manual selection",
            ),
        key="setup_mode_widget"
        )

        # --------------------------------------------------------
        # 10.2 Help note for the manual option
        # --------------------------------------------------------
        st.info(
                """
                NOTE : If you choose "Manual selection" You have to enter/choose
                Name , Experience , Skills , Company , level, postion in the next page
                after selecting Next button.
                """,
            )

        # --------------------------------------------------------
        # 10.3 "Next" button -> calls setup_choose() (Section 7)
        # --------------------------------------------------------
        if st.button(
        "Next",
        on_click=setup_choose
    ):
         st.write("Selection complete... Starting Interview...")

# ============================================================
# 11. EXTRACT TEXT FROM RESUME
#   Supported formats: PDF, DOCX, TXT
#   Checks the uploaded file's extension and uses the matching
#   library to extract plain text.
#   Returns: the resume as a single text string.
# ============================================================
def extract_resume_text(uploaded_file):
    file_name = uploaded_file.name.lower()

    # --------------------------------------------------------
    # 11.1 PDF - read every page and join the text
    # --------------------------------------------------------
    if file_name.endswith(".pdf"):
        reader = PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""   # "or ''" handles image-only pages
        return text
    # --------------------------------------------------------
    # 11.2 DOCX - read every paragraph, one per line
    # --------------------------------------------------------
    elif file_name.endswith(".docx"):
        document = Document(uploaded_file)
        text = ""
        for paragraph in document.paragraphs:
            text += paragraph.text + "\n"
        return text
    # --------------------------------------------------------
    # 11.3 TXT - decode the raw bytes as UTF-8
    # --------------------------------------------------------
    elif file_name.endswith(".txt"):
        text = uploaded_file.read().decode("utf-8")
        return text
    # --------------------------------------------------------
    # 11.4 UNSUPPORTED FILE
    # --------------------------------------------------------
    else:
        raise ValueError(
            "Unsupported file type. "
            "Please upload a PDF, DOCX, or TXT file."
        )

# ============================================================
# 12. JSON SCHEMA FOR STRUCTURED RESUME DATA
#   Tells the LLM exactly which fields to return and their types.
#   Used with OpenAI "Structured Outputs" (strict mode), so the
#   response is guaranteed to match this structure.
#   ["string", "null"] means the value may be missing (null).
# ============================================================
resume_schema = {
                "type": "object",
                "properties": {
                    # ---- Contact details ----
                    "name": {
                        "type": ["string", "null"]
                    },

                    "email": {
                        "type": ["string", "null"]
                    },

                    "phone_number": {
                        "type": ["string", "null"]
                    },

                    # ---- Current employment ----
                    "company": {
                        "type": ["string", "null"]
                    },

                    # Total years of experience as a number (e.g. 3.5)
                    "total_experience": {
                        "type": ["number", "null"]
                    },

                    "current_role": {
                        "type": ["string", "null"]
                    },

                    # ---- Skills list ----
                    "skills": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    },

                    # ---- Short prioritised summary of the resume ----
                    "summary": {
                         "type": "string"
                    },

                    # ---- Employment history: one object per job ----
                    "experience": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "company": {
                                    "type": ["string", "null"]
                                },
                                "role": {
                                    "type": ["string", "null"]
                                },
                                "duration": {
                                    "type": ["string", "null"]
                                }
                            },
                            "required": [
                                "company",
                                "role",
                                "duration"
                            ],
                            "additionalProperties": False
                        }
                    },

                    # ---- Projects list ----
                    "projects": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        }
                    }
                },

                # Strict mode requires every property to be listed here
                "required": [
                    "name",
                    "email",
                    "phone_number",
                    "company",
                    "total_experience",
                    "current_role",
                    "skills",
                    "experience",
                    "projects",
                    "summary"
                ],

                # Do not allow any extra fields
                "additionalProperties": False
            }

# ============================================================
# 13. PARSE RESUME WITH LLM
#   Sends the resume text to OpenAI and gets back a dict that
#   matches resume_schema (Section 12).
#   Steps:
#     13.1 Reject empty resumes
#     13.2 Call the OpenAI Responses API with the JSON schema
#     13.3 Convert the JSON text into a Python dict
#     13.4 Clean up / normalise the fields
# ============================================================
def parse_resume_with_llm(resume_text, client):
    # --------------------------------------------------------
    # 13.1 Reject empty or scanned (image-only) resumes
    # --------------------------------------------------------
    if not resume_text or not resume_text.strip():
        raise ValueError(
            "No readable text was found in the resume. "
            "Please upload a text-based PDF, DOCX, or TXT file."
        )

    # Shows an "Analyzing your resume" status box while running
    with st.status("Analyzing your resume"):
        # --------------------------------------------------------
        # 13.2 Call OpenAI with extraction rules + JSON schema
        # --------------------------------------------------------
        response = client.responses.create(
        model="gpt-5.6-luna",
        # PERFORMANCE: extraction is a simple task; low reasoning
        # effort is much faster with no real loss in accuracy
        reasoning={"effort": "low"},
        # Extraction rules given to the model
        instructions="""
        You are a precise resume information extraction system.

        Extract information only from the supplied resume.

        Rules:
        1. The candidate's name must be the actual person's
           name, not a programming language, framework,
           project, company, or job title.
        2. Use the resume's heading and contact section to
           identify the candidate's name.
        3. Do not treat Django, Python, Java, or other
           technical terms as a person's name.
        4. If the name is ambiguous, return null.
        5. Extract email and phone only when supported
           by the resume.
        6. Calculate total professional experience from
           employment dates when reasonably possible.
           Do not add overlapping periods twice.
        7. Do not invent missing details.
        8. Extract skills, roles, companies, and projects.
        9. Write a 4-6 sentence summary, prioritising in this order:
           (a) Name, Email and phone number,
           (b) current role and total years of experience,
           (c) core technical skills,
           (d) most significant projects and measurable outcomes,
           (e) domain / industry exposure,
           (f) education or certifications, if present.
           Do not add unsupported claims.
        10. Return only the required structured output.
        """,

        # The resume text itself
        input=resume_text,
        # Force the output to follow resume_schema exactly
        text={
            "format": {
                "type": "json_schema",
                "name": "resume",
                "strict": True,
                "schema": resume_schema
            }
        }
      )

        if not response.output_text:
           raise ValueError("The resume parser returned no output.")

        # --------------------------------------------------------
        # 13.3 Convert the JSON text into a Python dictionary
        # --------------------------------------------------------
        data = json.loads(response.output_text)

        # --------------------------------------------------------
        # 13.4 Normalise optional fields
        #      Trim spaces; turn empty strings into None.
        # --------------------------------------------------------
        data["name"] = (
            data.get("name").strip()
            if isinstance(data.get("name"), str)
            and data["name"].strip()
            else None
        )

        data["email"] = (
            data.get("email").strip()
            if isinstance(data.get("email"), str)
            and data["email"].strip()
            else None
        )

        data["phone_number"] = (
            data.get("phone_number").strip()
            if isinstance(data.get("phone_number"), str)
            and data["phone_number"].strip()
            else None
        )

        # Ensure list fields are always lists (never None)
        for field in ("skills", "projects", "experience"):
            if not isinstance(data.get(field), list):
                data[field] = []

        # Fallback text when no summary was produced
        data["summary"] = (
            data.get("summary") or
            "No summary could be generated from the available resume text."
        )
    return data

# ============================================================
# 14. PII SERVICES (LAZY-LOADED)
#   PII = Personally Identifiable Information (name, email, phone).
#   PERFORMANCE:
#   - Presidio + spaCy are imported ONLY inside the function, so
#     the app starts without loading them.
#   - Uses the small spaCy model (en_core_web_sm ~12 MB) instead of
#     the default en_core_web_lg (~550 MB).
#   - Loaded only when masking is actually enabled.
#   One-time install:  python -m spacy download en_core_web_sm
# ============================================================

# --------------------------------------------------------
# 14.1 Feature switch
#      Set to True only if you send masked_resume_text to the LLM.
#      Currently the original resume_text is sent, so masking is skipped.
# --------------------------------------------------------
USE_PII_MASKING = False

# --------------------------------------------------------
# 14.2 Build the PII analyzer + anonymizer (cached, first call only)
# --------------------------------------------------------
@st.cache_resource(show_spinner="Loading privacy engine (first time only)...")
def get_pii_engines():
    # Heavy imports kept inside the function (lazy import)
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine

    # Use the small spaCy model instead of the large default one
    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    ).create_engine()

    # Detects PII entities in text
    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine,
        supported_languages=["en"],
    )
    # Replaces detected PII with placeholders like <PERSON>
    anonymizer = AnonymizerEngine()

    # Custom recognizer: treat these company names as "COMPANY" entities
    company_recognizer = PatternRecognizer(
        supported_entity="COMPANY",
        patterns=[
            Pattern(name="tcs", regex=r"\bTCS\b", score=0.95),
            Pattern(name="infosys", regex=r"\bInfosys\b", score=0.95),
            Pattern(name="accenture", regex=r"\bAccenture\b", score=0.95),
            Pattern(
                name="capgemini",
                regex=r"\bCapgemini Technology Services\b",
                score=0.95,
            ),
        ],
        supported_language="en",
    )
    analyzer.registry.add_recognizer(company_recognizer)
    return analyzer, anonymizer


# ============================================================
# 15. MASK SENSITIVE INFORMATION USING PII
#   Returns:
#     masked_text       -> resume text with PII replaced
#     detected_entities -> {"PERSON": [...], "EMAIL_ADDRESS": [...], ...}
# ============================================================
def mask_resume_pii(resume_text):
    # Engines are created on the first call only (cached afterwards)
    analyzer, anonymizer = get_pii_engines()

    # --------------------------------------------------------
    # 15.1 Detect PII entities in the text
    # --------------------------------------------------------
    results = analyzer.analyze(
        text=resume_text,
        language="en",
        entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "COMPANY"],
    )

    # --------------------------------------------------------
    # 15.2 Record the original values before masking (no duplicates)
    # --------------------------------------------------------
    detected_entities = {}
    for result in results:
        entity_value = resume_text[result.start:result.end]
        detected_entities.setdefault(result.entity_type, [])
        if entity_value not in detected_entities[result.entity_type]:
            detected_entities[result.entity_type].append(entity_value)

    # --------------------------------------------------------
    # 15.3 Replace the detected PII in the text
    # --------------------------------------------------------
    masked_text = anonymizer.anonymize(
        text=resume_text,
        analyzer_results=results,
    ).text

    return masked_text, detected_entities

# ============================================================
# 16. SAVE CANDIDATE PROFILE TO MYSQL
#   Used by both setup modes (resume upload and manual form).
#   - Inserts a new candidate, OR updates the existing row when a
#     candidate with the same email already exists
#     (ON DUPLICATE KEY UPDATE - requires a UNIQUE key on email).
#   Returns: (internal candidate_id, 7-digit public candidate ID)
# ============================================================

# --------------------------------------------------------
# 16.0.1 Generate a random 7-digit public reference (1000000-9999999)
#      Shown to the candidate instead of the internal database ID.
# --------------------------------------------------------
def generate_candidate_reference():
    return str(secrets.randbelow(9_000_000) + 1_000_000)

# --------------------------------------------------------
# 16.0.2 Insert or update the candidate row
# --------------------------------------------------------
def save_candidate_profile(
    candidate_data,
    setup_mode,
    extracted_resume_text=None
):
    connection = None
    cursor = None
    public_id = generate_candidate_reference()

    try:
        # Reuse a pooled connection instead of opening a new one
        connection = get_db_connection()

        cursor = connection.cursor()

        # Individual values (kept for readability; the INSERT below
        # reads them directly from candidate_data)
        name = candidate_data.get("name")
        email = candidate_data.get("email")
        phone = candidate_data.get("phone_number")
        company = candidate_data.get("company")

        # Convert the Python dictionary to JSON text for MySQL
        structured_json = json.dumps(
            candidate_data,
            ensure_ascii=False
        )

        # ----------------------------------------------------
        # 16.0.2.1 INSERT new candidate, or UPDATE if the email exists.
        #   "candidate_id = LAST_INSERT_ID(candidate_id)" makes
        #   cursor.lastrowid return the EXISTING id on update.
        #   public_candidate_id is NOT overwritten on update, so a
        #   returning candidate keeps the same public ID.
        # ----------------------------------------------------
        cursor.execute(
            """
            INSERT INTO candidates (
                public_candidate_id,
                name,
                email,
                phone,
                company,
                setup_mode,
                extracted_resume_text,
                structured_data
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                candidate_id = LAST_INSERT_ID(candidate_id),
                name = VALUES(name),
                phone = VALUES(phone),
                company = VALUES(company),
                setup_mode = VALUES(setup_mode),
                extracted_resume_text =
                    VALUES(extracted_resume_text),
                structured_data = VALUES(structured_data)
            """,
            (
                public_id,
                candidate_data.get("name"),
                candidate_data.get("email"),
                candidate_data.get("phone_number")
                    or candidate_data.get("phone"),
                candidate_data.get("company"),
                setup_mode,
                extracted_resume_text,
                json.dumps(candidate_data, ensure_ascii=False)
            )
        )

        # Internal database ID (new row or existing row)
        candidate_id = cursor.lastrowid

        # ----------------------------------------------------
        # 16.0.2.2 Read back the public ID actually stored
        #        (for an existing candidate it is the old one)
        # ----------------------------------------------------
        cursor.execute(
                    """
                    SELECT public_candidate_id
                    FROM candidates
                    WHERE candidate_id = %s
                    """,
                    (candidate_id,)
                )

        public_id = cursor.fetchone()[0]

        connection.commit()

        # Log metadata only (no personal details)
        print(
            "Candidate profile saved successfully | "
            f"Candidate ID: {public_id} | "
            f"Setup mode: {setup_mode}"
        )

        return candidate_id, public_id

    except Exception:
        # Undo any partial changes, then let the caller handle the error
        if connection and connection.is_connected():
            connection.rollback()
        raise

    finally:
        # Always release the cursor and return the connection to the pool
        if cursor:
            cursor.close()

        if connection and connection.is_connected():
            connection.close()


# ============================================================
# 16.1 CANDIDATE PROFILE HELPERS (review screen: view + edit)
#   Used by the "Review your details" screen (Section 16.1).
#   Contains:
#     - PROFILE_FIELDS        : which fields are shown and how
#     - value conversion      : experience_years, as_list, ...
#     - database update       : update_candidate_profile
#     - interview prompt      : build_interview_system_prompt
#     - button callbacks      : start_edit, cancel_edit, save_edit
#     - rendering             : render_profile_value, render_profile_field
#   NOTE: these must be defined BEFORE Sections 17/18 use them.
# ============================================================

# --------------------------------------------------------
# 16.1.1 Fields shown on the review screen
#        (key in candidate_data, label on screen, input type)
#        Input types: text | number | skills | projects | summary
# --------------------------------------------------------
PROFILE_FIELDS = [
    # (field key in candidate_data, label, input kind)
    ("name", "Name", "text"),
    ("email", "Email", "text"),
    ("phone_number", "Phone number", "text"),
    ("total_experience", "Experience (years)", "number"),
    ("skills", "Skills", "skills"),
    ("projects", "Projects", "projects"),
    ("summary", "Summary", "summary"),
]


# --------------------------------------------------------
# 16.1.2 Convert experience to a number
#        Works for numbers (3.5) and free text ("3.5 years ...")
# --------------------------------------------------------
def experience_years(value):
    """Return experience as a number, e.g. '3.5 years in Python' -> 3.5."""
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


# --------------------------------------------------------
# 16.1.3 Convert a list OR a delimited string into a clean list
#        e.g. "Python, SQL" -> ["Python", "SQL"]
# --------------------------------------------------------
def as_list(value, separator=","):
    """Normalise a list or a delimited string into a clean list of strings."""
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = value.split(separator)
    else:
        items = []
    return [str(item).strip() for item in items if str(item).strip()]


# --------------------------------------------------------
# 16.1.4 Stored value -> text shown in the edit box
#        skills   -> "a, b, c"
#        projects -> one per line
#        number   -> float (capped at 60 for the number input)
# --------------------------------------------------------
def field_to_input_value(field, kind, data):
    """Value used to pre-fill the edit widget."""
    value = data.get(field)
    if kind == "number":
        return min(experience_years(value) or 0.0, 60.0)
    if kind == "skills":
        return ", ".join(as_list(value, ","))
    if kind == "projects":
        return "\n".join(as_list(value, "\n"))
    if field == "phone_number":
        return value or data.get("phone") or ""
    return value or ""


# --------------------------------------------------------
# 16.1.5 Edit box value -> validated value to store
#        Raises ValueError with a user-friendly message if invalid.
# --------------------------------------------------------
def input_to_field_value(field, kind, raw):
    """Validate and convert the edited widget value."""
    if kind == "number":
        return float(raw)
    if kind == "skills":
        return as_list(raw, ",")
    if kind == "projects":
        return as_list(raw, "\n")

    text = (raw or "").strip()
    # Name is mandatory
    if field == "name" and not text:
        raise ValueError("Name cannot be empty.")
    # Basic email format check
    if field == "email" and not re.fullmatch(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text
    ):
        raise ValueError("Please enter a valid email address.")
    # Digits, spaces, '-' and an optional leading '+'
    if field == "phone_number" and not re.fullmatch(
        r"\+?[0-9][0-9\- ]{6,18}", text
    ):
        raise ValueError(
            "Phone may contain only digits, spaces, '-' and a leading '+'."
        )
    return text or None


# --------------------------------------------------------
# 16.1.6 Save the edited profile to MySQL
#        Step 1: server-side lock check (no active interview)
#        Step 2: UPDATE the candidates row
# --------------------------------------------------------
def update_candidate_profile(candidate_id, candidate_data):
    """
        Write the edited profile back to the candidates table.
        Server-side lock: refused while this candidate has an ACTIVE
        interview. Interviews abandoned (tab closed) for 2+ hours are
        ignored so a returning candidate is not blocked forever.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        # Step 1: look for an ACTIVE interview for this candidate
        cursor.execute(
            """
            SELECT interview_id
            FROM interviews
            WHERE candidate_id = %s
              AND status = 'in_progress'
              AND ended_at IS NULL
              AND last_activity_at > NOW() - INTERVAL 2 HOUR
            LIMIT 1
            FOR UPDATE
            """,
            (candidate_id,),
        )

        # An ACTIVE interview was found -> block the edit (profile locked)
        if cursor.fetchone() is not None:
            raise ValueError("An interview is in progress; your profile is locked.")

        # Step 2: write the new values (full profile also stored as JSON)
        cursor.execute(
            """
            UPDATE candidates
            SET name = %s,
                email = %s,
                phone = %s,
                company = %s,
                structured_data = %s
            WHERE candidate_id = %s
            """,
            (
                candidate_data.get("name"),
                candidate_data.get("email"),
                candidate_data.get("phone_number")
                    or candidate_data.get("phone"),
                candidate_data.get("company"),
                json.dumps(candidate_data, ensure_ascii=False, default=str),
                candidate_id,
            ),
        )
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


# --------------------------------------------------------
# 16.1.7 Build the interviewer's system prompt from the profile
#        Used when the interview starts (Section 19.3) and after
#        a profile edit (to keep the AI's context in sync).
# --------------------------------------------------------
def build_interview_system_prompt(candidate_data):
    candidate_context = json.dumps(candidate_data, indent=2, default=str)
    return f"""
                You are an expert HR interviewer.

                Candidate information:

                {candidate_context}

                Ask exactly ONE question at a time.
                Base questions on the candidate's actual information.
                Do not invent candidate experience or skills.
                Ask follow-up questions based on their answers.
                """


# ---------------- 16.1.8 Edit button callbacks ----------------
# These run BEFORE the next rerun when a button is clicked.

# ✏️ clicked -> pre-fill the edit box and switch the field to edit mode
def start_edit(field, kind):
    st.session_state[f"input_{field}"] = field_to_input_value(
        field, kind, st.session_state.candidate_data
    )
    st.session_state[f"editing_{field}"] = True


# "Cancel" clicked -> leave edit mode without saving
def cancel_edit(field):
    st.session_state[f"editing_{field}"] = False


# "Save" clicked -> validate, save to MySQL, update session state
def save_edit(field, label, kind):
    # Work on a copy so session state changes only after a successful save
    updated = dict(st.session_state.candidate_data)

    try:
        # LOCK: no profile changes once the interview has started
        if st.session_state.get("setup_complete"):
            st.session_state[f"editing_{field}"] = False
            raise ValueError("The interview has started; your profile is locked.")

        # Validate and convert the new value
        value = input_to_field_value(
            field, kind, st.session_state.get(f"input_{field}")
        )
        updated[field] = value
        # Keep both phone keys in sync
        if field == "phone_number":
            updated["phone"] = value

        candidate_id = st.session_state.get("candidate_id")
        if candidate_id is None:
            raise ValueError("Candidate ID is missing; cannot save.")

        # Write to the database
        update_candidate_profile(candidate_id, updated)

        # Database save succeeded -> update the in-memory profile
        st.session_state.candidate_data = updated

        # Keep the interviewer's context in sync with the edited profile
        messages = st.session_state.get("messages") or []
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] = build_interview_system_prompt(updated)

        # Leave edit mode and show a success message
        st.session_state[f"editing_{field}"] = False
        st.session_state.profile_notice = ("success", f"{label} updated.")

    # Validation / lock errors -> show the message to the user
    except ValueError as e:
        st.session_state.profile_notice = ("error", str(e))
    # Duplicate email (UNIQUE key on candidates.email)
    except mysql.connector.IntegrityError:
        st.session_state.profile_notice = (
            "error", "This email is already linked to another candidate."
        )
    # Any other error -> generic message, error type logged to terminal
    except Exception as e:
        print(f"Profile update failed: {type(e).__name__}")
        st.session_state.profile_notice = (
            "error", f"Could not save {label}. Please try again."
        )


# ---------------- 16.1.9 Rendering ----------------

# Display a field's value in read-only form
def render_profile_value(field, kind, data):
    value = data.get(field)

    if kind == "number":
        # e.g. "2 years"
        years = experience_years(value)
        st.markdown(f"{years:g} years" if years is not None else "_Not provided_")
    elif kind == "skills":
        # Each skill shown as a small code-style tag
        skills = as_list(value, ",")
        st.markdown(" ".join(f"`{s}`" for s in skills) if skills else "_Not provided_")
    elif kind == "projects":
        # Bulleted list
        projects = as_list(value, "\n")
        st.markdown("\n".join(f"- {p}" for p in projects) if projects else "_Not provided_")
    else:
        # Plain text (name, email, phone, summary)
        if field == "phone_number":
            value = value or data.get("phone")
        st.markdown(value or "_Not provided_")


# Display one field: label + ✏️ button (view mode)
#                  or input box + Save/Cancel (edit mode)
def render_profile_field(field, label, kind):
    data = st.session_state.candidate_data or {}
    editing = st.session_state.get(f"editing_{field}", False)

    # Row with the field label on the left and the ✏️ button on the right
    label_col, button_col = st.columns([4, 1], vertical_alignment="center")
    label_col.markdown(f"**{label}**")

    # ---- VIEW MODE ----
    if not editing:
        button_col.button(
            "✏️",
            key=f"edit_btn_{field}",
            help=f"Edit {label}",
            on_click=start_edit,
            args=(field, kind),
        )
        render_profile_value(field, kind, data)
        return

    # ---- EDIT MODE: show the right input widget for the field type ----
    input_key = f"input_{field}"
    if kind == "number":
        st.number_input(
            label, key=input_key, min_value=0.0, max_value=60.0,
            step=0.5, label_visibility="collapsed",
        )
    elif kind == "skills":
        st.text_area(
            label, key=input_key, placeholder="Comma-separated, e.g. Python, SQL",
            label_visibility="collapsed",
        )
    elif kind == "projects":
        st.text_area(
            label, key=input_key, placeholder="One project per line",
            label_visibility="collapsed",
        )
    elif kind == "summary":
        st.text_area(label, key=input_key, height=220, label_visibility="collapsed")
    else:
        st.text_input(label, key=input_key, label_visibility="collapsed")

    # Save / Cancel buttons side by side
    save_col, cancel_col = st.columns(2)
    save_col.button(
        "Save", key=f"save_btn_{field}", type="primary",
        use_container_width=True, on_click=save_edit, args=(field, label, kind),
    )
    cancel_col.button(
        "Cancel", key=f"cancel_btn_{field}",
        use_container_width=True, on_click=cancel_edit, args=(field,),
    )

# ============================================================
# 16.2 PROFILE REVIEW SCREEN (SHARED BY UPLOAD + MANUAL)
#   The candidate reviews and edits the profile BEFORE the
#   interview starts. The AI generates its questions from this
#   profile, so it is locked once the interview begins.
#   start_button_key must be unique per screen (Streamlit rule).
# ============================================================
def render_profile_review(start_button_key):
    # Two blank lines before the review section
    st.write("")
    st.write("")

    st.subheader("Review your details", divider="rainbow")
    st.caption(
        "Please check your details. You can edit any field now. "
        "Once the interview starts, your profile is locked."
    )

    # --------------------------------------------------------
    # 16.2.1 Success / error message from the last Save click
    #        pop() shows it once and then removes it
    # --------------------------------------------------------
    notice = st.session_state.pop("profile_notice", None)
    if notice:
        level, text = notice
        (st.success if level == "success" else st.error)(text)

    # --------------------------------------------------------
    # 16.2.2 One bordered card per field
    # --------------------------------------------------------
    for field, label, kind in PROFILE_FIELDS:
        # Summary only exists for resume uploads
        if field == "summary" and st.session_state.setup_mode != "Upload Resume":
            continue
        with st.container(border=True):
            render_profile_field(field, label, kind)

    # --------------------------------------------------------
    # 16.2.3 Block starting while an edit box is still open
    #        (prevents starting with unsaved changes)
    # --------------------------------------------------------
    any_editing = any(
        st.session_state.get(f"editing_{field}", False)
        for field, _, _ in PROFILE_FIELDS
    )
    if any_editing:
        st.warning("Save or cancel your open edits before starting the interview.")

    # --------------------------------------------------------
    # 16.2.4 Start button -> complete_setup() (Section 8)
    # --------------------------------------------------------
    st.button(
        "Confirm & Start Interview",
        type="primary",
        key=start_button_key,
        on_click=complete_setup,
        disabled=any_editing,
        use_container_width=True,
    )
# ============================================================
# 17. CHOICE 1 - RESUME UPLOAD
#   Shown when the user chose "Upload Resume" and the interview
#   has not started yet.
#   Steps:
#     17.0.1 Upload the file
#     17.0.2 Skip processing if this exact file was already processed
#     17.0.3 Extract text -> (optional PII masking) -> LLM parsing
#     17.0.4 Format the phone number
#     17.0.5 Save to MySQL and store IDs in session state
#     17.1   Show the "Review your details" screen
# ============================================================
if (st.session_state.choose_setup and
    st.session_state.setup_mode == "Upload Resume"
    and not st.session_state.setup_complete
) :
    st.header("Upload Resume", divider="rainbow")

    # --------------------------------------------------------
    # 17.0.1 File uploader (PDF / DOCX / TXT)
    # --------------------------------------------------------
    uploaded_resume = st.file_uploader(
        "Upload your resume",
        type=["pdf", "docx", "txt"],
        key="resume_uploader"
    )
    if uploaded_resume:
        st.success("Resume uploaded successfully!")

        # --------------------------------------------------------
        # 17.0.2 Fingerprint the file (SHA-256) so it is NOT
        #        re-processed on every Streamlit rerun.
        # --------------------------------------------------------
        file_hash = hashlib.sha256(
        uploaded_resume.getvalue()
        ).hexdigest()

        # Process only if this file has not already been processed
        if st.session_state.get("processed_resume_hash") != file_hash:

            try :
              # ----------------------------------------------------
              # 17.0.3 (a) Extract text from the uploaded file
              # ----------------------------------------------------
              with measure_time("Resume text extraction"):
                 resume_text = extract_resume_text(uploaded_resume)

                # ----------------------------------------------------
                # 17.0.3 (b) Detect and mask PII ONLY when enabled
                #   (skipping it saves several seconds per resume)
                #   NOTE: this "if" is indented inside the
                #   "Resume text extraction" timer above, so its time
                #   is included in that measurement.
                # ----------------------------------------------------
                 if USE_PII_MASKING:
                  with st.spinner("Detecting and masking sensitive information..."):
                      with measure_time("PII detection and masking"):
                          masked_resume_text, detected_entities = mask_resume_pii(resume_text)

              # ----------------------------------------------------
              # 17.0.3 (c) Send the resume text to the LLM for parsing
              # ----------------------------------------------------
              with measure_time("OpenAI resume parsing"):
                # resume_json = parse_resume_with_llm(   (old variable name)
                candidate_data = parse_resume_with_llm(
                 resume_text, # Use this when you want to pass the same exact orignial resume data without masking
                 # masked_resume_text, # Use this when you want to pass the masked resume data
                 client
              )

              # ----------------------------------------------------
              # 17.0.4 Format the extracted phone number
              #   "+..."          -> keep as is
              #   "91XXXXXXXXXX"  -> "+91-XXXXXXXXXX"
              #   anything else   -> keep unchanged
              # ----------------------------------------------------
              phone_number = candidate_data.get("phone_number")

              if phone_number:
                   phone_number = str(phone_number).strip()

                   if phone_number.startswith("+"):
                       # Country code is already present
                       full_phone = phone_number
                   elif phone_number.startswith("91") and len(phone_number) == 12:
                    # Indian country code is present without "+"
                       full_phone = f"+{phone_number[:2]}-{phone_number[2:]}"
                   else:
                       # Keep the number unchanged when the country code is unknown
                       full_phone = phone_number

                   # Keep both phone keys in sync
                   candidate_data["phone_number"] = full_phone
                   candidate_data["phone"] = full_phone

              # Store structured data in session state
              st.session_state.candidate_data = candidate_data

              # ----------------------------------------------------
              # 17.0.5 Save resume text + structured data to MySQL
              # ----------------------------------------------------
              with st.spinner("Saving candidate profile..."):
               with measure_time("MySQL candidate profile save - Resume"):
                  candidate_id, public_id = save_candidate_profile(
                  candidate_data=candidate_data,
                  setup_mode="Upload Resume",
                  extracted_resume_text=resume_text
              )

              # Preserve the IDs for the interview-saving functions
              st.session_state.candidate_id = candidate_id
              st.session_state.public_candidate_id = public_id
              st.session_state.candidate_data = candidate_data

              # Mark processing complete only after successful saving
              st.session_state.processed_resume_hash = file_hash
              st.session_state.candidate_profile_saved = True

              # Log only metadata, not the resume or personal details
              print(
                 "Resume processing completed successfully | "
                 f"Candidate ID: {public_id} | "
                 f"File hash: {file_hash[:12]}"
              )

              # Mark resume processing as complete
              complete_resume_processing()

            # --------------------------------------------------------
            # 17.0.6 Any failure in 17.0.3 - 17.0.5
            #        Print full traceback to the terminal, show a
            #        friendly error, and stop this run.
            # --------------------------------------------------------
            except Exception as e:
              st.session_state.candidate_profile_saved = False

              # Print the complete error and line number in the terminal
              import traceback
              traceback.print_exc()

              # Log the error type, not the resume or personal information
              print(f"Resume processing failed: {type(e).__name__}")

              st.error(
                  "We couldn't save your resume details. "
                  "Please check the application console for details."
              )
              st.stop()

        # ------------------------------------------------------------
        # 17.1 REVIEW EXTRACTED DETAILS BEFORE STARTING
        #   Shown only after the resume was parsed AND saved.
        # ------------------------------------------------------------
        if st.session_state.get("candidate_profile_saved", False):
            render_profile_review(start_button_key="start_resume_interview")

# ==================================================================
# 18. CHOICE 2 - MANUAL SELECTION "PERSONAL INFORMATION FORM"
#   Shown only BEFORE the interview starts, if the user chose
#   "Manual selection", and until the form has been submitted.
#   The user enters:
#     - Name, Email, Phone (with country code)
#     - Experience, Skills
#     - Level, Position, Company
#   On a valid submit the profile is saved to MySQL and the app
#   should move to the review screen (see 18.15).
# ==================================================================
if  (
    st.session_state.choose_setup
    and st.session_state.setup_mode == "Manual selection"
    and not st.session_state.setup_complete
    # Hide the form once it was submitted; the review screen takes over
    and not st.session_state.get("manual_profile_saved", False)
):
    st.subheader("Personal informaton", divider="rainbow")

    # --------------------------------------------------------
    # 18.0 Initialize default values before creating widgets
    #      (each widget below reads its value from these keys)
    # --------------------------------------------------------
    defaults = {
        "name": "",
        "email": "",
        "phone_number": "",
        "experience": "",
        "skills": "",
        "level": "Junior",
        "position": "Data Scientist",
        "company": "Netflix",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # A form groups the inputs: nothing reruns until "submit" is clicked
    with st.form("interview_setup_form") :

       # --------------------------------------------------------
       # 18.1 Name input
       # --------------------------------------------------------
        st.text_input(
            "Name",
            max_chars=40,
            placeholder="Enter your name",
            key="name"
        )

        # --------------------------------------------------------
        # 18.2 Email input
        # --------------------------------------------------------
        st.text_input(
            "Email",
            max_chars=40,
            placeholder="Enter your email",
            key="email"
        )

        # --------------------------------------------------------
        # 18.3 Phone number input
        #      Left column: country code, right column: number
        # --------------------------------------------------------
        phone_col1, phone_col2 = st.columns([1, 2])

        with phone_col1:
            st.selectbox(
              "Country code",
              options=[
                "+91",  # India
                "+1",   # US/Canada
                "+33",  # France
                "+44",  # UK
                "+61",  # Australia
                "+81",  # Japan
                "+49",  # Germany
                "+971", # UAE
            ],
            key="phone_country_code",
            )

        with phone_col2:
           st.text_input(
           "Phone number",
           max_chars=10,
           placeholder="10-digit mobile number",
           key="phone_number",
        )

        # --------------------------------------------------------
        # 18.4 Experience input (free text)
        # --------------------------------------------------------
        st.text_area(
            "Experience",
            max_chars=300,
            placeholder="Describe your experience",
            key="experience"
        )

        # --------------------------------------------------------
        # 18.5 Skills input (free text, comma-separated recommended)
        # --------------------------------------------------------
        st.text_area(
            "Skills",
            max_chars=100,
            placeholder="List your skills",
            key="skills"
        )

        # --------------------------------------------------------
        # 18.6 COMPANY AND POSITION INFORMATION
        # --------------------------------------------------------
        st.subheader("Company and Position", divider="rainbow")

        # --------------------------------------------------------
        # 18.7 Two columns for Level and Position
        # --------------------------------------------------------
        col1, col2 = st.columns(2)

        # --------------------------------------------------------
        # 18.8 Interview level selection
        # --------------------------------------------------------
        with col1:
            st.radio(
                "Choose level",
                key="level",
                options=["Junior", "Mid-level", "Senior"],
            )

        # --------------------------------------------------------
        # 18.9 Position selection
        # --------------------------------------------------------
        with col2:
            st.selectbox(
                "Choose a position",
                options = [
                    "Data Scientist",
                    "Full Stack Developer",
                    "ML Engineer",
                    "Sales executive",
                    "Nodejs developer",
                    "SD L1 Analyst",
                    "SD Lead",
                    "SD Manager",
                    "Service Delivery Manager",
                    "Front end Developer(React/Angular)",
                    "dot net Developer"
                ],
                key="position",
            )

        # --------------------------------------------------------
        # 18.10 Company selection
        # --------------------------------------------------------
        st.selectbox(
            "Choose a Company",
            options = [
                "Amazon",
                "Meta",
                "Udemy",
                "365 Company",
                "Netflix",
                "LinkedIn",
                "Spotify",
                "Capgemini Technology Services",
                "IBM",
                "Accenture",
                "TCS",
                "Infosys",
            ],
            key="company",
        )

        # -------------------------------------------------------------------------
        # 18.11 FORM SUBMIT BUTTON
        #   "submitted" is True only on the rerun right after the click.
        #   Validation and saving happen in 18.12 - 18.14 below.
        # -------------------------------------------------------------------------
        submitted = st.form_submit_button(
            "Start Interview",
            type="primary",
        )

    # ------------------------------------------------------------------
    # 18.12 FORM VALIDATION CHECKS
    #   - Email must end in ".com"
    #   - Phone must be exactly 10 digits
    # ------------------------------------------------------------------
    if submitted:
         email = st.session_state["email"].strip()
         phone = st.session_state["phone_number"].strip()

         # Require an email address ending in .com
         email_pattern = (
             r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.com$"
         )

         # Require exactly 10 digits
         phone_pattern = r"^[0-9]{10}$"

         email_valid = re.fullmatch(email_pattern, email) is not None
         phone_valid = re.fullmatch(phone_pattern, phone) is not None

         # Show an error for each invalid field
         if not email_valid:
          st.error(
            "Please enter a valid email address ending in "
            ".com, for example name@gmail.com."
        )
         if not phone_valid:
          st.error(
            "Phone number must contain exactly 10 digits "
            "without spaces or special characters."
        )

         # --------------------------------------------------------------
         # Both fields valid -> build the candidate profile dict
         # Phone is stored as "<country code>-<number>", e.g. "+91-9876543210"
         # --------------------------------------------------------------
         if email_valid and phone_valid:
          phone_number = st.session_state.get("phone_number", "").strip()
          country_code = st.session_state.get("phone_country_code", "+91")

          full_phone = f"{country_code}-{phone_number}"

          st.session_state.candidate_data = {
            "name": st.session_state["name"].strip(),
            "email": email,
            "phone": full_phone,
            "phone_number": full_phone,
            "total_experience": st.session_state["experience"],
            "current_role": st.session_state["position"],
            "skills": st.session_state["skills"],
            "level": st.session_state["level"],
            "position": st.session_state["position"],
            "company": st.session_state["company"],
          }

          # --------------------------------------------------------------
          # 18.13 PRINT THE INFORMATION ENTERED BY THE USER TO THE CONSOLE
          #       (debug output in the terminal only)
          # --------------------------------------------------------------
          candidate = st.session_state.candidate_data
          print("\n========== CANDIDATE INFORMATION ==========")
          print(f"Name: {candidate['name']}")
          print(f"Email: {candidate['email']}")
          print(f"Phone: {candidate['phone']}")
          print(f"Experience: {candidate['total_experience']}")
          print(f"Skills: {candidate['skills']}")
          print(
                f"Position: {candidate['level']} "
                f"{candidate['position']} at {candidate['company']}"
            )
          print("===========================================\n")

          # --------------------------------------------------------------
          # 18.14 SAVE CANDIDATE PROFILE TO MYSQL
          #   On success -> mark manual_profile_saved and rerun, which
          #   hides this form (see the Section 18 condition).
          # --------------------------------------------------------------
          try:
             with st.spinner("Saving candidate profile..."):
              with measure_time("MySQL candidate profile save - Manual"):
                candidate_id, public_id = save_candidate_profile(
                candidate_data=st.session_state.candidate_data,
                setup_mode="Manual selection",
                extracted_resume_text=None
             )

             # Preserve the IDs for the interview-saving functions
             st.session_state.candidate_id = candidate_id
             st.session_state.public_candidate_id = public_id
             st.session_state.candidate_profile_saved = True
            #  st.session_state.candidate_id = candidate_id   (duplicate - old)

             print(
                "Manual candidate profile saved successfully | "
                f"Candidate ID: {candidate_id}"
             )

             # Go to the review screen (do NOT start the interview yet)
             st.session_state.manual_profile_saved = True
             st.rerun()

          except Exception as e:
            st.session_state.candidate_profile_saved = False
            # Log only the error type
            print(
                "Candidate profile save failed: "
                f"{type(e).__name__}"
            )
            st.error(
                "We couldn't save your candidate details. "
                "Please try again."
            )

# ==================================================================
# 18.15 MANUAL SELECTION: REVIEW DETAILS BEFORE STARTING
#   Shown after the manual form is saved (the form above is hidden
#   at that point). The candidate can also add Projects here
#   (the form doesn't have that field).
#   NOTE: must stay at the top level (not inside Section 18), because
#   Section 18 no longer runs once manual_profile_saved is True.
# ==================================================================
if (
    st.session_state.choose_setup
    and st.session_state.setup_mode == "Manual selection"
    and not st.session_state.setup_complete
    and st.session_state.get("manual_profile_saved", False)
):
    render_profile_review(start_button_key="start_manual_interview")

# ============================================================
# 18.16 INTERVIEW DATABASE FUNCTIONS
#   create_interview_record   -> new row when the interview starts
#   update_interview_activity -> touch last_activity_at per answer
#   end_interview_record      -> mark ended/completed (once only)
# ============================================================

# --------------------------------------------------------
# 18.16.1 Create the interview row (status = 'in_progress')
# --------------------------------------------------------
def create_interview_record(candidate_id, candidate_data):
    """
    Create an interview row when the interview actually starts.
    candidate_snapshot freezes the exact profile used for this
    interview, so later profile edits never change its history.

    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO interviews (
                candidate_id,
                status,
                candidate_snapshot,
                created_at,
                last_activity_at
            )
            VALUES (
                %s,
                'in_progress',
                %s,
                CURRENT_TIMESTAMP(6),
                CURRENT_TIMESTAMP(6)
            )
            """,
            (
                candidate_id,
                # Frozen copy of the profile as JSON
                json.dumps(candidate_data, ensure_ascii=False, default=str),

            ),
        )

        # The new interview's auto-increment ID
        interview_id = cursor.lastrowid
        conn.commit()
        return interview_id

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


# --------------------------------------------------------
# 18.16.2 Record activity each time the candidate answers
#         Fails (ValueError) if the interview is no longer active.
# --------------------------------------------------------
def update_interview_activity(interview_id):
    """Record activity when a candidate submits an answer."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE interviews
            SET last_activity_at = CURRENT_TIMESTAMP(6)
            WHERE interview_id = %s
              AND status = 'in_progress'
              AND ended_at IS NULL
            """,
            (interview_id,),
        )

        # 0 rows -> interview was already ended/completed
        if cursor.rowcount == 0:
            raise ValueError("Interview is no longer active.")

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

# ============================================================
# 18.16.3 END THE INTERVIEW IN MYSQL
#   Used by:
#     - "End Conversation" button (status = 'ended')
#     - 5th answer submitted      (status = 'completed')
#   The WHERE clause makes sure it only ends an active interview,
#   so it can never be ended twice.
#   Returns True if a row was actually updated.
# ============================================================

def end_interview_record(interview_id, final_status="ended"):
    """End an interview exactly once."""
    # Only these two final statuses are allowed
    if final_status not in ("ended", "completed"):
        raise ValueError("Invalid interview status.")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            UPDATE interviews
            SET status = %s,
                ended_at = CURRENT_TIMESTAMP(6)
            WHERE interview_id = %s
              AND status = 'in_progress'
              AND ended_at IS NULL
            """,
            (final_status, interview_id),
        )

        conn.commit()
        return cursor.rowcount == 1

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

# ============================================================
# 18.17 INTERVIEW LIFECYCLE STATE
#   interview_id    -> database ID of the current interview
#   interview_ended -> True once ended or completed
#   interview_saved -> True once feedback + answers are saved
# ============================================================

if "interview_id" not in st.session_state:
    st.session_state.interview_id = None

if "interview_ended" not in st.session_state:
    st.session_state.interview_ended = False

if "interview_saved" not in st.session_state:
    st.session_state.interview_saved = False


# --------------------------------------------------------
# 18.17.1 Create exactly ONE interview row for this session
#   Runs on the first rerun after "Confirm & Start Interview".
#   interview_id is None only the first time, so it never
#   creates a second row.
# --------------------------------------------------------
if (
    st.session_state.setup_complete
    and st.session_state.get("candidate_id") is not None
    and st.session_state.interview_id is None
):
    try:
        st.session_state.interview_id = (
            create_interview_record(
                st.session_state.candidate_id,
                st.session_state.candidate_data,   # frozen profile snapshot
            )
        )
    except Exception:
        st.error(
            "Unable to create the interview record. "
            "Please retry."
        )
        st.stop()

# ============================================================
# 18.18 SIDEBAR - INTERVIEW INFO + END CONVERSATION
#   Shown only after the interview has started.
#   Displays candidate name, interview ID, public candidate ID,
#   and either the "End Conversation" button or an
#   "interview has ended" message.
# ============================================================
with st.sidebar:
    st.subheader("Interview")

    if st.session_state.setup_complete:
        candidate_data = st.session_state.get("candidate_data") or {}

        # --------------------------------------------------------
        # 18.18.1 Candidate / interview identifiers
        # --------------------------------------------------------
        st.caption(f"Candidate: {candidate_data.get('name') or 'Candidate'}")
        st.caption(f"Interview ID: {st.session_state.interview_id or 'Not created'}")
        st.caption(
            f"Candidate ID: "
            f"{st.session_state.get('public_candidate_id') or 'Not available'}"
        )

        # --------------------------------------------------------
        # 18.18.2 Ended message OR "End Conversation" button
        # --------------------------------------------------------
        if st.session_state.interview_ended:
            st.info("This interview has ended.")

        elif st.button(
            "End Conversation",
            key="end_interview_button",
            use_container_width=True,
        ):
            try:
                interview_id = st.session_state.interview_id
                if interview_id is None:
                    raise ValueError("No interview record exists.")

                # Mark as 'ended' in MySQL, then lock the chat
                end_interview_record(interview_id, final_status="ended")
                st.session_state.interview_ended = True
                st.session_state.chat_complete = True
                st.rerun()

            except Exception:
                st.error("Unable to end the interview. Please try again.")

# ============================================================
# 19. INTERVIEW / CHATBOT SECTION
#   This section runs only when:
#     1. Setup is complete
#     2. Feedback has NOT been shown
#     3. Chat is NOT complete
#   This is the main interactive chatbot section.
# ============================================================
if (
    st.session_state.setup_complete
    and not st.session_state.feedback_shown
    and not st.session_state.chat_complete
):

    # --------------------------------------------------------
    # 19.1 Display initial interview greeting
    # --------------------------------------------------------
    candidate_name = (
    st.session_state.candidate_data.get("name")
    )
    st.info(
        f"""
        Hi {candidate_name}, thank you for appling for this role,
        very excited to take interview for you.. Here's your first question!
        """,
        icon="👏"
    )

    # ------------------------------------------------------------------
    # 19.2 SELECT THE OPENAI MODEL
    #   The model name is stored in session_state so it persists
    #   between Streamlit reruns. (Already set in Section 3.1;
    #   this is a safety fallback.)
    # ------------------------------------------------------------------
    if "openai_model" not in st.session_state:
        st.session_state["openai_model"] = "gpt-5.6-luna"

    # ------------------------------------------------------------------
    # 19.3 CREATE THE INITIAL SYSTEM MESSAGE (first run only)
    #   Tells the AI what role it plays and gives it the confirmed
    #   candidate profile (name, experience, skills, level, position,
    #   company, ...). This message is NOT displayed to the user.
    # ------------------------------------------------------------------

    if not st.session_state.messages:
        st.session_state.messages = [
            {
                "role": "system",
                "content": build_interview_system_prompt(
                    st.session_state.candidate_data
                ),
            }
        ]
   
        # ------------------------------------------------------------------------
        # 19.4 GENERATE FIRST INTERVIEW QUESTION (first run only)
        #   The candidate has not answered anything yet, so we ask
        #   OpenAI to generate the first interview question.
        #   reasoning_effort="none" -> fastest response
        # ------------------------------------------------------------------------
        with st.spinner("Preparing your interview questions..."):
         with measure_time("OpenAI first interview question"):
            first_response = client.chat.completions.create(
            model=st.session_state["openai_model"],
            messages=st.session_state.messages,
            reasoning_effort="none",
            max_completion_tokens=400
            )

        # Extract the AI's first question text
        first_question = (
            first_response.choices[0].message.content
        )

        # ------------------------------------------------------------------
        # 19.5 SAVE FIRST AI QUESTION
        #   Must be saved into messages, otherwise when the user
        #   answers, OpenAI won't know which question was answered.
        # ------------------------------------------------------------------
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": first_question
            }
        )

    # ------------------------------------------------------------------
    # 19.6 DISPLAY PREVIOUS CHAT HISTORY
    #   Runs on EVERY rerun. Loops through all messages and shows
    #   every user and assistant message. The system message is
    #   skipped because it is an internal instruction.
    # ------------------------------------------------------------------
    for message in st.session_state.messages:
         if message["role"] != "system":
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    # ------------------------------------------------------------------------------
    # 19.7 GET USER'S ANSWER
    #   st.chat_input() shows the chat box at the bottom of the page.
    #   When the user submits an answer, the code inside "if prompt:" runs.
    #   The input is hidden once the interview has ended.
    # ------------------------------------------------------------------------------
    # if not st.session_state.chat_complete:   (old condition)
    if (
    not st.session_state.chat_complete
    and not st.session_state.interview_ended
    ):

     prompt = st.chat_input(
        "Your answer..",
        max_chars=2000,
        key="interview_chat_input",
     )

     if prompt :
            # ------------------------------------------------
            # 19.8 SAVE USER'S ANSWER
            #   (a) Make sure an active interview record exists
            #   (b) Update last_activity_at in MySQL
            #   (c) Add the answer to the conversation history
            # ------------------------------------------------

            candidate_id = st.session_state.get("candidate_id")
            interview_id = st.session_state.get("interview_id")

            # Debug output in the terminal
            print("DEBUG candidate_id:", repr(candidate_id))
            print("DEBUG interview_id:", repr(interview_id))

            # (a) No interview row -> cannot continue
            if interview_id is None:
                st.error("No active interview record exists.")
                st.stop()

            # (b) Record activity (fails if the interview was ended)
            try:
                update_interview_activity(interview_id)
            except Exception:
                st.error(
                    "Unable to save interview activity. "
                    "Please retry your answer."
                )
                st.stop()

            # (c) Append the answer to the history
            st.session_state.messages.append(
                {
                    "role": "user",
                    "content": prompt
                }
            )

            # ------------------------------------------------
            # 19.9 DISPLAY USER'S ANSWER
            #   Shows the answer in the chat interface immediately.
            # ------------------------------------------------
            with st.chat_message("user"):
                st.markdown(prompt)

            # ------------------------------------------------------------------
            # 19.10 INCREMENT ANSWER COUNT
            #   Before answer 1: count = 0
            #   After answer 1 : count = 1
            #   ...
            #   After answer 5 : count = 5
            # ------------------------------------------------------------------
            st.session_state.user_message_count += 1

            # ---------------------------------------------------------------------
            # 19.11 CHECK WHETHER THIS WAS THE 5TH ANSWER
            #   count < 5 -> ask OpenAI for the next question (19.12)
            #   count = 5 -> DO NOT call OpenAI; show a fixed completion
            #                message and end the interview (19.14)
            # ---------------------------------------------------------------------
            if st.session_state.user_message_count < 5:

                # -----------------------------------------
                # 19.12 GENERATE NEXT INTERVIEW QUESTION
                #   Sends the whole conversation and streams
                #   the reply into an assistant chat bubble.
                # -----------------------------------------
               with st.chat_message("assistant"):
                 with measure_time("OpenAI next interview question"):
                    stream = client.chat.completions.create(

                        # The selected OpenAI model
                        model=st.session_state["openai_model"],

                        # Send the entire conversation history
                        messages=[
                            {
                                "role": m["role"],
                                "content": m["content"]
                            }
                            for m in st.session_state.messages
                        ],

                        # Disable reasoning for this request (fastest)
                        reasoning_effort="none",

                        # Limit response length
                        max_completion_tokens=400,

                        # Stream the response gradually
                        stream=True
                    )

                    # Display the AI response as it is generated
                    # (returns the full text when finished)
                    response = st.write_stream(stream)

                 # ------------------------------------------------
                 # 19.13 SAVE AI RESPONSE TO CHAT HISTORY
                 #   Saved so it is sent back to OpenAI with the
                 #   next answer and shown again after reruns.
                 # ------------------------------------------------
                    st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": response
                    }
                )
            else :
                # --------------------------------------------------------------------------
                # 19.14 5TH ANSWER - END THE INTERVIEW
                #   There is NO OpenAI call here; we use a fixed message.
                #   This prevents the AI from asking a 6th question.
                # --------------------------------------------------------------------------
                completion_message = (
                    'Thank you for your attempt, '
                    'please click on "Get Feedback" '
                    'option to view your results.'
                )

                # ------------------------------------------------------------------
                # 19.15 Save the completion message to history
                #   so it still appears after the Streamlit rerun.
                # ------------------------------------------------------------------
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": completion_message
                    }
                )

                # ------------------------------------------------------------------
                # 19.16 MARK INTERVIEW AS COMPLETE
                #   Save status = 'completed' + timestamp in MySQL,
                #   then lock the chat.
                # ------------------------------------------------------------------

                interview_id = st.session_state.get("interview_id")

                if interview_id is not None:
                    try:
                        end_interview_record(
                            interview_id,
                            final_status="completed",
                        )

                        st.session_state.interview_ended = True
                        st.session_state.chat_complete = True

                    except Exception:
                        st.error(
                            "Your answers were received, but we could not "
                            "save the interview completion status. Please retry."
                        )
                        st.stop()
                else:
                    st.error("No active interview record exists.")
                    st.stop()

                # Refresh to remove the chat input immediately
                st.rerun()

# ------------------------------------------------------------------
# 20. INTERVIEW COMPLETION STATUS
#   Shows a disabled input box with a "completed" message once the
#   interview is over (replaces the chat input).
# ------------------------------------------------------------------
if st.session_state.chat_complete:
      st.text_input(
        "Interview completed",
        value="Thank you for the attempt , You have completed all 5 answers. Click on 'Feeback' button to proceed",
        disabled=True,
        key="completed_interview_input",
    )

# ================================================================
# 21. GET FEEDBACK BUTTON
#   Appears after the candidate has submitted all 5 answers and
#   feedback has not been shown yet.
#   NOTE: If the interview was ended early with "End Conversation"
#   (fewer than 5 answers), this button does not appear.
# ================================================================
if (
    st.session_state.chat_complete
    and st.session_state.user_message_count >= 5
    and not st.session_state.feedback_shown
):
    if st.button( "Get Feedback", type="primary"):
        show_feedback()
        st.rerun()

# ====================================================================
# 22. SAVE THE INTERVIEW RESULT TO MYSQL
#   Called once after feedback is generated (Section 23).
#   Steps (all in ONE transaction):
#     22.1 Extract the overall score from the feedback text
#     22.2 Update the candidate's phone number
#     22.3 Verify the interview belongs to this candidate
#     22.4 Store score + feedback on the interview row
#     22.5 Pair each AI question with the candidate's answer
#     22.6 Insert all question/answer pairs
#     22.7 Commit
# ====================================================================
import mysql.connector        # (duplicate import - harmless)
import re                     # (duplicate import - harmless)
from decimal import Decimal   # (duplicate import - harmless)

def save_interview_to_mysql(
    candidate_data,
    messages,
    feedback_text
):
    connection = None
    cursor = None

    try:
        # ------------------------------------------------------------
        # 22.1 Extract the overall score, e.g. "Overall Score: 7.5/10"
        #      (also matches "**Overall Score:** 7.5/10")
        # ------------------------------------------------------------
        
        # Allow up to 40 formatting characters (e.g. "** **:red[")
        # between "Overall Score:" and the number, but no digits
        # and no line breaks, so it can't skip to another number.
        score_match = re.search(
            r"Overall\s+Score\s*:?[^0-9\n]{0,40}?"
            r"(10(?:\.0+)?|[0-9](?:\.\d+)?)\s*/\s*10",
            feedback_text,
            re.IGNORECASE
        )
        if not score_match:
            print("Feedback received:", repr(feedback_text[:500]))
            raise ValueError(
                "Could not extract the overall score."
                "Expected format: Overall Score: 0.0/10"
            )
        score = Decimal(score_match.group(1))
        if not Decimal("0") <= score <= Decimal("10"):
            raise ValueError("Score must be between 0 and 10.")

        # ------------------------------------------------------------
        # Get a database connection from the pool
        # ------------------------------------------------------------
        with measure_time("MySQL connection"):

        # Reuse a pooled connection instead of opening a new one
            connection = get_db_connection()

        cursor = connection.cursor()

        # ------------------------------------------------------------
        # 22.2 Candidate details (phone number update)
        # ------------------------------------------------------------
        name = candidate_data.get("name")
        email = candidate_data.get("email")

        # Get phone number from all supported candidate-data sources
        candidate_data = candidate_data or {}

        phone = (
            candidate_data.get("phone_number")
            or candidate_data.get("phone")
            or st.session_state.get("phone_number")
            or st.session_state.get("phone")
        )
        company = candidate_data.get("company")

        # Debug BEFORE executing SQL (terminal only)
        print("Candidate data:", repr(candidate_data))
        print("Phone value:", repr(phone))
        print("Phone type:", type(phone).__name__)
        print("Phone length:", len(str(phone)) if phone is not None else 0)

        # Phone is required -> stop with a clear error if missing
        if not phone:
            print("Candidate data received:", repr(candidate_data))
            print("Session phone_number:", repr(
               st.session_state.get("phone_number")
            ))
            print("Session phone:", repr(st.session_state.get("phone")))
            raise ValueError(
                  "Phone number is missing. Check candidate_data and session state."
            )

        # Reuse the existing candidate ID
        candidate_id = st.session_state.get("candidate_id")

        if candidate_id is None:
              raise ValueError("Candidate ID is missing from session state.")

        # Update the existing candidate instead of inserting a duplicate
        with measure_time("MySQL candidate insert/update"):
         cursor.execute(
            """
            UPDATE candidates
            SET phone = %s
            WHERE candidate_id = %s
            """,
          (phone, candidate_id)
        )

        # Keep the existing candidate_id; do not reassign it.
        print(f"Updated phone for candidate ID: {candidate_id}")

        # ------------------------------------------------------------
        # 22.3 Verify the interview row belongs to this candidate
        # ------------------------------------------------------------
        interview_id = st.session_state.get("interview_id")
        candidate_id = st.session_state.get("candidate_id")

        if interview_id is None:
            raise ValueError("Interview ID is missing.")

        if candidate_id is None:
            raise ValueError("Candidate ID is missing.")

        with measure_time("MySQL interview update"):
        # Verify that the interview belongs to this candidate.
            cursor.execute(
                            """
                                SELECT interview_id
                                FROM interviews
                                WHERE interview_id = %s
                                AND candidate_id = %s
                            """,
                            (interview_id, candidate_id),
                )

            interview_row = cursor.fetchone()

            if interview_row is None:
                raise ValueError(
                    f"No interview found for interview_id={interview_id}, "
                    f"candidate_id={candidate_id}. "
                    "Check the IDs in the interviews table."
            )

            # ------------------------------------------------------------
            # 22.4 Store the score + feedback on the interview row
            #      ended_at is set only if it was not already set.
            # ------------------------------------------------------------
            cursor.execute(
                            """
                                UPDATE interviews
                                SET overall_score = %s,
                                    overall_feedback = %s,
                                    status = 'completed',
                                    ended_at = COALESCE(
                                        ended_at,
                                        CURRENT_TIMESTAMP(6)
                                    )
                                WHERE interview_id = %s
                                AND candidate_id = %s
                            """,
                (
                    score,
                    feedback_text,
                    interview_id,
                    candidate_id,
                ),
            )

        # ------------------------------------------------------------
        # 22.5 Pair each AI question with the user's answer
        #   Walks through the history: an assistant message becomes
        #   the "pending" question; the next user message is its answer.
        #   Each row: (interview_id, question_number, question, answer)
        # ------------------------------------------------------------
        responses = []
        pending_question = None
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            # Skip the internal system prompt
            if role == "system":
                continue
            if role == "assistant":
                # Ignore the fixed completion message
                if "click on" in content.lower() and \
                   "get feedback" in content.lower():
                    continue
                pending_question = content
            elif role == "user" and pending_question:
                responses.append((
                    interview_id,
                    len(responses) + 1,
                    pending_question,
                    content
                ))
                pending_question = None

        # Nothing to save -> treat as an error
        if not responses:
            raise ValueError(
                "No question-and-answer pairs were found "
                "in the interview messages."
            )

        print(
            f"DEBUG: Saving {len(responses)} responses "
            f"for interview_id={interview_id}"
        )

        # ------------------------------------------------------------
        # 22.6 Insert all question/answer pairs in one call
        # ------------------------------------------------------------
        # if responses:   (old guard - no longer needed)
        cursor.executemany(
                """
                        INSERT INTO interview_responses (
                            interview_id,
                            question_number,
                            ai_question,
                            user_answer
                        )
                        VALUES (%s, %s, %s, %s)
                """,
                responses,
            )

        # ------------------------------------------------------------
        # 22.7 Commit the interview update and responses together
        # ------------------------------------------------------------
        with measure_time("MySQL transaction commit"):
             connection.commit()

        return {
            "success": True,
            "candidate_id": candidate_id,
            "interview_id": interview_id,
            "responses_saved": len(responses)
        }
    except Exception:
        # Undo everything from this transaction, then re-raise
        if connection and connection.is_connected():
            connection.rollback()
        raise
    finally:
        # Always release the cursor and return the connection to the pool
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

# ============================================================
# 22.0 SCORE COLORING (DETERMINISTIC)
#   The LLM writes plain scores ("0.0/10", "3/5").
#   Python then makes ONLY the number bold + colored using
#   fixed thresholds, so colors are always correct and no
#   extra text like "Red (Poor)" is shown.
#   Thresholds (same ratio for /5 and /10):
#     below 60%      -> red     (below 3.0/5, below 6.0/10)
#     60% to < 90%   -> orange  (3.0-4.4/5,  6.0-8.9/10)
#     90% and above  -> green   (4.5+/5,     9.0+/10)
# ============================================================

# --------------------------------------------------------
# 22.0.1 Pick the color for a score
# --------------------------------------------------------
def score_color(score, out_of):
    ratio = score / out_of
    if ratio < 0.6:
        return "red"
    if ratio < 0.9:
        return "orange"
    return "green"


# --------------------------------------------------------
# 22.0.2 Find score lines and rebuild them
#   Matches "**Overall Score:** ..." and "**Score:** ..." lines,
#   finds the X/10 or X/5 value, and replaces the WHOLE rest of
#   the line with just the bold colored score. This also removes
#   duplicates like "Score: Score:" and labels like "Red (Poor)".
#   "**Score Legend:**" is NOT matched, so the legend stays.
# --------------------------------------------------------
SCORE_LINE_PATTERN = re.compile(
    r"(\*\*(?:Overall\s+Score|Score):\*\*)"     # the bold label
    r"[^\n]*?"                                  # anything before the number
    r"(\d+(?:\.\d+)?)\s*/\s*(10|5)\b"           # the score, e.g. 3.5/5
    r"[^\n]*",                                  # rest of the line (dropped)
    re.IGNORECASE,
)

# --------------------------------------------------------
# 22.0.3 Add a divider line before every question
#   1. Remove any "---" lines the model already wrote
#      (prevents double dividers).
#   2. Insert a divider before each "**Question N:**".
#   The blank lines around "---" are REQUIRED: in Markdown,
#   "---" directly under a line of text turns that text
#   into a heading instead of drawing a line.
# --------------------------------------------------------
def add_question_dividers(feedback_text):
    # Step 1: drop existing divider lines
    feedback_text = re.sub(
        r"^[ \t]*-{3,}[ \t]*$\n?", "", feedback_text, flags=re.MULTILINE
    )

    # Step 2: put a divider (with blank lines around it) before each question
    return re.sub(
        r"\s*\n(?=[ \t]*\*\*Question\s+\d+:\*\*)",
        "\n\n---\n\n",
        feedback_text,
        flags=re.IGNORECASE,
    )

def colorize_scores(feedback_text):
    def replace(match):
        label, score, out_of = match.groups()
        color = score_color(float(score), float(out_of))
        # e.g. **Score:** **:green[4.5/5]**
        return f"{label} **:{color}[{score}/{out_of}]**"

    # Color the scores, then add dividers between questions
    return add_question_dividers(
        SCORE_LINE_PATTERN.sub(replace, feedback_text)
    )

# ============================================================
# 22.1 FEEDBACK PROMPT BUILDER
#   Builds the system prompt for the evaluator LLM.
#   The candidate's experience is inserted so the expected depth
#   of answers matches their seniority.
#   The output format ("Overall Score: X/10") must stay as is,
#   because Section 22.1 extracts the score with a regex.
# ============================================================

def build_feedback_system_prompt(total_experience):

    return f"""
    You are a professional technical interview evaluator. Evaluate the candidate strictly based on the actual interview conversation and the candidate's stated experience.

    **CANDIDATE EXPERIENCE**

     The candidate's experience is: {total_experience}

     Adjust expectations for technical depth, problem-solving, communication, and practical knowledge according to this experience.

    **OUTPUT REQUIREMENTS**

    **1. OVERALL SCORE**

        Start with:

        **Overall Score:** X/10 
        Write only the number in this exact format (for example: **Overall Score:** 6.5/10). Do not add colors, color names, or labels such as "Poor" or "Good".

        Evaluate each question individually on a scale of 0 to 5. Calculate the overall score using the average of all question scores, converted to a scale of 10:

        Overall Score = (Sum of all question scores / (Number of questions × 5)) × 10

        Round the final score to one decimal place. Do not independently invent an overall score that conflicts with the individual scores. If all five answers receive 0/5, the overall score must be 0/10.

    **2. OVERALL FEEDBACK**

        Write:

        **Feedback:**

        Provide specific strengths, weaknesses, and actionable improvements. Avoid generic advice. Base conclusions only on the conversation.

    **3. SCORE LEGEND**

        Display this exact legend:

        **Score Legend:** :red[Red — Poor] | :orange[Yellow — Average] | :green[Green — Good]

    **4. QUESTION-BY-QUESTION EVALUATION**

        Evaluate every actual AI interview question in the conversation. If five questions were asked, evaluate all five. Never invent missing questions or answers.

        For each question, follow this exact structure:

        **Question 1:** [Original AI question]

        **Candidate Answer:** [Brief, accurate summary of the actual answer. If the candidate skipped the question, explicitly state that no technical answer was provided.]

        **Score:** X/5 and the appropriate color label
        Write only the number in this exact format (for example: **Score:** 3.5/5). Do not repeat the word "Score", and do not add colors, color names, or labels.

        **Evaluation:** [Specific strengths and shortcomings supported by the candidate's answer.]

        **Expected Answer:** [What a candidate with the stated experience would reasonably be expected to explain.]

        **Improvement:** [Concrete recommendation for improving the answer.]

        Repeat this structure for every actual question, preserving the original question order.

    **5. FORMATTING REQUIREMENTS**

        - Use Markdown bold formatting for all section labels and field labels, including Overall Score, Feedback, Score Legend, Question 1, Candidate Answer, Score, Evaluation, Expected Answer, and Improvement.
        - Do not use HTML tags.
        - Keep each question's evaluation clearly separated with blank lines.
        - Make the output readable, consistent, and suitable for display in a Streamlit application.

    **6. EVALUATION RULES**

        - Be fair, evidence-based, and consistent.
        - Do not award points for claims unsupported by the answer.
        - Consider the candidate's stated experience.
        - If an answer is missing, explicitly state that it was not provided and score accordingly.
        - Do not fabricate technical details, questions, or candidate responses.
        - Keep feedback concise but useful.
        - Return feedback only. Do not ask follow-up questions.

    """

# ============================================================
# 23. FEEDBACK SECTION
#   Appears after the user clicks "Get Feedback".
#   23.1 Generate the feedback ONCE (streamed) and cache it
#   23.2 Save the interview result to MySQL ONCE
#   23.3 "Restart Interview" button
# ============================================================
if st.session_state.feedback_shown:
    st.subheader("Feedback")

    # -----------------------------------------------------------------------
    # 23.1 GENERATE FEEDBACK ONLY ONCE
    #   PERFORMANCE: without this, every rerun (any button click)
    #   called OpenAI again (slow, costly, and changed the score).
    # -----------------------------------------------------------------------

    if st.session_state.feedback_text is None:
        # Experience used to calibrate the evaluator's expectations
        total_experience = st.session_state.candidate_data.get(
               "total_experience", "unspecified"
        )

        # Whole conversation as plain text ("role : content" per line)
        conversation_history = "\n".join(
            f"{msg['role']} : {msg['content']}"
            for msg in st.session_state.messages
            if msg["role"] != "system"   # no need to send the system prompt
        )

        with st.spinner("Evaluating your interview performance..."):
            with measure_time("OpenAI feedback generation"):

                # PERFORMANCE: stream so the user sees feedback
                # appear immediately instead of waiting for all of it
                stream = client.chat.completions.create(
                    model = st.session_state["openai_model"],
                    messages = [
                        {
                            "role" : "system",
                            "content" : build_feedback_system_prompt(total_experience),
                        },
                        {
                                "role" : "user",
                                "content":(
                                    "This is the interview you need to evaluate. "
                                    "You are only a tool for evaluation and should "
                                    f"not engage in conversaion : {conversation_history}"
                                ),
                        },
                    ],
                    reasoning_effort="low",
                    max_completion_tokens=3000,
                    stream=True,
                )

                # Stream into a placeholder so the user sees text arriving,
                # then swap it for the colorized version once complete.
                feedback_placeholder = st.empty()
                with feedback_placeholder.container():

                    # write_stream renders as it arrives and returns the full text
                    st.session_state.feedback_text = st.write_stream(stream)

                feedback_placeholder.markdown(
                    colorize_scores(st.session_state.feedback_text)
                )
    else:
        # Already generated: just display the stored feedback
        st.markdown(colorize_scores(st.session_state.feedback_text))

    # Feedback is already displayed above (st.write_stream on the first
    # run, st.markdown afterwards), so it is not written again here.
    feedback_text = st.session_state.feedback_text

    # -----------------------------------------------------------------------
    # 23.2 SAVE THE INTERVIEW TO MYSQL (only once per session)
    # -----------------------------------------------------------------------
    if "interview_saved" not in st.session_state:
     st.session_state.interview_saved = False

    if not st.session_state.interview_saved:
        try:
            # Use the confirmed profile from session state
            candidate_data = st.session_state.candidate_data

            # ---------------------------------------------------------------
            # Normalise the phone format before saving
            #   "+91-XXXXXXXXXX" -> unchanged
            #   "+91XXXXXXXXXX"  -> "+91-XXXXXXXXXX"
            # ---------------------------------------------------------------
            phone = (
                     candidate_data.get("phone_number")
                     or candidate_data.get("phone")
                    )

            if phone:
                phone = str(phone).strip()
                   # Keep an existing hyphen if it is already present
                if phone.startswith("+") and "-" in phone:
                   full_phone = phone
                elif phone.startswith("+91") and len(phone) == 13:
                   full_phone = f"+91-{phone[3:]}"
                else:
                   full_phone = phone

                candidate_data["phone"] = full_phone
                candidate_data["phone_number"] = full_phone

            # Debug output in the terminal
            print(
                "Candidate data being saved:",
                repr(st.session_state.candidate_data)
            )

            # Save score, feedback and all Q&A pairs (Section 22)
            result = save_interview_to_mysql(
                candidate_data=st.session_state.candidate_data,
                messages=st.session_state.messages,
                feedback_text=feedback_text
            )

            # Mark as saved only after the database function succeeds
            st.session_state.interview_saved = True

            # Use the candidate ID returned by the save function for logging
            print(f"Candidate ID: {result['candidate_id']}")

            # Log the interview save result
            print(
              "Interview saved successfully | "
              f"Candidate ID: {result['candidate_id']} | "
              f"Interview ID: {result['interview_id']} | "
              f"Responses saved: {result['responses_saved']}"
            )

        except Exception as e:
           st.error("Failed to save interview results.")
           st.exception(e)   # shows the full error on the page (debugging)

    # -----------------------------------------------------------------------------------------
    # 23.3 RESTART INTERVIEW BUTTON
    #   Reloads the browser page, which starts a fresh session.
    #   Requires: pip install streamlit-js-eval
    #   (streamlit_js_eval runs JavaScript in the browser from Python)
    # -----------------------------------------------------------------------------------------
    if st.button("Restart Interview" , type="primary") :
       streamlit_js_eval(js_expressions = "parent.window.location.reload()")

# ============================================================
# 24. SCRIPT EXECUTION TIME
#   Prints how long this complete rerun took (terminal only).
#   Timer was started in Section 4.2.
# ============================================================

script_elapsed_time = time.perf_counter() - script_start_time

print(
    f"[PERFORMANCE] Script run "
    f"{st.session_state['_run_count']} completed in "
    f"{script_elapsed_time:.3f} seconds"
)
