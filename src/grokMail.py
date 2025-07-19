import requests
import msal
import json
import os
from datetime import datetime

# Configuration
CLIENT_ID = "your_client_id"  # Replace with your Azure app client ID
CLIENT_SECRET = "your_client_secret"  # Replace with your Azure app client secret
TENANT_ID = "your_tenant_id"  # Replace with your Azure tenant ID
EMAIL_ADDRESS = "oehamiton@hotmail.com"
GROK_API_KEY = "your_grok_api_key"  # Replace with your xAI Grok API key
PROMPT_FILE = "classification_prompts.txt"
GRAPH_API_ENDPOINT = "https://graph.microsoft.com/v1.0"

# Microsoft Graph API Authentication
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

# Read classification and response prompts from text file
def load_prompts():
    if not os.path.exists(PROMPT_FILE):
        default_prompts = {
            "classification": (
                "Analyze the following email and classify it into one of these categories: Work, Personal, Promotions, Spam. "
                "Return only the category name.\n\nSubject: {subject}\nFrom: {sender}\nBody: {body}"
            ),
            "response": {
                "Work": "Draft a professional, concise response for this email. Start with 'Hello,' and end with 'Best,'. "
                        "Address the email's main points.\n\nSubject: {subject}\nBody: {body}",
                "Personal": "Draft a friendly, concise response for this email. Start with 'Hi,' and end with 'Cheers,'. "
                           "Address the email's main points.\n\nSubject: {subject}\nBody: {body}",
                "Promotions": None,  # No auto-response for Promotions
                "Spam": None  # No auto-response for Spam
            }
        }
        with open(PROMPT_FILE, "w", encoding="utf-8") as f:
            json.dump(default_prompts, f, indent=4)
        return default_prompts
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# Call xAI Grok API for classification or response generation
def call_grok_api(prompt, api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "prompt": prompt,
        "max_tokens": 150
    }
    response = requests.post("https://api.x.ai/grok", headers=headers, json=data)
    if response.status_code == 200:
        return response.json().get("choices")[0].get("text").strip()
    else:
        raise Exception(f"Grok API call failed: {response.text}")

# Create or get folder ID in Outlook
def get_or_create_folder(access_token, folder_name):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    # Check if folder exists
    response = requests.get(
        f"{GRAPH_API_ENDPOINT}/me/mailFolders",
        headers=headers
    )
    if response.status_code == 200:
        folders = response.json().get("value", [])
        for folder in folders:
            if folder["displayName"].lower() == folder_name.lower():
                return folder["id"]
    
    # Create folder if it doesn't exist
    data = {
        "displayName": folder_name
    }
    response = requests.post(
        f"{GRAPH_API_ENDPOINT}/me/mailFolders",
        headers=headers,
        json=data
    )
    if response.status_code == 201:
        return response.json()["id"]
    else:
        raise Exception(f"Failed to create folder {folder_name}: {response.text}")

# Move email to a subfolder
def move_email(access_token, message_id, folder_id):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "destinationId": folder_id
    }
    response = requests.post(
        f"{GRAPH_API_ENDPOINT}/me/messages/{message_id}/move",
        headers=headers,
        json=data
    )
    if response.status_code != 201:
        print(f"Failed to move email {message_id}: {response.text}")

# Create draft email in Outlook
def create_draft_email(access_token, subject, body, to_recipient):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "message": {
            "subject": f"Re: {subject}",
            "body": {
                "contentType": "Text",
                "content": body
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": to_recipient
                    }
                }
            ]
        },
        "saveToSentItems": False
    }
    response = requests.post(
        f"{GRAPH_API_ENDPOINT}/me/messages",
        headers=headers,
        json=data
    )
    if response.status_code == 201:
        print(f"Draft created for email from {to_recipient}")
    else:
        print(f"Failed to create draft: {response.text}")

# Main processing function
def process_emails():
    access_token = get_access_token()
    prompts = load_prompts()
    
    # Fetch unread emails
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    response = requests.get(
        f"{GRAPH_API_ENDPOINT}/me/mailFolders/inbox/messages?$filter=isRead eq false",
        headers=headers
    )
    if response.status_code != 200:
        raise Exception(f"Failed to fetch emails: {response.text}")
    
    emails = response.json().get("value", [])
    for email in emails:
        message_id = email["id"]
        subject = email["subject"] or "No Subject"
        sender = email["from"]["emailAddress"]["address"]
        body = email["body"]["content"]
        
        # Classify email using Grok API
        classification_prompt = prompts["classification"].format(
            subject=subject, sender=sender, body=body
        )
        category = call_grok_api(classification_prompt, GROK_API_KEY)
        
        # Move email to corresponding folder
        folder_id = get_or_create_folder(access_token, category)
        move_email(access_token, message_id, folder_id)
        print(f"Moved email '{subject}' to {category} folder")
        
        # Auto-draft response if applicable
        response_prompt = prompts["response"].get(category)
        if response_prompt:
            response_text = call_grok_api(
                response_prompt.format(subject=subject, body=body),
                GROK_API_KEY
            )
            create_draft_email(access_token, subject, response_text, sender)

# Run the script
if __name__ == "__main__":
    try:
        process_emails()
    except Exception as e:
        print(f"Error: {e}")