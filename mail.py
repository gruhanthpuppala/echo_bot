import base64
import os
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Google API scopes (only Gmail.modify is needed for sending replies)
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

# Custom acknowledgment message (replace [Your LinkedIn URL] with your actual LinkedIn profile URL)
ACKNOWLEDGMENT_MESSAGE = (
    "Thanks for reaching out to Mr. Gruhanth! I am an AI agent acknowledging this mail "
    "and sharing my LinkedIn profile to be in touch and connect socially/professionally. "
    "You can connect with me at: [Your LinkedIn URL].\n\n"
    "Best regards,\nAssistant Agent (mail-id-2)"
)

# Block 1: Authentication Function
# This function authenticates the script using credentials.json for mail-id-2
# to send replies from mail-id-2.
def get_gmail_service():
    """Authenticate and return a Gmail service instance for mail-id-2."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)  # Opens browser for OAuth consent from mail-id-2
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

# Block 2: Fetch Unread Emails Function
# This function retrieves all unread emails from the inbox of mail-id-1.
def get_unread_emails(gmail_service):
    """Fetch a list of unread email messages from mail-id-1's inbox."""
    try:
        # Use mail-id-1's email address to monitor its inbox
        result = gmail_service.users().messages().list(userId='me', labelIds=['INBOX'], q='is:unread').execute()
        messages = result.get('messages', [])
        return messages
    except HttpError as e:
        print(f"Error fetching unread emails from mail-id-1: {e}")
        return []

# Block 3: Send Acknowledgment Reply Function
# This function sends an acknowledgment reply from mail-id-2 to the sender within the same thread.
def send_acknowledgment_reply(gmail_service, message):
    """Send an acknowledgment reply from mail-id-2 to the sender within the same thread."""
    msg_id = message['id']
    try:
        full_msg = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    except HttpError as e:
        print(f"Error retrieving email {msg_id} from mail-id-1: {e}")
        return

    # Get headers to identify the sender, subject, and threading information
    headers = full_msg['payload']['headers']
    sender_email = next((h['value'] for h in headers if h['name'] == 'From'), "").strip()
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
    thread_id = full_msg['threadId']
    message_id = next((h['value'] for h in headers if h['name'] == 'Message-ID'), None)

    if not sender_email:
        print(f"Warning: No valid sender email found for thread {thread_id}. Skipping send.")
        return

    # Create the MIME message with threading headers
    mime_msg = MIMEText(ACKNOWLEDGMENT_MESSAGE)
    mime_msg['to'] = sender_email
    mime_msg['subject'] = f"Re: {subject}"
    # Set threading headers to ensure the reply is part of the same thread
    if message_id:
        mime_msg['In-Reply-To'] = message_id
        mime_msg['References'] = message_id

    # Encode and send the message with threadId
    raw_msg = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
    body = {'raw': raw_msg, 'threadId': thread_id}
    try:
        gmail_service.users().messages().send(userId='me', body=body).execute()
        print(f"Sent threaded acknowledgment from mail-id-2 to {sender_email} for thread {thread_id}")
    except HttpError as e:
        print(f"Error sending acknowledgment for thread {thread_id}: {e}")

# Block 4: Main Function
# This is the entry point of the script. It authenticates with mail-id-2, fetches unread emails from mail-id-1,
# sends threaded acknowledgments from mail-id-2, and marks emails as read on mail-id-1.
def main():
    """Main execution loop to process unread emails on mail-id-1 and send threaded replies from mail-id-2."""
    # Authenticate with mail-id-2
    gmail_service = get_gmail_service()
    # Monitor mail-id-1's inbox (requires mail-id-1's delegation or IMAP access setup if not using same credentials)
    unread_msgs = get_unread_emails(gmail_service)
    print(f"📨 Found {len(unread_msgs)} unread emails on mail-id-1.")

    # Process each unread email
    for msg in unread_msgs:
        send_acknowledgment_reply(gmail_service, msg)
        try:
            gmail_service.users().messages().modify(userId='me', id=msg['id'], body={'removeLabelIds': ['UNREAD']}).execute()
            print(f"Marked email {msg['id']} as read on mail-id-1.")
        except HttpError as e:
            print(f"Error marking email {msg['id']} as read on mail-id-1: {e}")

if __name__ == '__main__':
    main()