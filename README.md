# QuickCover: AI Cover Letter Generator

[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Framework](https://img.shields.io/badge/Framework-FastAPI-green.svg)](https://fastapi.tiangolo.com/)

QuickCover is a powerful backend service built with FastAPI that leverages Google's Gemini AI to generate professional, tailored cover letters. It intelligently extracts text from a user's resume and a job description to create a persuasive and customized application document.

## ✨ Features

- **AI-Powered Generation**: Utilizes the Google Gemini API for high-quality, context-aware text generation.
- **Flexible Input**: Accepts a resume via URL and a job description via either URL or direct text input.
- **Multi-Format Support**: Automatically parses content from various sources:
  - PDF (`.pdf`)
  - Microsoft Word (`.docx`)
  - HTML web pages
  - Plain text (`.txt`)
- **Robust Web Scraping**: Uses `cloudscraper` to bypass anti-bot measures (like Cloudflare), ensuring reliable content fetching from job description URLs.
- **Google Drive Integration**: Automatically transforms Google Drive share links for resumes into direct download links for seamless parsing.
- **Customizable Output**: Allows users to specify a target word count for the generated cover letter.
- **CORS Enabled**: Configured with open CORS policies (`*`) for easy integration with any frontend application, including those hosted on GitHub Pages.
- **Asynchronous by Design**: Built on FastAPI and `starlette.concurrency` to handle I/O-bound tasks (like fetching URLs and calling the Gemini API) without blocking the server.

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- A Google Gemini API Key. You can get one from Google AI Studio.

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd QuickCover
```

### 2. Create a Virtual Environment

It's highly recommended to use a virtual environment to manage project dependencies.

```bash
# On macOS/Linux
python3 -m venv venv
source venv/bin/activate

# On Windows
python -m venv venv
.\venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Environment Variable

The application requires your Gemini API key to be set as an environment variable.

```bash
# On macOS/Linux
export GEMINI_API_KEY="your_api_key_here"

# On Windows (Command Prompt)
set GEMINI_API_KEY="your_api_key_here"

# On Windows (PowerShell)
$env:GEMINI_API_KEY="your_api_key_here"
```

### 5. Run the Application

Use `uvicorn` to run the FastAPI server. The `--reload` flag will automatically restart the server when you make code changes.

```bash
uvicorn app:app --reload
```

The service will be available at `http://127.0.0.1:8000`.

## 📖 API Documentation

The application exposes one primary endpoint for generating cover letters.

### `POST /generate`

This endpoint fetches the resume and job description, sends them to the Gemini API, and returns a generated cover letter.

**Request Body** (`application/json`):

```json
{
  "resume_url": "https://path/to/your/resume.pdf",
  "job_description_url": "https://www.linkedin.com/jobs/view/12345",
  "job_description_text": null,
  "word_count": 350
}
```
> **Note**: You must provide either `job_description_url` or `job_description_text`.

**Example `curl` Request:**

```bash
curl -X POST "http://127.0.0.1:8000/generate" \
-H "Content-Type: application/json" \
-d '{
      "resume_url": "URL_TO_YOUR_RESUME.pdf",
      "job_description_text": "We are looking for a skilled Python developer with experience in FastAPI...",
      "word_count": 300
    }'
```

**Success Response** (`200 OK`):

```json
{
    "status": "success",
    "cover_letter": "Dear Hiring Manager,\n\nI am writing to express my keen interest in the Python Developer position... [Generated Cover Letter Text] ...",
    "word_count_request": 300,
    "job_description_url": null
}
```
