import base64
import os
import subprocess
import dateparser
from datetime import timedelta
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Google API scopes
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar'
]

def get_services():
    """Authenticate and return Gmail and Calendar service instances."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    gmail_service = build('gmail', 'v1', credentials=creds)
    calendar_service = build('calendar', 'v3', credentials=creds)
    return gmail_service, calendar_service

def get_unread_emails(gmail_service):
    """Fetch unread emails from the inbox."""
    try:
        result = gmail_service.users().messages().list(userId='me', labelIds=['INBOX'], q='is:unread').execute()
        messages = result.get('messages', [])
        return messages
    except HttpError as e:
        print(f"Error fetching unread emails: {e}")
        return []

def generate_ai_reply(prompt):
    """Generate a reply using the Ollama Mistral model, extracting only the AI-generated content."""
    command = f'echo "{prompt}" | ollama run mistral'
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
        output = result.stdout.strip()
        
        # Improved parsing: Assume AI response starts after the first newline or prompt
        if prompt in output:
            # Split by prompt and take the part after it
            output = output.split(prompt, 1)[-1].strip()
        # Further clean up: Take content after the first newline to skip any preamble
        if '\n' in output:
            output = output.split('\n', 1)[-1].strip()
        # Return only non-empty content, otherwise fallback
        return output if output and not output.startswith("Provide") else "AI response unavailable."
    except subprocess.SubprocessError as e:
        print(f"Error executing Ollama command: {e}")
        return "AI response unavailable due to execution error."

def process_email(gmail_service, message):
    """Process an email and generate summary and acknowledgment replies."""
    msg_id = message['id']
    try:
        full_msg = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    except HttpError as e:
        print(f"Error retrieving email {msg_id}: {e}")
        return "No Subject", "Unable to process email body."

    # Get headers
    headers = full_msg['payload']['headers']
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
    sender_email = next((h['value'] for h in headers if h['name'] == 'From'), "").strip()
    cc_recipients = next((h['value'] for h in headers if h['name'] == 'Cc'), "")
    thread_id = full_msg['threadId']
    
    # Get email body with error handling
    body = ""
    try:
        if 'parts' in full_msg['payload']:
            for part in full_msg['payload']['parts']:
                if part['mimeType'] == 'text/plain':
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                    break
        else:
            body = base64.urlsafe_b64decode(full_msg['payload']['body']['data']).decode('utf-8', errors='replace')
    except Exception as e:
        print(f"Error decoding email body for message {msg_id}: {e}")
        body = "Unable to decode email body."

    # Refined summary prompt
    summary_prompt = f"###START###\nOutput only a concise summary of the email content in bullet points.\n###END###\n{body}"
    summary_reply = generate_ai_reply(summary_prompt)
    
    # Refined acknowledgment prompt
    ack_prompt = f"###START###\nOutput only a polite acknowledgment for the email content on behalf of the owner.\n###END###\n{body}"
    ack_reply = generate_ai_reply(ack_prompt) + "\n\nThis is an AI-generated response. The owner will reply soon when available."
    
    send_thread_reply(gmail_service, thread_id, sender_email, subject, summary_reply, cc_recipients, to_self=True)
    send_thread_reply(gmail_service, thread_id, sender_email, subject, ack_reply, cc_recipients, to_self=False)

    return subject, body

def send_thread_reply(gmail_service, thread_id, sender, subject, text, cc_recipients, to_self=False):
    """Send a reply email within the thread."""
    user_profile = gmail_service.users().getProfile(userId='me').execute()
    my_email = user_profile['emailAddress']
    
    mime_msg = MIMEText(text)
    
    if to_self:
        mime_msg['to'] = my_email
    else:
        # Validate sender_email
        if not sender or not sender.strip():
            print(f"Warning: No valid sender email found for thread {thread_id}. Skipping send.")
            return
        # Reply to all: sender + CC recipients
        recipients = [sender.strip()]
        if cc_recipients:
            recipients.extend(cc_recipients.split(','))
        # Remove my email from recipients if present to avoid self-CC
        recipients = [r.strip() for r in recipients if r.strip() and r.strip() != my_email]
        if not recipients:
            print(f"Warning: No valid recipients for thread {thread_id}. Skipping send.")
            return
        mime_msg['to'] = ', '.join(recipients)
        if cc_recipients:
            mime_msg['cc'] = cc_recipients
    
    mime_msg['subject'] = f"Re: {subject}"
    
    raw_msg = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
    body = {'raw': raw_msg, 'threadId': thread_id}
    try:
        gmail_service.users().messages().send(userId='me', body=body).execute()
    except HttpError as e:
        print(f"Error sending email for thread {thread_id}: {e}")

def extract_event_time(text):
    """Extract date/time from email text."""
    return dateparser.parse(text)

def create_calendar_event(calendar_service, summary, start_time):
    """Create a calendar event if a valid start time is provided."""
    if not start_time:
        return False

    end_time = start_time + timedelta(hours=1)

    event = {
        'summary': summary,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
    }

    try:
        calendar_service.events().insert(calendarId='primary', body=event).execute()
        return True
    except HttpError as e:
        print(f"Error creating calendar event: {e}")
        return False

def main():
    """Main function to process unread emails."""
    gmail_service, calendar_service = get_services()
    unread_msgs = get_unread_emails(gmail_service)
    print(f"📨 Found {len(unread_msgs)} unread emails.")

    for msg in unread_msgs:
        subject, body = process_email(gmail_service, msg)
        start_time = extract_event_time(body)
        create_calendar_event(calendar_service, f"Meeting: {subject}", start_time)
        try:
            gmail_service.users().messages().modify(userId='me', id=msg['id'], body={'removeLabelIds': ['UNREAD']}).execute()
        except HttpError as e:
            print(f"Error marking email as read for message {msg['id']}: {e}")

if __name__ == '__main__':
    main()