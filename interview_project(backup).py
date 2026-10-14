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

# ============================================================
# 2. TEMPORARY DIAGNOSTIC: CHECK SCRIPT RERUNS
# ============================================================
if "_run_count" not in st.session_state:
    st.session_state["_run_count"] = 0

st.session_state["_run_count"] += 1

st.caption(
    f"Script runs: {st.session_state['_run_count']}"
)

# ========================================================
# 3. CREATE OPENAI CLIENT
  # The API key is retrieved from Streamlit secrets.
# ========================================================
client = OpenAI(
    api_key=st.secrets["OPENAI_API_KEY"]
    )

# ============================================================
# 4. STREAMLIT PAGE CONFIGURATION
 # Sets the browser tab title and icon.
 # Also displays the main title of the application.
# ============================================================
st.set_page_config(
    page_title="Streamlit Chat",
    page_icon="💬"
)

st.title("Interview phase")

# ============================================================================
# 5. INITIALIZE SESSION STATE VARIABLES
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
# 6. FUNCTION TO Choose THE SETUP 
  # This function is called when the user clicks "Next".
# ============================================================
def setup_choose():
    # Save the selected setup mode before leaving the selectbox page
    st.session_state.setup_mode = st.session_state.setup_mode_widget

    # Move to the next setup stage
    st.session_state.choose_setup = True

# =================================================================
# 7. FUNCTION TO MARK THE SETUP AS COMPLETE
 # This function is called when the user clicks "Start Interview".
# =================================================================
def complete_setup():
    st.session_state.setup_complete = True

# ============================================================
# 8. FUNCTION TO SHOW FEEDBACK
  # This function changes feedback_shown to True when the 
  # "Get Feedback" button is clicked.
# ============================================================
def show_feedback():
    st.session_state.feedback_shown = True

# ===============================================================
# 9. Setup selection Form
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
# 10. EXTRACT TEXT FROM RESUME
# This function supports:
#     PDF
#     DOCX
#     TXT
# The function checks the uploaded file's extension
# and uses the appropriate method to extract the text.
# ============================================================
def extract_resume_text(uploaded_file):
    # Get the uploaded file name.
    # Example:
    #     john_resume.pdf
    #     john_resume.docx
    #     john_resume.txt
    file_name = uploaded_file.name.lower()

    # --------------------------------------------------------
    # 10.1 PDF
    # --------------------------------------------------------
    if file_name.endswith(".pdf"):

        reader = PdfReader(uploaded_file)

        text = ""

        for page in reader.pages:

            text += page.extract_text() or ""

        return text
    # --------------------------------------------------------
    # 10.2 DOCX
    # --------------------------------------------------------
    elif file_name.endswith(".docx"):

        document = Document(uploaded_file)

        text = ""

        for paragraph in document.paragraphs:

            text += paragraph.text + "\n"

        return text
    # --------------------------------------------------------
    # 10.3 TXT
    # --------------------------------------------------------
    elif file_name.endswith(".txt"):

        text = uploaded_file.read().decode("utf-8")

        return text
    # --------------------------------------------------------
    # 10.4 UNSUPPORTED FILE
    # --------------------------------------------------------
    else:
        raise ValueError(
            "Unsupported file type. "
            "Please upload a PDF, DOCX, or TXT file."
        )

# ============================================================
# 11. Define schema for structured resume data
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
# 12. Parse Resume with LLM
# ============================================================
def parse_resume_with_llm(resume_text, client):
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
# 13. Define PII Services
  # This section imports the necessary packages to run PII Service
# ==================================================================
import re
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
analyzer, anonymizer = get_pii_engines()

# ============================================================
# 14. Mask the sensitive Information using PII
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
# 15. Choice 1 - Resume Upload and display extracted resume data
  # This form gives the option to upload the resume
# ============================================================
if (st.session_state.choose_setup and 
st.session_state.setup_mode == "Upload Resume" 
and not st.session_state.setup_complete) : 
    st.header("Upload Resume", divider="rainbow") 
    uploaded_resume = st.file_uploader( "Upload your resume", 
                type=["pdf", "docx", "txt"] 
            )  
    if uploaded_resume: 
        st.success("Resume uploaded successfully!")

        # Extract text from the uploaded PDF
        resume_text = extract_resume_text(uploaded_resume)

        # Display the extracted text
        st.write("### Extracted Orignial Resume Text before masking")   
        st.write(resume_text)

        # Mask sensitive information before sending to OpenAI
        masked_resume_text, detected_entities = mask_resume_pii(resume_text)
        # Send masked text to the LLM
        resume_json = parse_resume_with_llm(
                resume_text, # Use this when you want to pass the same exact orignial resume data without masking
                # masked_resume_text,
                client
        )
        candidate_data = json.loads(resume_json)

        # Restore detected personal details into the structured data
        candidate_data["name"] = (
                detected_entities.get("PERSON", [None])[0]
        )
        candidate_data["email"] = (
                detected_entities.get("EMAIL_ADDRESS", [None])[0]
        )
        candidate_data["phone_number"] = (
                detected_entities.get("PHONE_NUMBER", [None])[0]
        )

        st.session_state.candidate_data = candidate_data
 
        # Convert JSON string to Python Dictionary
        candidate_data = json.loads(resume_json)

        # Store candidate information in session state
        st.session_state.candidate_data = candidate_data

        # Mark resume processing as complete
        complete_resume_processing()

        # Display structured Candidate Data
        st.write("### Structured Candidate Data")
        st.json(st.session_state.candidate_data)
        if st.button(
                "Start Interview",
                on_click=complete_setup
            ):
                st.write("Setup complete... Starting Interview...")
       
# ==================================================================
# 16. Choice 2 - Manaul Selection "PERSONAL INFORMATION FORM"
  # This section is displayed only BEFORE the interview starts and 
  # if user chooses the setup as "Manual selection".
  # The user enters:
  # - Name
  # - Experience
  # - Skills
# ==================================================================
import time
import streamlit as st
start_time = time.perf_counter()
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
       # 16.1 Name input
       # --------------------------------------------------------
        st.text_input(
            "Name",
            max_chars=40,
            placeholder="Enter your name",
            key="name"
        )

        # --------------------------------------------------------
        # 16.2 Email input
        # --------------------------------------------------------
        st.text_input(
            "Email",
            max_chars=40,
            placeholder="Enter your email",
            key="email"
        )

        # --------------------------------------------------------
        # 16.3 Phone number input
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
        # 16.4 Experience input
        # --------------------------------------------------------
        st.text_area(
            "Experience",
            max_chars=300,
            placeholder="Describe your experience",
            key="experience"
        )

        # --------------------------------------------------------
        # 16.5 Skills input
        # --------------------------------------------------------
        st.text_area(
            "Skills",
            max_chars=100,
            placeholder="List your skills",
            key="skills"
        )

        # --------------------------------------------------------
        # 16.6 COMPANY AND POSITION INFORMATION
        # --------------------------------------------------------
        st.subheader("Company and Position", divider="rainbow")

        # --------------------------------------------------------
        # 16.7 Create two columns for Level and Position
        # --------------------------------------------------------
        col1, col2 = st.columns(2)

        # --------------------------------------------------------
        # 16.8 Interview level selection
        # --------------------------------------------------------
        with col1:
            st.radio(
                "Choose level",
                key="level",
                options=["Junior", "Mid-level", "Senior"],
            )

        # --------------------------------------------------------
        # 16.9 Position selection
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
        # 16.10 Company selection
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
        # 16.11 FORM SUBMIT AND START INTERVIEW 
           # Clicking this button changes setup_complete to True.
           # This causes Streamlit to rerun and enter the interview section below.
        # -------------------------------------------------------------------------
        submitted = st.form_submit_button(
            "Start Interview",
            type="primary",
        )

    # ------------------------------------------------------------------
    # 16.12 FORM VALIDATION CHECKS
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
          st.session_state.candidate_data = {
            "name": st.session_state["name"].strip(),
            "email": email,
            "phone": (
                st.session_state["phone_country_code"] + phone
            ),
            "total_experience": st.session_state["experience"],
            "current_role": st.session_state["position"],
            "skills": st.session_state["skills"],
            "level": st.session_state["level"],
            "position": st.session_state["position"],
            "company": st.session_state["company"],
          }

          # --------------------------------------------------------------
          # 16.13 PRINT THE INFORMATION ENTERED BY THE USER TO THE CONSOLE
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
          st.session_state.setup_complete = True
          st.rerun()

# ============================================================
# 17. INTERVIEW / CHATBOT SECTION
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
    # 17.1 Display initial interview greeting
    # --------------------------------------------------------
    candidate_name = (
    st.session_state.candidate_data.get("name")
    )
    st.info(
        """
        f"Hi {candidate_name},Thank you for appling for this role,
        very excited to take interview for you..
        """,
        icon="👏"
    )

    # --------------------------------------------------------
    # 17.2 Check whether the OpenAI client exists
    # --------------------------------------------------------
    if not client:
        print(
            "No API key was found - please head over "
            "to the troubleshooting notebook in this folder "
            "to identify & fix!"
        )
    else:
        print("API key found and looks good so far!")

    # ------------------------------------------------------------------
    # 17.3 SELECT THE OPENAI MODEL
        # The model name is stored in session_state so it can
        # persist between Streamlit reruns.
    # ------------------------------------------------------------------
    if "openai_model" not in st.session_state:
        st.session_state["openai_model"] = "gpt-5.6-luna"

    # ------------------------------------------------------------------
    # 17.4 CREATE THE INITIAL SYSTEM MESSAGE
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
        # 17.5 GENERATE FIRST INTERVIEW QUESTION
            # The candidate has not answered anything yet.
            # Therefore we ask OpenAI to generate the  first interview question.
        # ------------------------------------------------------------------------
        first_response = client.chat.completions.create(
    
                model=st.session_state["openai_model"],
    
                messages=st.session_state.messages,
    
                reasoning_effort="none",
    
                max_completion_tokens=300
            )
        
        # Extract the AI's first question.
        first_question = (
            first_response.choices[0].message.content
        )

        # ------------------------------------------------------------------
        # 17.6 SAVE FIRST AI QUESTION
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
    # 17.7 DISPLAY PREVIOUS CHAT HISTORY
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
    # 17.8 GET USER'S ANSWER
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
            # 17.9 SAVE USER'S ANSWER
                  # The user's answer is added to the conversation history.
            # ------------------------------------------------
            st.session_state.messages.append(
                {
                    "role": "user",
                    "content": prompt
                }
            )

            # ------------------------------------------------
            # 17.10 DISPLAY USER'S ANSWER
               # Shows the answer in the chat interface.
            # ------------------------------------------------
            with st.chat_message("user"):
                st.markdown(prompt)

            # ------------------------------------------------------------------
            # 17.11 INCREMENT ANSWER COUNT
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
            # 17.12 CHECK WHETHER THIS WAS THE 5TH ANSWER
                # This is the most important part.
                # If count is LESS than 5:
                #  Ask OpenAI for another question.
                # If count is 5:
                #  DO NOT call OpenAI. Instead show the fixed completion message.
            # ---------------------------------------------------------------------
            if st.session_state.user_message_count < 5:
            
                # -----------------------------------------
                # 17.13 GENERATE NEXT INTERVIEW QUESTION
                # -----------------------------------------
               with st.chat_message("assistant"):
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
                 # 17.14 SAVE AI RESPONSE TO CHAT HISTORY
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
                # 17.15 5TH ANSWER - END THE INTERVIEW
                    # IMPORTANT:
                    # There is NO OpenAI API call here. We simply create a fixed message.
                    # This prevents AI from asking a 6th question.
                # --------------------------------------------------------------------------
                completion_message = (
                    'Thank you for your attempt, '
                    'please click on "Get Feedback" '
                    'option to view your results.'
                )

                # # Display the completion message.
                # with st.chat_message("assistant"):

                #     st.markdown(completion_message)

                # ------------------------------------------------------------------
                # 17.16 Save the completion message to history.
                    # This means it will still appear after the Streamlit rerun.
                # ------------------------------------------------------------------
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": completion_message
                    }
                )

                # ------------------------------------------------------------------
                # 17.17 MARK INTERVIEW AS COMPLETE
                  # This causes the interview section above to stop 
                  # running on the next Streamlit rerun.
                # ------------------------------------------------------------------
                st.session_state.chat_complete = True

                # Refresh to remove the chat input immediately
                st.rerun()

# ------------------------------------------------------------------
# 18 INTERVIEW COMPLETION STATUS
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
# 19. GET FEEDBACK BUTTON
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
# 20. Saves the entire data in Database(MySQL)
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
            r"Overall\s+Score\s*:\s*(10(?:\.0)?|[0-9](?:\.\d+)?)",
            feedback_text,
            re.IGNORECASE
        )
        if not score_match:
            raise ValueError(
                "Could not extract the overall score."
            )
        score = Decimal(score_match.group(1))
        if not Decimal("0") <= score <= Decimal("10"):
            raise ValueError("Score must be between 0 and 10.")
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
        phone = candidate_data.get("phone_number")
        company = candidate_data.get("company")

        # Debug BEFORE executing SQL
        print("Phone value:", repr(phone))
        print("Phone type:", type(phone).__name__)
        print("Phone length:", len(str(phone)) if phone is not None else 0)

        cursor.execute(
            """
            INSERT INTO candidates (name, email, phone, company)
            VALUES (%s, %s, %s , %s)
            ON DUPLICATE KEY UPDATE
                candidate_id = LAST_INSERT_ID(candidate_id),
                name = VALUES(name),
                phone = VALUES(phone),
                company = VALUES(company)
            """,
            (name, email, phone, company)
        )
        candidate_id = cursor.lastrowid
        
        # 2. Save the overall interview result
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

        # 3. Pair each AI question with the user's answer
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

        # 4. Save all question-answer pairs
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
# 21. FEEDBACK SECTION
   # This section appears after the user clicks "Get Feedback".
# ============================================================
if st.session_state.feedback_shown:
    st.subheader("Feedback")

    # -----------------------------------------------------------------------
    # 21.1 Combine all conversation messages into one text block
        # This can later be sent to OpenAI to generate interview feedback.
    # -----------------------------------------------------------------------
    conversation_history = "\n".join(
        [
            f"{msg['role']} : {msg['content']}"
            for msg in st.session_state.messages
        ]
    )    
    feedback_client = OpenAI(api_key = st.secrets["OPENAI_API_KEY"])
    feedback_completion = feedback_client.chat.completions.create(
                model = st.session_state["openai_model"],
                 messages = [
                      {
                           "role" : "system",
                           "content" : """
                                         You are a helpful tool that provides feedback on an interview performance.
                                         Before the Feeback, share the overall performace score of 1 to 10.
                                         Follow this format :
                                         Overall Score : // Your score
                                         Feeback : //Here you put the feedback on what exactly the interviee need to focus
                                         Give only the feedback do not ask any additional questions.
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
                 max_completion_tokens=700
          )
 
    feedback_text = feedback_completion.choices[0].message.content
    st.write(feedback_text)

    # Save the interview only once per session
    if "interview_saved" not in st.session_state:
     st.session_state.interview_saved = False
    if not st.session_state.interview_saved:
     try:
        result = save_interview_to_mysql(
            candidate_data=st.session_state.candidate_data,
            messages=st.session_state.messages,
            feedback_text=feedback_text
        )

        # Mark as saved only after the database function succeeds
        st.session_state.interview_saved = True

        # Detailed information goes to the server console
        print(
            "Interview saved successfully | "
            f"Candidate ID: {result['candidate_id']} | "
            f"Interview ID: {result['interview_id']} | "
            f"Responses saved: {result['responses_saved']}"
        )
        # st.success(
        #     f"Interview saved successfully! "
        #     f"Candidate ID: {result['candidate_id']} | "
        #     f"Interview ID: {result['interview_id']} | "
        #     f"Responses saved: {result['responses_saved']}"
        # )
     except Exception as e:
        st.error("Failed to save interview results.")
        st.exception(e)

    # -----------------------------------------------------------------------------------------
    # 21.2 Reload/restart interview button
            # Install "stream-js-eval" using "pip install stream-js-eval" and then import it.
            # It helps to execute javaScript commands directly from Streamlit,
            # allowing advanced features like page refresh and browser interaction.
    # -----------------------------------------------------------------------------------------
    if st.button("Restart Interview" , type="primary") :
       streamlit_js_eval(js_expressions = "parent.window.location.reload()")

