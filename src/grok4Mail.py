import sys
import aiohttp
import asyncio
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv
import msal
import requests  # For sync auth, but async for API calls
import re  # For HTML stripping
from bs4 import BeautifulSoup

load_dotenv()

# Configuration (from env vars)
CLIENT_ID = os.getenv("CLIENT_ID")
GROK_API_KEY = os.getenv("GROK_API_KEY")
EMAIL_ADDRESS = "oehamiton@hotmail.com"  # As provided; correct if typo (e.g., oehamilton)
PROMPT_FILE = "email_classifier.txt"
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"
GROK_API_ENDPOINT = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4-0709"  # Updated to valid model name per xAI docs

AUTHORITY = "https://login.microsoftonline.com/common"  # 'common' for personal accounts
SCOPES = ["https://graph.microsoft.com/Mail.ReadWrite", "https://graph.microsoft.com/Mail.Send", "https://graph.microsoft.com/User.Read"]  # No offline_access; MSAL adds it automatically
REDIRECT_PORT = 8000  # Extracted port for fixed use; matches your registered http://localhost:8000
CACHE_FILE = "token_cache.json"  # For persisting tokens locally

# Create public client app
app = msal.PublicClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    token_cache=msal.SerializableTokenCache()  # For caching
)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache = app.token_cache
            cache.deserialize(f.read())

def save_cache():
    with open(CACHE_FILE, "w") as f:
        f.write(app.token_cache.serialize())

def get_access_token():
    load_cache()
    accounts = app.get_accounts()
    
    if accounts:
        # Silent refresh if token exists
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result:
            save_cache()
            print("Access token refreshed silently.")
            return result["access_token"]
    
    # Interactive auth (opens browser; uses http://localhost base with fixed port)
    print("Starting interactive authentication...")
    result = app.acquire_token_interactive(SCOPES, port=REDIRECT_PORT)
    if "access_token" in result:
        save_cache()
        print("Interactive authentication successful.")
        return result["access_token"]
    else:
        raise Exception(f"Authentication failed: {result.get('error_description')}")

# Load prompts (with backward compatibility for old format)
def load_prompts():
    if not os.path.exists(PROMPT_FILE):
        # Create default with new format
        print("Prompt file not found, creating default prompts...")
        default_prompts = {
            "model": DEFAULT_MODEL,
            "classification": {
                "system": "You are a helpful email classifier. Analyze the email content, ignoring any HTML or CSS formatting. Classify it into one category: Work, Personal, Promotions, Spam, Urgent. Return ONLY the category name.",
                "user": "Subject: {subject}\nFrom: {sender}\nBody: {body}"
            },
            "response": {
                "Work": {
                    "system": "Draft a professional response. Start with 'Hello,' and end with 'Best regards,'. Be concise.",
                    "user": "Subject: {subject}\nBody: {body}"
                },
                "Personal": {
                    "system": "Draft a friendly response. Start with 'Hi,' and end with 'Cheers,'. Be concise.",
                    "user": "Subject: {subject}\nBody: {body}"
                },
                "Urgent": {
                    "system": "Draft an urgent response. Highlight key actions.",
                    "user": "Subject: {subject}\nBody: {body}"
                },
                "Promotions": None,
                "Spam": None
            }
        }
        with open(PROMPT_FILE, "w", encoding="utf-8") as f:
            json.dump(default_prompts, f, indent=4)
        return default_prompts
    
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        prompts = json.load(f)
    
    print(prompts)
    # Migrate old format if detected (classification is string)
    if isinstance(prompts.get("classification"), str):
        print("Migrating old prompt format to new system/user structure...")
        old_class = prompts["classification"]
        prompts["classification"] = {
            "system": "You are a helpful email classifier. " + old_class.split("\n\n")[0],
            "user": "\n\n".join(old_class.split("\n\n")[1:])
        }
        for cat, resp in prompts["response"].items():
            if resp:
                prompts["response"][cat] = {
                    "system": "You are a helpful email responder. " + resp.split("\n\n")[0],
                    "user": "\n\n".join(resp.split("\n\n")[1:])
                }
        prompts["model"] = DEFAULT_MODEL  # Add if missing
        # Save migrated version
        with open(PROMPT_FILE, "w", encoding="utf-8") as f:
            json.dump(prompts, f, indent=4)
    
    return prompts

# Async call to Grok API with retry and debug
async def call_grok_api(session, system_prompt, user_prompt, model, max_tokens=150, retries=3):
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.2,  # Low for consistency in classification
        "stream": False
    }
    for attempt in range(retries):
        try:
            async with session.post(GROK_API_ENDPOINT, headers=headers, json=data, timeout=30) as response:
                if response.status == 200:
                    resp_json = await response.json()
                    #print(f"Debug: Full Grok API response: {json.dumps(resp_json, indent=2)}")  # Debug print
                    if "choices" in resp_json and resp_json["choices"]:
                        return resp_json["choices"][0]["message"]["content"].strip()
                    else:
                        print("Warning: No 'choices' in API response.")
                        return None
                else:
                    error = await response.text()
                    print(f"API error (attempt {attempt+1}): {error}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except Exception as e:
            print(f"Exception in API call: {e}")
            await asyncio.sleep(2 ** attempt)
    raise Exception("Grok API call failed after retries")

# Fetch all folders with pagination
def fetch_all_folders(access_token, parent_id=None):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    url = f"{GRAPH_API_ENDPOINT}/me/mailFolders"
    if parent_id:
        url = f"{GRAPH_API_ENDPOINT}/me/mailFolders/{parent_id}/childFolders"
    folders = []
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            folders.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        else:
            raise Exception("Failed to fetch folders")
    return folders

# Get Inbox ID
def get_inbox_id(access_token):
    folders = fetch_all_folders(access_token)
    for folder in folders:
        if folder["displayName"].lower() == "inbox":
            return folder["id"]
    raise Exception("Inbox folder not found")

# Get or create folder as subfolder of Inbox
def get_or_create_folder(access_token, folder_name):
    if not folder_name:
        folder_name = "Uncategorized"  # Default if empty
        print("Warning: Category was empty; using 'Uncategorized' folder.")
    inbox_id = get_inbox_id(access_token)
    folders = fetch_all_folders(access_token, inbox_id)
    print("Existing subfolders in Inbox:", [f["displayName"] for f in folders])  # Debug print
    for folder in folders:
        if folder["displayName"].lower() == folder_name.lower():
            return folder["id"]
    data = {"displayName": folder_name}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    response = requests.post(f"{GRAPH_API_ENDPOINT}/me/mailFolders/{inbox_id}/childFolders", headers=headers, json=data)
    if response.status_code == 201:
        return response.json()["id"]
    elif "ErrorFolderExists" in response.text:
        # Re-fetch if exists error
        folders = fetch_all_folders(access_token, inbox_id)
        for folder in folders:
            if folder["displayName"].lower() == folder_name.lower():
                return folder["id"]
    print(f"Failed to create folder {folder_name}: {response.text}")  # Add debug for failure
    raise Exception(f"Failed to create folder {folder_name}")

# Move email (sync)
def move_email(access_token, message_id, folder_id):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {"destinationId": folder_id}
    response = requests.post(f"{GRAPH_API_ENDPOINT}/me/messages/{message_id}/move", headers=headers, json=data)
    if response.status_code != 201:
        print(f"Failed to move email {message_id}: {response.text}")  # Add debug

# Mark as read (sync)
def mark_as_read(access_token, message_id):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {"isRead": True}
    response = requests.patch(f"{GRAPH_API_ENDPOINT}/me/messages/{message_id}", headers=headers, json=data)
    if response.status_code != 200:
        print(f"Failed to mark email {message_id} as read: {response.text}")  # Add debug

# Create draft (sync)
def create_draft_email(access_token, subject, body, to_recipient):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {
        "message": {
            "subject": f"Re: {subject}",
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_recipient}}]
        },
        "saveToSentItems": False
    }
    response = requests.post(f"{GRAPH_API_ENDPOINT}/me/messages", headers=headers, json=data)
    if response.status_code == 201:
        print(f"Draft created for email from {to_recipient}")
    else:
        print(f"Failed to create draft: {response.text}")  # Add debug

# Main async processor
async def process_emails():
    access_token = get_access_token()
    prompts = load_prompts()
    model = prompts.get("model", DEFAULT_MODEL)
    print(f"Using model: {model}")
    # Fetch unread emails (batch of 1 for simplicity)
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    response = requests.get(
        f"{GRAPH_API_ENDPOINT}/me/mailFolders/inbox/messages?$filter=isRead eq false&$top=10",
        headers=headers
    )
    if response.status_code != 200:
        raise Exception("Failed to fetch emails")
    
    emails = response.json().get("value", [])
    async with aiohttp.ClientSession() as session:
        tasks = []
        for email in emails:
            tasks.append(process_single_email(session, access_token, email, prompts, model))
        await asyncio.gather(*tasks)

async def process_single_email(session, access_token, email, prompts, model):
    message_id = email["id"]
    subject = email["subject"] or "No Subject"
    sender = email["from"]["emailAddress"]["address"]
    body = email["body"]["content"]
    print(f"Processing email: {subject} from {sender}")
    #print(f"Email body (raw): {body[:1000]}...")  # Print first 100 chars for debug
    
    # Clean HTML from body to make prompt cleaner; most important for classification to avoid token overflow and provide better context
    # Clean HTML from body using BeautifulSoup
    soup = BeautifulSoup(body, 'lxml')  # Use 'lxml' parser for better performance
    body_clean = soup.get_text(separator=' ').strip()  # Join text with single spaces, remove extra whitespace
    body_clean = ' '.join(body_clean.split())  # Normalize whitespace
    body_clean = body_clean[:500]  # Truncate to avoid token overflow
    #print(f"Cleaned body (truncated): {body_clean[:500]}...")  # Print first 500 chars for debug
    
    # Classify
    class_system = prompts["classification"]["system"]
    class_user = prompts["classification"]["user"].format(subject=subject, sender=sender, body=body_clean)
    #print(f"Class System Prompt: {class_system}")
    #print(f"Class User Prompt: {class_user}")
    #Debug step to end or pause here so data being passed to the API can be verified
    #print(f"Debug: Classifying email with subject '{subject}' and body '{body_clean}'")
   
    #sys.exit()  # Stop for debugging purposes
    category = await call_grok_api(session, class_system, class_user, model, max_tokens=512)  # Increased to allow for reasoning + output
    
    print(f"Debug: Returned category: {category} \n")  # Debug to see what was returned
    
    # Move to folder
    folder_id = get_or_create_folder(access_token, category)
    #mark_as_read(access_token, message_id)
    move_email(access_token, message_id, folder_id)
 
    print(f"Moved email '{subject}' to {category} folder")
    
    # Auto-draft if applicable
"""     response_prompt = prompts["response"].get(category)
    if response_prompt:
        resp_system = response_prompt["system"]
        resp_user = response_prompt["user"].format(subject=subject, body=body_clean)  # Use clean body for response too
        response_text = await call_grok_api(session, resp_system, resp_user, model)
        create_draft_email(access_token, subject, response_text, sender) """

if __name__ == "__main__":
    try:
        asyncio.run(process_emails())
    except Exception as e:
        print(f"Error: {e}")