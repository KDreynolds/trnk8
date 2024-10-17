from fastapi import FastAPI, Request, Form, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import os
import string
import random
from dotenv import load_dotenv
import validators
from supabase import create_client, Client
from datetime import datetime

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}"
}

security = HTTPBearer(auto_error=False)

async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        token = token.split("Bearer ")[1]
        user = supabase.auth.get_user(token)
        if user.user:
            # Access display_name from user_metadata
            display_name = user.user.user_metadata.get("display_name", "Unknown")
            # Add display_name to the user object
            user_dict = user.user.__dict__
            user_dict['display_name'] = display_name
            return user_dict
    except Exception as e:
        print(f"Token validation error: {str(e)}")
        return None

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "user": None})

@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if response.user:
            access_token = response.session.access_token
            redirect = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
            redirect.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
            return redirect
        else:
            return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})
    except Exception as e:
        print(f"Login error: {str(e)}")
        return templates.TemplateResponse("login.html", {"request": request, "error": f"Login failed: {str(e)}"})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register(request: Request, username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    try:
        print(f"Attempting to register user with email: {email} and username: {username}")  # Debugging line

        auth_response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "display_name": username
                }
            }
        })

        if auth_response.user:
            if auth_response.session is None:
                return templates.TemplateResponse("register.html", {
                    "request": request, 
                    "success": "Registration successful. Please check your email to confirm your account."
                })
            else:
                access_token = auth_response.session.access_token
                print(f"Access token obtained: {access_token}")  # Debugging line
                redirect = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
                redirect.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
                return redirect
        else:
            print("Registration failed: No user returned")  # Debugging line
            return templates.TemplateResponse("register.html", {"request": request, "error": "Registration failed. Please try again."})
    except Exception as e:
        print(f"Registration error: {str(e)}")  # Debugging line
        if "already registered" in str(e):
            return templates.TemplateResponse("register.html", {"request": request, "error": "Email already registered"})
        return templates.TemplateResponse("register.html", {"request": request, "error": f"Registration failed: {str(e)}"})

@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response

@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return FileResponse('static/images/favicon.png')

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return templates.TemplateResponse("landing.html", {"request": request})
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.post("/", response_class=HTMLResponse)
async def create_short_url(
    request: Request, 
    url: str = Form(...), 
    user: dict = Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # Validate URL
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    if not validators.url(url):
        return templates.TemplateResponse("index.html", {"request": request, "error": "Invalid URL.", "user": user})

    # Generate unique short code
    async with httpx.AsyncClient() as client:
        try:
            while True:
                short_code = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
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

            # Insert into Supabase with user_id
            insert_response = await client.post(
                f"{SUPABASE_URL}/rest/v1/urls",
                json={
                    "original_url": url, 
                    "short_code": short_code, 
                    "user_id": user.id  # Include user_id
                },
                headers=headers
            )

            if insert_response.status_code != 201:
                return templates.TemplateResponse("index.html", {"request": request, "error": "Failed to save URL.", "user": user})

        except Exception as e:
            print(f"Exception occurred: {e}")
            return templates.TemplateResponse("index.html", {"request": request, "error": "An error occurred.", "user": user})

    short_url = f"{request.url.scheme}://{request.url.netloc}/{short_code}"

    if 'HX-Request' in request.headers:
        return templates.TemplateResponse("partials/short_url.html", {"request": request, "short_url": short_url, "user": user})

    return templates.TemplateResponse("index.html", {"request": request, "short_url": short_url, "user": user})
        
@app.get("/account", response_class=HTMLResponse)
async def account(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("account.html", {"request": request, "user": user})

@app.get("/links", response_class=HTMLResponse)
async def links(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/urls",
                params={
                    "select": "original_url,short_code,created_at",
                    "user_id": f"eq.{user['id']}",  # Access id as a dictionary key
                    "order": "created_at.desc"
                },
                headers=headers
            )
            if response.status_code != 200:
                print(f"Error fetching links: {response.text}")
                raise HTTPException(status_code=500, detail="Internal Server Error")
            links = response.json()
        except Exception as e:
            print(f"Exception occurred: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")

    return templates.TemplateResponse("links.html", {"request": request, "user": user, "links": links})
        

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

