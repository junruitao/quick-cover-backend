import os
import time
import re
import io
import random
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
from starlette.concurrency import run_in_threadpool 
from typing import Optional 
from pypdf import PdfReader
from docx import Document

# Import necessary Gemini components
from google import genai
from google.genai import types

# Import cloudscraper instead of requests for robust fetching
import cloudscraper
from requests.exceptions import RequestException, HTTPError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration and Initialization ---

# Initialize FastAPI app
app = FastAPI(
    title="Cover Letter Generator",
    description="Generates a tailored cover letter using Gemini, based on a resume URL and a specific job description URL."
)

# --- CORS Configuration ---
# FIX: Changing origins to ["*"] to allow access from all domains, 
# including GitHub Pages (https://<username>.github.io/<repo-name>).
origins = ["*"] 

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Keep as ["*"] for flexibility
    allow_headers=["*"], # Keep as ["*"] for flexibility
)
# --- End CORS Configuration ---


# Fetch API Key from environment variable
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not set. Gemini API calls will fail.")

# Initialize Gemini Client (it uses the GEMINI_API_KEY environment variable if set)
try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    client = None
    print(f"Error initializing Gemini client: {e}")

# Data model for the incoming request
class GenerationRequest(BaseModel):
    resume_url: str = Field(..., description="URL pointing to the user's resume (text, PDF, or DOC).")
    # UPDATED: Made URL optional and added text field
    job_description_url: Optional[str] = Field(None, description="Optional URL pointing to the job description (HTML page).")
    job_description_text: Optional[str] = Field(None, description="Optional text content of the job description.")
    word_count: int = Field(300, description="The target word count for the generated cover letter.", ge=50, le=1000)

# --- Core Utility Functions ---

def fetch_url_content(url: str, max_retries: int = 5) -> str:
    """
    Robustly fetches content from a given URL using cloudscraper to bypass anti-bot protection.
    """
    # --- Google Drive Link Transformation ---
    # Check if the URL is a Google Drive share link and transform it into a direct download link.
    gdrive_match = re.search(r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)', url)
    if gdrive_match:
        file_id = gdrive_match.group(1)
        original_url = url
        # The original URL is kept to inspect the file extension later if needed.
        url = f'https://drive.google.com/uc?export=download&id={file_id}'
        logging.info(f"Google Drive link detected. Transforming '{original_url}' to direct download link: '{url}'")
    # --- End Transformation ---


    logging.info(f"Attempting to fetch content from URL: {url}")

    # Define a robust, common User-Agent to help bypass bot detection
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    # 1. Create the cloudscraper session without passing headers directly
    scraper = cloudscraper.create_scraper() 
    # 2. Assign the custom headers after creation (CORRECT METHOD)
    scraper.headers.update(headers)

    for attempt in range(max_retries):
        try:
            # Set a timeout to prevent hanging requests
            response = scraper.get(url, timeout=15)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            
            content_type = response.headers.get('Content-Type', '').lower()
            # Use the original URL for extension checking if it was transformed
            url_for_extension_check = original_url if 'original_url' in locals() else url

            # --- Fallback for generic binary stream ---
            # If the server sends a generic content type, try to infer the type from the URL's file extension.
            # If that fails, inspect the file's magic numbers (the first few bytes).
            if 'application/octet-stream' in content_type:
                logging.warning(f"Received generic 'application/octet-stream' content type. Attempting to infer type from URL: {url_for_extension_check}")
                if url_for_extension_check.lower().endswith('.pdf'):
                    content_type = 'application/pdf'
                elif url_for_extension_check.lower().endswith('.docx'):
                    content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                # Magic number check as a more robust fallback
                elif response.content.startswith(b'%PDF'):
                    logging.info("Inferred PDF from file signature.")
                    content_type = 'application/pdf'
                elif response.content.startswith(b'PK\x03\x04'): # ZIP file signature, common for DOCX
                    logging.info("Inferred DOCX from file signature (ZIP header).")
                    content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

            
            # --- Content Type Handling ---
            if 'application/pdf' in content_type:
                logging.info(f"Successfully fetched PDF content from {url}. Extracting text.")
                try:
                    pdf_file = io.BytesIO(response.content)
                    reader = PdfReader(pdf_file)
                    text = "".join(page.extract_text() or "" for page in reader.pages)
                    return text
                except Exception as e:
                    logging.error(f"Failed to parse PDF from {url}. Error: {e}")
                    raise HTTPException(status_code=500, detail=f"Could not parse the PDF file from the URL. Error: {e}")
            
            elif 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' in content_type:
                logging.info(f"Successfully fetched DOCX content from {url}. Extracting text.")
                try:
                    docx_file = io.BytesIO(response.content)
                    doc = Document(docx_file)
                    text = "\n".join(para.text for para in doc.paragraphs)
                    return text
                except Exception as e:
                    logging.error(f"Failed to parse DOCX from {url}. Error: {e}")
                    raise HTTPException(status_code=500, detail=f"Could not parse the DOCX file from the URL. Error: {e}")
            
            elif 'text/html' in content_type:
                logging.info(f"Successfully fetched HTML content from {url}. Extracting text.")
                return extract_text_from_html(response.text)
            
            elif 'text/' in content_type:
                logging.info(f"Successfully fetched plain text content (Content-Type: {content_type}) from {url}.")
                return response.text
            
            else:
                logging.warning(f"Unsupported content type '{content_type}' at {url}. Cannot extract text.")
                raise HTTPException(status_code=400, detail=f"Unsupported content type: {content_type}. Please provide a URL to a text, HTML, PDF, or DOCX file.")

        except HTTPError as http_err:
            status_code = response.status_code if 'response' in locals() else 500
            error_detail = f"Request failed (Status {status_code}). Attempting retry {attempt + 1}/{max_retries}..."
            
            logging.warning(f"URL: {url} - {error_detail}")
            if attempt < max_retries - 1 and status_code in [403, 404, 503]:
                # Use linear backoff with increased random jitter
                sleep_time = (5 * attempt) + random.uniform(5, 10) 
                logging.info(f"Applying random sleep: {sleep_time:.2f} seconds before next retry.")
                time.sleep(sleep_time) 
            elif attempt < max_retries - 1:
                # Retry for non-anti-bot errors too, but rely on raise_for_status logic
                 time.sleep(2 ** attempt) 
            else:
                # If all retries fail, raise the final error
                logging.error(f"All retries failed for URL: {url}. Last error: {error_detail}")
                raise HTTPException(status_code=status_code, detail=f"Failed to fetch content from URL: {url} after {max_retries} attempts. Last error: {error_detail}")

        except RequestException as e:
            # Handle non-HTTP errors like connection issues or timeouts
            logging.warning(f"Attempt {attempt + 1} failed for {url} due to connection error: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt) # Exponential backoff
            else:
                logging.error(f"All retries failed for URL: {url} due to connection error: {e}")
                raise HTTPException(status_code=400, detail=f"Failed to connect to URL: {url} after {max_retries} attempts. Error: {e}")


def extract_text_from_html(html_content: str) -> str:
    """
    Uses BeautifulSoup to parse HTML and extract the main, readable text, 
    stripping out scripts, styles, and other whitespace.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script, style, and other tags that don't contain meaningful text
    for script_or_style in soup(['script', 'style', 'header', 'footer', 'nav', 'form', 'aside']):
        script_or_style.decompose()

    # Get text
    text = soup.get_text()
    
    # Break into lines and remove leading/trailing space on each
    lines = (line.strip() for line in text.splitlines())
    # Break multiple lines into paragraphs
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    # Drop blank lines
    text = '\n'.join(chunk for chunk in chunks if chunk)
    
    return text

# --- API Endpoints ---

@app.get("/")
def read_root():
    """Simple health check endpoint."""
    return {"message": "Cover Letter Generator Service is Running. POST to /generate."}


@app.options("/generate")
async def options_generate():
    """
    NEW: Explicit OPTIONS handler to ensure CORS preflight checks pass with a 200 OK.
    This prevents Pydantic validation errors (400) on the empty OPTIONS request body.
    """
    return {"message": "CORS preflight successful."}


@app.post("/generate")
async def generate_cover_letter(request: GenerationRequest):
    """
    Fetches resume and job description content and asks Gemini to generate a tailored cover letter.
    """
    # Use a high-level try/except block to catch any unhandled exceptions 
    # and return a proper HTTP 500 response, preventing Uvicorn tracebacks.
    try:
        if not client:
            raise HTTPException(status_code=500, detail="Gemini API Client is not initialized. Check GEMINI_API_KEY environment variable.")
        
        # New validation check: ensure either URL or text is provided for JD
        if not request.job_description_url and not request.job_description_text:
             raise HTTPException(status_code=400, detail="Must provide either a Job Description URL or paste the job description text.")


        # 1. Fetch Resume Content - NOW RUN IN THREADPOOL
        try:
            # Explicitly run synchronous I/O in a separate thread
            resume_content = await run_in_threadpool(fetch_url_content, request.resume_url)
        except HTTPException as e:
            raise HTTPException(status_code=400, detail=f"Resume URL Error: {e.detail}")
        
        if not resume_content:
            raise HTTPException(status_code=400, detail="Resume content is empty after attempting to fetch from URL. The URL may be inaccessible or the content is empty.")

        # 2. Get Job Description Content
        job_description_content = request.job_description_text
        
        if not job_description_content and request.job_description_url:
            try:
                # Explicitly run synchronous I/O in a separate thread
                job_description_content = await run_in_threadpool(fetch_url_content, request.job_description_url)
            except HTTPException as e:
                # Re-raise the exception raised by fetch_url_content (which is already an HTTPException)
                raise HTTPException(status_code=400, detail=f"Job Description URL Error: {e.detail}")
        
        if not job_description_content:
             raise HTTPException(status_code=400, detail="Job Description content is empty after attempting to fetch or using provided text.")


        # 3. Construct the Prompt for Gemini
        system_prompt = (
            "You are a professional career coach and expert cover letter writer. "
            "Your task is to generate a highly tailored, persuasive cover letter based on the user's resume and a specific job description. "
            "The letter must not exceed the specified word count."
        )
        
        user_prompt = f"""
        Generate a professional cover letter.
        
        --- CONSTRAINTS ---
        1. The cover letter must be professional and highly customized.
        2. The word count must be approximately {request.word_count} words.
        3. The tone should be enthusiastic and confident.
        4. You must only mention skills and experiences that are explicitly present in the provided resume
        
        --- INPUT DATA ---
        
        [JOB DESCRIPTION]
        {job_description_content}
        
        [RESUME]
        {resume_content}
        """

        # 4. Call the Gemini API - NOW RUN IN THREADPOOL
        try:
            print("Sending request to Gemini...")
            
            # The client call is synchronous, so run it in a threadpool
            response = await run_in_threadpool(
                client.models.generate_content,
                model='gemini-2.5-flash',
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.7,
                ),
            )

            cover_letter = response.text
            
            if not cover_letter:
                raise Exception("Gemini returned an empty response.")
            
            return {
                "status": "success",
                "cover_letter": cover_letter,
                "word_count_request": request.word_count,
                "job_description_url": request.job_description_url
            }

        except Exception as e:
            print(f"Gemini API Error: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to generate cover letter with Gemini API. Error: {e}")

    except HTTPException:
        # Re-raise explicit HTTP exceptions (like 400s or 500s we raised intentionally)
        raise
    except Exception as e:
        # Catch all other unexpected errors
        print(f"An unexpected internal server error occurred: {e}")
        # Return a generic 500 error to the client
        raise HTTPException(status_code=500, detail=f"An unexpected internal server error occurred: {str(e)}")