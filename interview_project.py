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
    page_title="Streamlit Chat",
    page_icon="💬"
)

st.title("Interview phase")

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

# ========================================================
# 5. CREATE OPENAI CLIENT
  # The API key is retrieved from Streamlit secrets.
# ========================================================
try:
    api_key = st.secrets["OPENAI_API_KEY"]

    if not api_key or not api_key.strip():
        raise ValueError("OpenAI API key is empty.")
    client = OpenAI(api_key=api_key)
    print("OpenAI client initialized successfully.")
except Exception as e:
    client = None
    print(f"OpenAI client initialization failed: {type(e).__name__}")
    st.error(
        "OpenAI configuration is missing or invalid. "
        "Please check your application secrets."
    )

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
                    "projects"
                ],
    
                "additionalProperties": False
            }

# ============================================================
# 13. Parse Resume with LLM
# ============================================================
def parse_resume_with_llm(resume_text, client):
    with st.status("Analyzing your resume"):
        response = client.responses.create(
        model="gpt-5.6-luna",
        instructions="""
        You are an expert resume parser.
        Extract candidate information from the resume.
        Important rules:
        1. Do not invent information.
        2. Only use information present in the resume.
        3. If information is missing, return null for scalar fields.
        4. Return an empty array when a list cannot be found.
        5. Calculate total experience from the resume when possible.
        6. Preserve the actual company and role names.
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
    return response.output_text

# ==================================================================
# 14. Define PII Services
  # This section imports the necessary packages to run PII Service
# ==================================================================
from presidio_analyzer import (
    AnalyzerEngine,
    Pattern,
    PatternRecognizer
    )
from presidio_anonymizer import AnonymizerEngine

@st.cache_resource
def get_pii_engines():
 analyzer = AnalyzerEngine()
 anonymizer = AnonymizerEngine()

 company_recognizer = PatternRecognizer(
    supported_entity="COMPANY",
    patterns=[
        Pattern(
            name="tcs",
            regex=r"\bTCS\b",
            score=0.95
        ),
        Pattern(
            name="infosys",
            regex=r"\bInfosys\b",
            score=0.95
        ),
        Pattern(
            name="accenture",
            regex=r"\bAccenture\b",
            score=0.95
        ),
        Pattern(
            name="capgemini",
            regex=r"\bCapgemini Technology Services\b",
            score=0.95
        )
    ],
    supported_language="en"
  )
 
 analyzer.registry.add_recognizer(company_recognizer)
 return analyzer, anonymizer

# Initialize PII services with a spinner
with st.spinner("Initializing application... Please wait"):
 with measure_time("PII engine initialization"):
   analyzer, anonymizer = get_pii_engines()

# ============================================================
# 15. Mask the sensitive Information using PII
  # This analyzer detects and Mask the important information
# ============================================================
def mask_resume_pii(resume_text):
    # Detect PII entities
    results = analyzer.analyze(
        text=resume_text,
        language="en",
        entities=[
            "EMAIL_ADDRESS",
            "PHONE_NUMBER",
            "PERSON",
            "COMPANY"
        ]
    )

    # Capture detected entity values before masking
    detected_entities = {}

    for result in results:
        entity_value = resume_text[result.start:result.end]
        entity_type = result.entity_type

        detected_entities.setdefault(entity_type, [])
        if entity_value not in detected_entities[entity_type]:
            detected_entities[entity_type].append(entity_value)

    # Mask detected PII
    masked_text = anonymizer.anonymize(
        text=resume_text,
        analyzer_results=results
    ).text

    return masked_text, detected_entities

# ============================================================
# 16 SAVE CANDIDATE PROFILE AFTER RESUME PROCESSING
# ============================================================

def save_candidate_profile(
    candidate_data,
    setup_mode,
    extracted_resume_text=None
):
    connection = None
    cursor = None

    try:
        connection = mysql.connector.connect(
            host=st.secrets["mysql"]["host"],
            port=st.secrets["mysql"]["port"],
            user=st.secrets["mysql"]["user"],
            password=st.secrets["mysql"]["password"],
            database=st.secrets["mysql"]["database"]
        )

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
                name,
                email,
                phone,
                company,
                setup_mode,
                extracted_resume_text,
                structured_data
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
                name,
                email,
                phone,
                company,
                setup_mode,
                extracted_resume_text,
                structured_json
            )
        )

        candidate_id = cursor.lastrowid
        connection.commit()

        print(
            "Candidate profile saved successfully | "
            f"Candidate ID: {candidate_id} | "
            f"Setup mode: {setup_mode}"
        )

        return candidate_id

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

              # Detect amd mask PII
              with st.spinner("Detecting and masking sensitive information..."):
                    with measure_time("PII detection and masking"):
                        masked_resume_text, detected_entities = mask_resume_pii(resume_text)
         
              # Send masked text to the LLM
              with measure_time("OpenAI resume parsing"):
                resume_json = parse_resume_with_llm(
                 resume_text, # Use this when you want to pass the same exact orignial resume data without masking
                 # masked_resume_text,
                 client
              ) 
              # Convert the response into a Python dictionary
              with measure_time("Resume JSON parsing"):
                  candidate_data = json.loads(resume_json)

              # Restore detected personal details into the structured data
              with measure_time("Resume JSON parsing"):
                candidate_data["name"] = (
                detected_entities.get("PERSON", [None])[0]
              )
              candidate_data["email"] = (
                detected_entities.get("EMAIL_ADDRESS", [None])[0]
              )
              candidate_data["phone_number"] = (
                detected_entities.get("PHONE_NUMBER", [None])[0]
              )

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
                       full_phone = f"+91-{phone_number}"

                   candidate_data["phone_number"] = full_phone
                   candidate_data["phone"] = full_phone

              # Store structured data in session state
              st.session_state.candidate_data = candidate_data

              # Save resume and structured data to MySQL
              with st.spinner("Saving candidate profile..."):
               with measure_time("MySQL candidate profile save - Resume"):
                  candidate_id = save_candidate_profile(
                  candidate_data=candidate_data,
                  setup_mode="Upload Resume",
                  extracted_resume_text=resume_text
              )

              # Preserve the ID for the interview-saving function
              st.session_state.candidate_id = candidate_id

              # Mark processing complete only after successful saving
              st.session_state.processed_resume_hash = file_hash
              st.session_state.candidate_profile_saved = True

              # Log only metadata, not the resume or personal details
              print(
                 "Resume processing completed successfully | "
                 f"Candidate ID: {candidate_id} | "
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

        # Keep your existing Start Interview button below this block.
        if st.session_state.get("candidate_profile_saved", False):
            if st.button(
                "Start Interview",
                on_click=complete_setup,
                key="start_resume_interview"
            ):
              pass

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
                candidate_id = save_candidate_profile(
                candidate_data=st.session_state.candidate_data,
                setup_mode="Manual selection",
                extracted_resume_text=None
             )

             # Preserve the ID for the interview-saving function
             st.session_state.candidate_id = candidate_id

             st.session_state.candidate_profile_saved = True
            #  st.session_state.candidate_id = candidate_id

             print(
                "Manual candidate profile saved successfully | "
                f"Candidate ID: {candidate_id}"
             )

             # Mark setup complete only after successful saving
             st.session_state.setup_complete = True
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
        if st.session_state.setup_mode == "Upload Resume":
           candidate_data = st.session_state.candidate_data
        else:
        # Create the SAME candidate_data structure from the manually entered information.
         candidate_data = {
            "name": st.session_state["name"],
            "email": st.session_state["email"],
            "phone": (
                st.session_state["phone_country_code"]
                + st.session_state["phone_number"]
            ),
            "total_experience": st.session_state["experience"],
            "current_role": st.session_state["position"],
            "skills": st.session_state["skills"],
            "level": st.session_state["level"],
            "position": st.session_state["position"],
            "company": st.session_state["company"]
        }
         
        # Store it in session state so it persists during the interview.
         st.session_state.candidate_data = candidate_data

        # Convert candidate data to JSON
        candidate_context = json.dumps(
        st.session_state.candidate_data,
        indent=2
        )
        st.session_state.messages = [
            {
              
                "role": "system",
                "content": f"""
                You are an expert HR interviewer.

                Candidate information:

                {candidate_context}

                Ask exactly ONE question at a time.
                Base questions on the candidate's actual information.
                Do not invent candidate experience or skills.
                Ask follow-up questions based on their answers.
                """
            }
        ]

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
    if not st.session_state.chat_complete:
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
                  # This causes the interview section above to stop 
                  # running on the next Streamlit rerun.
                # ------------------------------------------------------------------
                st.session_state.chat_complete = True

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
          connection = mysql.connector.connect(
            host=st.secrets["mysql"]["host"],
            port=st.secrets["mysql"]["port"],
            user=st.secrets["mysql"]["user"],
            password=st.secrets["mysql"]["password"],
            database=st.secrets["mysql"]["database"]
        )
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
        with measure_time("MySQL interview insert"):
         cursor.execute(
            """
            INSERT INTO interviews (
                candidate_id,
                overall_score,
                overall_feedback,
                status
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                candidate_id,
                score,
                feedback_text,
                "completed"
            )
        )
        interview_id = cursor.lastrowid

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
        if responses:
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
                responses
            )
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
# 23. FEEDBACK SECTION
   # This section appears after the user clicks "Get Feedback".
# ============================================================
if st.session_state.feedback_shown:
    st.subheader("Feedback")

    # -----------------------------------------------------------------------
    # 23.1 Combine all conversation messages into one text block
        # This can later be sent to OpenAI to generate interview feedback.
    # -----------------------------------------------------------------------
    total_experience = (
    st.session_state.candidate_data.get("total_experience", "unspecified")
    )
    conversation_history = "\n".join(
        [
            f"{msg['role']} : {msg['content']}"
            for msg in st.session_state.messages
        ]
    )    
    feedback_client = OpenAI(api_key = st.secrets["OPENAI_API_KEY"])
    with st.spinner("Evaluating your interview performance..."):
      with measure_time("OpenAI feedback generation"):
         feedback_completion = feedback_client.chat.completions.create(
                model = st.session_state["openai_model"],
                 messages = [
                      {
                           "role" : "system",
                           "content" : f"""
                                         You are a professional technical interview evaluator. Evaluate the candidate strictly based on the actual interview conversation and the candidate's stated experience.

                                        **CANDIDATE EXPERIENCE**

                                        The candidate's experience is: {total_experience}

                                        Adjust expectations for technical depth, problem-solving, communication, and practical knowledge according to this experience.

                                        **OUTPUT REQUIREMENTS**

                                        **1. OVERALL SCORE**

                                        Start with:

                                        **Overall Score:** X/10

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
                        },
                        {   
                             "role" : "user",
                            "content": f"""This is the interview you need to evaluate,
                                           You are only a tool for evaluation and should
                                            not engage in conversaion : {conversation_history} """
                      }
                 ],
                 reasoning_effort="low",
                 max_completion_tokens=3000
          )
 
    feedback_text = feedback_completion.choices[0].message.content
    st.write(feedback_text)

    # Save the interview only once per session
    if "interview_saved" not in st.session_state:
     st.session_state.interview_saved = False

    if not st.session_state.interview_saved:
        try:
            # Refresh candidate data without overwriting existing values with blanks
            candidate_data = st.session_state.candidate_data

            candidate_data.update({
                "name": st.session_state.get("name")
                    or candidate_data.get("name", ""),
                "email":st.session_state.get("email")
                    or candidate_data.get("email", ""),
                "company": st.session_state.get("company")
                    or candidate_data.get("company", ""),
            })

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