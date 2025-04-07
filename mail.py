import base64
import os
import subprocess
import dateparser
from datetime import timedelta
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Google API scopes
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar'
]

def get_services():
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
    result = gmail_service.users().messages().list(userId='me', labelIds=['INBOX'], q='is:unread').execute()
    messages = result.get('messages', [])
    return messages

def generate_ai_reply(prompt):
    command = f'echo "{prompt}" | ollama run mistral'
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout.strip()

# Modified to process full email body and return CC recipients
def process_email(gmail_service, message):
    msg_id = message['id']
    full_msg = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    
    # Get headers
    headers = full_msg['payload']['headers']
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
    sender_email = next((h['value'] for h in headers if h['name'] == 'From'), "")
    cc_recipients = next((h['value'] for h in headers if h['name'] == 'Cc'), "")
    thread_id = full_msg['threadId']
    
    # Get email body
    body = ""
    if 'parts' in full_msg['payload']:
        for part in full_msg['payload']['parts']:
            if part['mimeType'] == 'text/plain':
                body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                break
    else:
        body = base64.urlsafe_b64decode(full_msg['payload']['body']['data']).decode('utf-8')

    # 1. Summary for self using body
    summary_prompt = f"Summarize this email content in bullet points:\nContent: {body}"
    summary_reply = generate_ai_reply(summary_prompt)
    send_thread_reply(gmail_service, thread_id, sender_email, subject, summary_reply, cc_recipients, to_self=True)

    # 2. Acknowledgment for all using body
    ack_prompt = f"Generate a polite acknowledgment for this email content: {body}"
    ack_reply = generate_ai_reply(ack_prompt) + "\n\nThis is an AI-generated response. The owner will reply soon when available."
    send_thread_reply(gmail_service, thread_id, sender_email, subject, ack_reply, cc_recipients, to_self=False)

    return subject, body

# Modified to handle CC recipients
def send_thread_reply(gmail_service, thread_id, sender, subject, text, cc_recipients, to_self=False):
    user_profile = gmail_service.users().getProfile(userId='me').execute()
    my_email = user_profile['emailAddress']
    
    mime_msg = MIMEText(text)
    
    if to_self:
        mime_msg['to'] = my_email
    else:
        # Reply to all: sender + CC recipients
        recipients = [sender]
        if cc_recipients:
            recipients.extend(cc_recipients.split(','))
        # Remove my email from recipients if present to avoid self-CC
        recipients = [r.strip() for r in recipients if r.strip() != my_email]
        mime_msg['to'] = ', '.join(recipients)
        if cc_recipients:
            mime_msg['cc'] = cc_recipients
    
    mime_msg['subject'] = f"Re: {subject}"
    
    raw_msg = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
    body = {'raw': raw_msg, 'threadId': thread_id}
    gmail_service.users().messages().send(userId='me', body=body).execute()

def extract_event_time(text):
    dt = dateparser.parse(text)
    return dt

def create_calendar_event(calendar_service, summary, start_time):
    if not start_time:
        return False

    end_time = start_time + timedelta(hours=1)

    event = {
        'summary': summary,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
    }

    calendar_service.events().insert(calendarId='primary', body=event).execute()
    return True

def main():
    gmail_service, calendar_service = get_services()
    unread_msgs = get_unread_emails(gmail_service)
    print(f"📨 Found {len(unread_msgs)} unread emails.")

    for msg in unread_msgs:
        subject, body = process_email(gmail_service, msg)
        start_time = extract_event_time(body)
        create_calendar_event(calendar_service, f"Meeting: {subject}", start_time)
        gmail_service.users().messages().modify(userId='me', id=msg['id'], body={'removeLabelIds': ['UNREAD']}).execute()

if __name__ == '__main__':
    main()