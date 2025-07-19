import aiohttp
import asyncio
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv
import msal
import requests  # For sync auth, but async for API calls

load_dotenv()

# Configuration (from env vars)
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
EMAIL_ADDRESS = "oehamiton@hotmail.com"  # As provided; correct if typo (e.g., oehamiLton)
GROK_API_KEY = os.getenv("GROK_API_KEY")
PROMPT_FILE = "classification_prompts.txt"
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"
GROK_API_ENDPOINT = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4"  # Use Grok 4 for advanced reasoning

# Microsoft Graph API Authentication (sync for simplicity)
def get_access_token():
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=authority,
        client_credential=CLIENT_SECRET
    )
    scopes = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_for_client(scopes=scopes)
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Authentication failed: {result.get('error_description')}")

# Load prompts (now with system/user separation and model option)
def load_prompts():
    if not os.path.exists(PROMPT_FILE):
        default_prompts = {
            "model": DEFAULT_MODEL,
            "classification": {
                "system": "You are a helpful email classifier. Analyze the email and classify it into one category: Work, Personal, Promotions, Spam, Urgent. Return ONLY the category name.",
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
        return json.load(f)

# Async call to Grok API with retry
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
                    return resp_json["choices"][0]["message"]["content"].strip()
                else:
                    error = await response.text()
                    print(f"API error (attempt {attempt+1}): {error}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except Exception as e:
            print(f"Exception in API call: {e}")
            await asyncio.sleep(2 ** attempt)
    raise Exception("Grok API call failed after retries")

# Get or create folder (sync)
def get_or_create_folder(access_token, folder_name):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    response = requests.get(f"{GRAPH_API_ENDPOINT}/me/mailFolders", headers=headers)
    if response.status == 200:
        folders = response.json().get("value", [])
        for folder in folders:
            if folder["displayName"].lower() == folder_name.lower():
                return folder["id"]
    data = {"displayName": folder_name}
    response = requests.post(f"{GRAPH_API_ENDPOINT}/me/mailFolders", headers=headers, json=data)
    if response.status == 201:
        return response.json()["id"]
    raise Exception(f"Failed to create folder {folder_name}")

# Move email (sync)
def move_email(access_token, message_id, folder_id):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {"destinationId": folder_id}
    response = requests.post(f"{GRAPH_API_ENDPOINT}/me/messages/{message_id}/move", headers=headers, json=data)
    if response.status != 201:
        print(f"Failed to move email {message_id}")

# Mark as read (sync)
def mark_as_read(access_token, message_id):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {"isRead": True}
    response = requests.patch(f"{GRAPH_API_ENDPOINT}/me/messages/{message_id}", headers=headers, json=data)
    if response.status != 200:
        print(f"Failed to mark email {message_id} as read")

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
    if response.status == 201:
        print(f"Draft created for email from {to_recipient}")
    else:
        print(f"Failed to create draft")

# Main async processor
async def process_emails():
    access_token = get_access_token()
    prompts = load_prompts()
    model = prompts.get("model", DEFAULT_MODEL)
    
    # Fetch unread emails (batch of 50)
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    response = requests.get(
        f"{GRAPH_API_ENDPOINT}/me/mailFolders/inbox/messages?$filter=isRead eq false&$top=50",
        headers=headers
    )
    if response.status != 200:
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
    
    # Classify
    class_system = prompts["classification"]["system"]
    class_user = prompts["classification"]["user"].format(subject=subject, sender=sender, body=body)
    category = await call_grok_api(session, class_system, class_user, model, max_tokens=50)
    
    # Move to folder
    folder_id = get_or_create_folder(access_token, category)
    move_email(access_token, message_id, folder_id)
    mark_as_read(access_token, message_id)
    print(f"Moved email '{subject}' to {category} folder")
    
    # Auto-draft if applicable
    response_prompt = prompts["response"].get(category)
    if response_prompt:
        resp_system = response_prompt["system"]
        resp_user = response_prompt["user"].format(subject=subject, body=body)
        response_text = await call_grok_api(session, resp_system, resp_user, model)
        create_draft_email(access_token, subject, response_text, sender)

if __name__ == "__main__":
    try:
        asyncio.run(process_emails())
    except Exception as e:
        print(f"Error: {e}")