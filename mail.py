import base64
import os
import subprocess
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Google API scopes (only Gmail.modify is needed for sending replies)
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

# Block 1: Authentication Function
# This function authenticates the script using credentials.json and generates token.json
# for the Gmail account to send replies.
def get_gmail_service():
    """Authenticate and return a Gmail service instance."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)  # Opens browser for OAuth consent
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

# Block 2: Fetch Unread Emails Function
# This function retrieves all unread emails from the inbox of the account being monitored.
def get_unread_emails(gmail_service):
    """Fetch a list of unread email messages from the inbox."""
    try:
        result = gmail_service.users().messages().list(userId='me', labelIds=['INBOX'], q='is:unread').execute()
        messages = result.get('messages', [])
        return messages
    except HttpError as e:
        print(f"Error fetching unread emails: {e}")
        return []

# Block 3: Generate AI Reply Function
# This function generates a reply using the Ollama Mistral model with improved parsing and debugging.
def generate_ai_reply(prompt):
    """Generate a reply using Ollama Mistral, extracting only the AI-generated content with debugging."""
    command = f'echo "{prompt}" | ollama run mistral'
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
        output = result.stdout.strip()
        print(f"Raw Ollama Output: {output}")  # Debug: Print raw output to analyze

        # Improved parsing: Look for content after the ###RESPONSE### marker
        response_marker = "###RESPONSE###"
        if response_marker in output:
            output = output.split(response_marker, 1)[-1].strip()
        elif prompt in output:
            # Fallback: Split by prompt and take the part after it
            output = output.split(prompt, 1)[-1].strip()
        # Further clean up: Take content after the first newline to skip preamble
        if '\n' in output:
            output = output.split('\n', 1)[-1].strip()

        # Return only non-empty content, otherwise use a default acknowledgment
        default_ack = "Thank you for your email. This is an AI-generated response. The owner will reply soon."
        return output if output and not output.startswith(("###", "Provide")) else default_ack

    except subprocess.SubprocessError as e:
        print(f"Error executing Ollama command: {e}")
        return "Thank you for your email. This is an AI-generated response. The owner will reply soon due to an error."

# Block 4: Send Acknowledgment Reply Function
# This function sends an AI-generated acknowledgment reply to the sender of a new email.
def send_acknowledgment_reply(gmail_service, message):
    """Send an AI-generated acknowledgment reply to the email sender."""
    msg_id = message['id']
    try:
        full_msg = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    except HttpError as e:
        print(f"Error retrieving email {msg_id}: {e}")
        return

    # Get headers to identify the sender and subject
    headers = full_msg['payload']['headers']
    sender_email = next((h['value'] for h in headers if h['name'] == 'From'), "").strip()
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
    thread_id = full_msg['threadId']

    if not sender_email:
        print(f"Warning: No valid sender email found for thread {thread_id}. Skipping send.")
        return

    # Generate acknowledgment prompt for AI
    ack_prompt = f"###RESPONSE###\nProvide only a polite acknowledgment for the email content on behalf of the owner.\n{next((base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace') for part in full_msg['payload'].get('parts', []) if part['mimeType'] == 'text/plain'), '') or base64.urlsafe_b64decode(full_msg['payload']['body']['data']).decode('utf-8', errors='replace')}"
    ack_reply = generate_ai_reply(ack_prompt)

    # Create the MIME message with the acknowledgment
    mime_msg = MIMEText(ack_reply)
    mime_msg['to'] = sender_email
    mime_msg['subject'] = f"Re: {subject}"

    # Encode and send the message
    raw_msg = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
    body = {'raw': raw_msg, 'threadId': thread_id}
    try:
        gmail_service.users().messages().send(userId='me', body=body).execute()
        print(f"Sent acknowledgment to {sender_email} for thread {thread_id}")
    except HttpError as e:
        print(f"Error sending acknowledgment for thread {thread_id}: {e}")

# Block 5: Main Function
# This is the entry point of the script. It authenticates, fetches unread emails,
# sends acknowledgments, and marks emails as read.
def main():
    """Main execution loop to process unread emails and send acknowledgments."""
    gmail_service = get_gmail_service()  # Note: Only Gmail service is used, calendar_service is removed
    unread_msgs = get_unread_emails(gmail_service)
    print(f"📨 Found {len(unread_msgs)} unread emails.")

    for msg in unread_msgs:
        send_acknowledgment_reply(gmail_service, msg)
        try:
            gmail_service.users().messages().modify(userId='me', id=msg['id'], body={'removeLabelIds': ['UNREAD']}).execute()
            print(f"Marked email {msg['id']} as read.")
        except HttpError as e:
            print(f"Error marking email {msg['id']} as read: {e}")

if __name__ == '__main__':
    main()