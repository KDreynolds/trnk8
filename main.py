from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import httpx
import os
import string
import random
from dotenv import load_dotenv
import validators
from fastapi.staticfiles import StaticFiles

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

headers = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}

def generate_short_code(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/", response_class=HTMLResponse)
async def create_short_url(request: Request, url: str = Form(...)):
    from datetime import datetime  # Import to pass current year if needed

    # Validate URL
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    if not validators.url(url):
        return templates.TemplateResponse("index.html", {"request": request, "error": "Invalid URL."})

    # Generate unique short code
    async with httpx.AsyncClient() as client:
        try:
            while True:
                short_code = generate_short_code()
                response = await client.get(
                    f"{SUPABASE_URL}/rest/v1/urls",
                    params={"select": "short_code", "short_code": f"eq.{short_code}"},
                    headers=headers
                )
                if response.status_code != 200:
                    print(f"Error checking short code: {response.text}")
                    continue  # Try generating a new short code
                if not response.json():
                    break  # Short code is unique

            # Insert into Supabase
            insert_response = await client.post(
                f"{SUPABASE_URL}/rest/v1/urls",
                json={"original_url": url, "short_code": short_code},
                headers=headers
            )

            # Log the response from Supabase
            print(f"Insert response status: {insert_response.status_code}")
            print(f"Insert response body: {insert_response.text}")

            if insert_response.status_code != 201:
                return templates.TemplateResponse("index.html", {"request": request, "error": "Failed to save URL.", "current_year": datetime.now().year})

        except Exception as e:
            print(f"Exception occurred: {e}")
            return templates.TemplateResponse("index.html", {"request": request, "error": "An error occurred.", "current_year": datetime.now().year})

    # Assign short_url after successful insertion
    short_url = f"{request.url.scheme}://{request.url.netloc}/{short_code}"

    # Now, check for 'HX-Request' after 'short_url' is assigned
    if 'HX-Request' in request.headers:
        return templates.TemplateResponse("partials/short_url.html", {"request": request, "short_url": short_url})

    return templates.TemplateResponse("index.html", {"request": request, "short_url": short_url, "current_year": datetime.now().year})



@app.get("/{short_code}")
async def redirect_url(short_code: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/urls",
                params={"select": "original_url", "short_code": f"eq.{short_code}"},
                headers=headers
            )
            if response.status_code != 200:
                print(f"Error fetching original URL: {response.text}")
                raise HTTPException(status_code=404, detail="URL not found")
            data = response.json()
            if data:
                original_url = data[0]['original_url']
                return RedirectResponse(original_url)
            else:
                raise HTTPException(status_code=404, detail="URL not found")
        except Exception as e:
            print(f"Exception occurred: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})


@app.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})


@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})

