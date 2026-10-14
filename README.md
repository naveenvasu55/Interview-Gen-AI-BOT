AI-Powered Interview Simulator

An AI-powered interview application built with Python, Streamlit, OpenAI, and MySQL that simulates technical interviews and evaluates candidate performance.

The application allows candidates to either upload their resume (PDF, DOCX, or TXT) for automatic information extraction or manually enter their personal details, skills, experience, target role, and preferred company. Using AI, it generates personalized interview questions, conducts an interactive chat-based interview with five questions, and provides detailed feedback with scores, strengths, weaknesses, expected answers, and actionable improvement suggestions.

Candidate profiles, interview questions, answers, scores, and feedback are stored in a MySQL database for record keeping.

Key Features

Resume Parsing: Extracts candidate information and structures it using an OpenAI model.

Manual Candidate Setup: Supports candidate details, skills, experience, job role, seniority level, and company selection.

Personal Information Detection: Uses Microsoft Presidio to detect and mask selected personal information.

AI-Powered Interviews: Generates personalized questions and follow-ups based on candidate profiles and previous answers.

Automated Evaluation: Provides question-by-question scoring, expected answers, and personalized improvement recommendations.

MySQL Integration: Stores candidate profiles, interview responses, scores, and feedback.

Performance Monitoring: Measures execution times for key operations.

Secure Configuration: Uses Streamlit secrets to manage API keys and database credentials.

Tech Stack

Language: Python

Frontend: Streamlit

AI Integration: OpenAI API

Database: MySQL

Resume Processing: PyPDF, python-docx

PII Detection and Anonymization: Microsoft Presidio

Data Processing: JSON, Regular Expressions, Hashlib

Application Workflow

Choose resume upload or manual candidate setup.

Extract or collect candidate information.

Generate personalized interview questions using AI.

Answer five interview questions through the chat interface.

Receive an overall score, detailed evaluation, and improvement suggestions.

Store candidate and interview results in MySQL.
