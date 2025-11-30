import os
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # Import CORS middleware
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup

# Import necessary Gemini components
from google import genai
from google.genai import types

# Import cloudscraper instead of requests for robust fetching
import cloudscraper
from requests.exceptions import RequestException, HTTPError

# --- Configuration and Initialization ---

# Initialize FastAPI app
app = FastAPI(
    title="Cover Letter Generator",
    description="Generates a tailored cover letter using Gemini, based on a resume URL and a specific job description URL."
)

# --- CORS Configuration ---
# NOTE: The origins list should be updated for deployment.
# We are including common development environments (localhost:3000)
# and allowing your production deployment URL.
origins = [
    "http://localhost:3000",  # Local React development server
    "http://localhost:8080",  # Common other local ports
    "https://cover-letter-generator-310631449500.australia-southeast1.run.app" # Your Cloud Run URL (sometimes needed)
    # If your frontend is deployed to Firebase or another host, add that URL here:
    # e.g., "https://your-firebase-app-id.web.app" 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # List of allowed origins
    allow_credentials=True,      # Allow cookies/authorization headers
    allow_methods=["*"],         # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],         # Allow all headers
)
# --- End CORS Configuration ---


# Fetch API Key from environment variable
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    # This is fine for local development but must be set in Cloud Run/GitHub Actions secrets
    print("Warning: GEMINI_API_KEY not set. Gemini API calls will fail.")

# Initialize Gemini Client (it uses the GEMINI_API_KEY environment variable if set)
try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    # Client initialization might fail if key is missing/invalid, handle gracefully
    client = None
    print(f"Error initializing Gemini client: {e}")

# Data model for the incoming request
class GenerationRequest(BaseModel):
    resume_url: str = Field(..., description="URL pointing to the user's resume (text, PDF, or DOC).")
    job_description_url: str = Field(..., description="URL pointing to the job description (HTML page).")
    word_count: int = Field(300, description="The target word count for the generated cover letter.", ge=50, le=1000)

# --- Core Utility Functions ---

def fetch_url_content(url: str, max_retries: int = 5) -> str:
    """
    Robustly fetches content from a given URL using cloudscraper to bypass anti-bot protection.
    
    Increased max_retries to 5 and added a robust User-Agent header to mimic browser traffic.
    """
    # Define a robust, common User-Agent to help bypass bot detection
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    # Create the cloudscraper session, passing in the realistic headers
    scraper = cloudscraper.create_scraper(headers=headers) 

    for attempt in range(max_retries):
        try:
            # Set a timeout to prevent hanging requests
            response = scraper.get(url, timeout=15)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
            
            content_type = response.headers.get('Content-Type', '').lower()

            if 'text/html' in content_type:
                # Use BeautifulSoup to clean and extract readable text from HTML
                return extract_text_from_html(response.text)
            
            # For other text-based files, return the content
            return response.text

        except HTTPError as http_err:
            status_code = response.status_code if 'response' in locals() else 500
            error_detail = f"Request failed (Status {status_code}). Attempting retry {attempt + 1}/{max_retries}..."
            
            print(error_detail)
            if attempt < max_retries - 1 and status_code in [403, 404, 503]:
                time.sleep(2 ** attempt) # Exponential backoff for anti-bot errors
            elif attempt < max_retries - 1:
                # Retry for non-anti-bot errors too, but rely on raise_for_status logic
                 time.sleep(2 ** attempt) 
            else:
                # If all retries fail, raise the final error
                raise HTTPException(status_code=status_code, detail=f"Failed to fetch content from URL: {url} after {max_retries} attempts. Last error: {error_detail}")

        except RequestException as e:
            # Handle non-HTTP errors like connection issues or timeouts
            print(f"Attempt {attempt + 1} failed for {url} due to connection error: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt) # Exponential backoff
            else:
                raise HTTPException(status_code=400, detail=f"Failed to connect to URL: {url} after {max_retries} attempts. Error: {e}")

    
    # This line should ideally not be reached
    raise HTTPException(status_code=400, detail=f"Failed to fetch content from URL after {max_retries} attempts: {url}")


def extract_text_from_html(html_content: str) -> str:
    """
    Uses BeautifulSoup to parse HTML and extract the main, readable text, 
    stripping out scripts, styles, and extra whitespace.
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


@app.post("/generate")
async def generate_cover_letter(request: GenerationRequest):
    """
    Fetches resume and job description content and asks Gemini to generate a tailored cover letter.
    """
    if not client:
        raise HTTPException(status_code=500, detail="Gemini API Client is not initialized. Check GEMINI_API_KEY environment variable.")

    # 1. Fetch Resume Content
    try:
        # NOTE: For simplicity, we treat the resume content as raw text.
        resume_content = fetch_url_content(request.resume_url)
    except HTTPException as e:
        raise HTTPException(status_code=400, detail=f"Resume URL Error: {e.detail}")

    # 2. Fetch Job Description Content (Fixed with cloudscraper)
    try:
        # This will use the robust fetching and HTML cleaning logic
        job_description_content = fetch_url_content(request.job_description_url)
    except HTTPException as e:
        raise HTTPException(status_code=400, detail=f"Job Description URL Error: {e.detail}")

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
    4. Start with a standard business salutation (e.g., "Dear Hiring Manager,").
    
    --- INPUT DATA ---
    
    [JOB DESCRIPTION]
    {job_description_content}
    
    [RESUME SUMMARY (Key Skills/Experience)]
    {resume_content}
    """

    # 4. Call the Gemini API
    try:
        print("Sending request to Gemini...")
        
        response = client.models.generate_content(
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