# AI-Powered Interview Simulator

An AI-powered interview application built with **Python, Streamlit, OpenAI, and MySQL** that simulates technical interviews and evaluates candidate performance.

The application allows candidates to upload their resumes (**PDF, DOCX, or TXT**) or manually enter their details, skills, experience, target role, and preferred company. It generates personalized interview questions, conducts an interactive interview with five questions, and provides detailed feedback with scores, strengths, weaknesses, expected answers, and actionable improvement suggestions.

Candidate profiles, interview responses, scores, and feedback are stored in a **MySQL database**.

## 🚀 Key Features

- **Resume Parsing:** Extracts candidate information and structures it using an OpenAI model.
- **Manual Candidate Setup:** Allows candidates to enter their personal details, skills, experience, job role, seniority level, and preferred company.
- **Personal Information Detection:** Uses Microsoft Presidio to detect and mask selected personal information.
- **AI-Powered Interviews:** Generates personalized interview questions and follow-up questions based on candidate profiles and previous answers.
- **Automated Evaluation:** Provides question-by-question scoring, expected answers, and personalized improvement recommendations.
- **MySQL Integration:** Stores candidate profiles, interview responses, scores, and feedback.
- **Performance Monitoring:** Measures execution times for important operations.
- **Secure Configuration:** Uses Streamlit secrets to manage API keys and database credentials.

## 🛠️ Tech Stack

- **Programming Language:** Python
- **Frontend:** Streamlit
- **AI Integration:** OpenAI API
- **Database:** MySQL
- **Resume Processing:** PyPDF, python-docx
- **PII Detection and Anonymization:** Microsoft Presidio
- **Data Processing:** JSON, Regular Expressions, Hashlib

## 🔄 Application Workflow

1. **Choose Setup Mode:** Upload a resume or enter candidate details manually.
2. **Process Candidate Information:** Extract or collect candidate details, skills, and experience.
3. **Generate Interview Questions:** Use AI to create personalized interview questions.
4. **Conduct the Interview:** Answer five questions through the interactive chat interface.
5. **Evaluate Performance:** Receive an overall score, detailed feedback, expected answers, and improvement suggestions.
6. **Save Results:** Store candidate information and interview results in MySQL.

## 🎯 Project Objective

To provide an interactive, AI-powered interview practice platform that helps candidates assess their technical knowledge, identify areas for improvement, and prepare more effectively for job interviews.
