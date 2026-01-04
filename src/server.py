import os.path
import base64
import json
import io
from typing import List, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP
from bs4 import BeautifulSoup
import dateparser
from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn
import asyncio
import pdfplumber

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

mcp = FastMCP("gmail-receipts")
app = FastAPI()

def get_gmail_service():
    """Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                raise FileNotFoundError("credentials.json not found. Please download it from Google Cloud Console.")
            
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    return service

@mcp.tool()
def search_emails(query: str = "", sender: str = None, recipient: str = None, subject: str = None, start_date: str = None, end_date: str = None, max_results: int = 10) -> str:
    """
    Search for emails in Gmail and return lightweight metadata (ID, subject, sender, date, snippet).
    Use get_email_content() to fetch full email body.
    
    Args:
        query: General search query (e.g., 'receipt').
        sender: Filter by sender (e.g., 'swiggy', 'uber'). Matches names or emails.
        recipient: Filter by recipient.
        subject: Filter by subject line.
        start_date: Start date (inclusive) in any common format (e.g., '2024-01-01', 'last week').
        end_date: End date (exclusive) in any common format.
        max_results: Maximum number of emails to return.
    """
    service = get_gmail_service()
    
    search_parts = []
    if query:
        search_parts.append(query)
    if sender:
        search_parts.append(f"from:{sender}")
    if recipient:
        search_parts.append(f"to:{recipient}")
    if subject:
        search_parts.append(f"subject:{subject}")
    
    if start_date:
        dt = dateparser.parse(start_date)
        if dt:
            search_parts.append(f"after:{dt.strftime('%Y/%m/%d')}")
            
    if end_date:
        dt = dateparser.parse(end_date)
        if dt:
            search_parts.append(f"before:{dt.strftime('%Y/%m/%d')}")
            
    final_query = " ".join(search_parts).strip()
    if not final_query:
        pass

    results = service.users().messages().list(userId='me', q=final_query, maxResults=max_results).execute()
    messages = results.get('messages', [])

    if not messages:
        return "No messages found."

    output = []
    for message in messages:
        msg = service.users().messages().get(userId='me', id=message['id'], format='metadata', metadataHeaders=['From', 'Subject', 'Date']).execute()
        headers = msg['payload']['headers']
        subject_val = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
        sender_val = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
        date_val = next((h['value'] for h in headers if h['name'] == 'Date'), 'Unknown Date')
        snippet = msg.get('snippet', '')
        output.append(f"ID: {message['id']}\nDate: {date_val}\nFrom: {sender_val}\nSubject: {subject_val}\nSnippet: {snippet}\n---")

    return "\n".join(output)

def extract_attachments_from_payload(payload: dict, attachments: list = None) -> list:
    """
    Recursively extract attachment metadata from email payload.
    Returns list of attachment info dicts.
    """
    if attachments is None:
        attachments = []
    
    # Check if this part is an attachment
    filename = payload.get('filename', '')
    if filename:
        body = payload.get('body', {})
        attachment_info = {
            'filename': filename,
            'mime_type': payload.get('mimeType', 'application/octet-stream'),
            'size': body.get('size', 0),
            'attachment_id': body.get('attachmentId', ''),
        }
        
        # Check if PDF might be password protected (we can't know for sure until we try to read it)
        if attachment_info['mime_type'] == 'application/pdf':
            attachment_info['protection'] = 'unknown (check when downloading)'
        else:
            attachment_info['protection'] = 'none'
        
        attachments.append(attachment_info)
    
    # Recursively check nested parts
    if 'parts' in payload:
        for part in payload['parts']:
            extract_attachments_from_payload(part, attachments)
    
    return attachments


def extract_body_from_payload(payload: dict) -> tuple[str, str]:
    """
    Recursively extract plain text and HTML body from email payload.
    Returns (plain_text, html_text) tuple.
    """
    plain_text = ""
    html_text = ""
    
    mime_type = payload.get('mimeType', '')
    
    # Check if this part has direct body data
    if 'body' in payload and 'data' in payload['body']:
        data = payload['body']['data']
        decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        
        if mime_type == 'text/plain':
            plain_text = decoded
        elif mime_type == 'text/html':
            html_text = decoded
    
    # Recursively check nested parts
    if 'parts' in payload:
        for part in payload['parts']:
            nested_plain, nested_html = extract_body_from_payload(part)
            if nested_plain and not plain_text:
                plain_text = nested_plain
            if nested_html and not html_text:
                html_text = nested_html
    
    return plain_text, html_text


@mcp.tool()
def get_email_content(email_id: str) -> str:
    """
    Get the full content of a specific email by ID, including attachment metadata.
    Use get_email_attachment() to download specific attachments.
    
    Args:
        email_id: The Gmail message ID (from search_emails results).
    """
    service = get_gmail_service()
    
    try:
        msg = service.users().messages().get(userId='me', id=email_id, format='full').execute()
        payload = msg['payload']
        headers = payload['headers']
        
        # Extract headers
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
        date = next((h['value'] for h in headers if h['name'] == 'Date'), 'Unknown Date')
        to = next((h['value'] for h in headers if h['name'] == 'To'), 'Unknown Recipient')
        
        # Extract body recursively
        plain_text, html_text = extract_body_from_payload(payload)
        
        # Prefer plain text, fall back to HTML converted to text
        if plain_text:
            body = plain_text
        elif html_text:
            soup = BeautifulSoup(html_text, 'html.parser')
            # Remove script and style elements
            for element in soup(['script', 'style', 'head']):
                element.decompose()
            body = soup.get_text(separator='\n', strip=True)
        else:
            # Last resort: use the snippet from the message
            body = msg.get('snippet', '(No body content available)')
        
        # Extract attachment metadata
        attachments = extract_attachments_from_payload(payload)
        
        # Format attachment info
        if attachments:
            attachment_lines = [f"\n--- Attachments ({len(attachments)}) ---"]
            for i, att in enumerate(attachments, 1):
                size_kb = att['size'] / 1024
                if size_kb >= 1024:
                    size_str = f"{size_kb/1024:.1f}MB"
                else:
                    size_str = f"{size_kb:.1f}KB"
                attachment_lines.append(
                    f"{i}. {att['filename']} | {att['mime_type']} | {size_str} | protection: {att['protection']} | ID: {att['attachment_id']}"
                )
            attachment_section = "\n".join(attachment_lines)
        else:
            attachment_section = "\n--- Attachments (0) ---\nNo attachments"
        
        return f"""Email ID: {email_id}
From: {sender}
To: {to}
Date: {date}
Subject: {subject}

--- Body ---
{body}
{attachment_section}"""
    
    except Exception as e:
        return f"Error fetching email {email_id}: {str(e)}"


@mcp.tool()
def get_email_attachment(email_id: str, attachment_id: str, password: str = None) -> str:
    """
    Download and read an email attachment. For PDFs, extracts text content.
    For other files, returns base64-encoded content.
    
    Args:
        email_id: The Gmail message ID.
        attachment_id: The attachment ID (from get_email_content results).
        password: Optional password for password-protected PDF files.
    """
    service = get_gmail_service()
    
    try:
        # Get the original message to find the filename and mime type first
        msg = service.users().messages().get(userId='me', id=email_id, format='full').execute()
        attachments = extract_attachments_from_payload(msg['payload'])
        
        # Find the matching attachment metadata
        attachment_info = None
        for att in attachments:
            if att['attachment_id'] == attachment_id:
                attachment_info = att
                break
        
        # If not found by exact match, try to find by position (fallback)
        if not attachment_info and attachments:
            # Use first attachment if only one exists
            if len(attachments) == 1:
                attachment_info = attachments[0]
                attachment_id = attachment_info['attachment_id']
        
        if not attachment_info:
            return f"Error: Attachment with ID {attachment_id} not found in email. Available attachments: {[a['filename'] for a in attachments]}"
        
        filename = attachment_info['filename']
        mime_type = attachment_info['mime_type']
        
        # Get the attachment data
        attachment = service.users().messages().attachments().get(
            userId='me',
            messageId=email_id,
            id=attachment_id
        ).execute()
        
        # Decode the attachment data
        file_data = base64.urlsafe_b64decode(attachment['data'])
        
        # Handle PDF files - extract text
        if mime_type == 'application/pdf':
            try:
                pdf_file = io.BytesIO(file_data)
                text_content = []
                
                # pdfplumber expects password as string, not bytes
                pdf_password = password if password else None
                
                with pdfplumber.open(pdf_file, password=pdf_password) as pdf:
                    for i, page in enumerate(pdf.pages, 1):
                        page_text = page.extract_text()
                        if page_text:
                            text_content.append(f"--- Page {i} ---\n{page_text}")
                
                if text_content:
                    extracted_text = "\n\n".join(text_content)
                    return f"""Attachment: {filename}
Type: {mime_type}
Size: {len(file_data)} bytes
Protection: {'password-protected' if password else 'none'}

--- Extracted Text ---
{extracted_text}"""
                else:
                    return f"""Attachment: {filename}
Type: {mime_type}
Size: {len(file_data)} bytes

Note: PDF contains no extractable text (may be image-based or scanned document)."""
                    
            except Exception as pdf_error:
                error_msg = str(pdf_error).lower()
                if 'password' in error_msg or 'encrypted' in error_msg:
                    return f"""Attachment: {filename}
Type: {mime_type}
Size: {len(file_data)} bytes
Protection: password-protected

Error: This PDF is password-protected. Please provide the password parameter to extract text."""
                else:
                    return f"""Attachment: {filename}
Type: {mime_type}
Size: {len(file_data)} bytes

Error extracting PDF text: {str(pdf_error)}

Falling back to base64 content (first 1000 chars):
{base64.b64encode(file_data).decode()[:1000]}..."""
        
        # Handle text-based files
        elif mime_type.startswith('text/') or mime_type in ['application/json', 'application/xml']:
            try:
                text_content = file_data.decode('utf-8', errors='ignore')
                return f"""Attachment: {filename}
Type: {mime_type}
Size: {len(file_data)} bytes

--- Content ---
{text_content}"""
            except:
                pass
        
        # Handle image files - return base64 for potential display
        elif mime_type.startswith('image/'):
            b64_content = base64.b64encode(file_data).decode()
            return f"""Attachment: {filename}
Type: {mime_type}
Size: {len(file_data)} bytes

--- Base64 Content (for display) ---
data:{mime_type};base64,{b64_content}"""
        
        # For other binary files, return base64 with size limit
        else:
            b64_content = base64.b64encode(file_data).decode()
            if len(b64_content) > 10000:
                return f"""Attachment: {filename}
Type: {mime_type}
Size: {len(file_data)} bytes

--- Base64 Content (truncated, first 10000 chars) ---
{b64_content[:10000]}...

Note: Full content truncated. Total base64 length: {len(b64_content)} chars"""
            else:
                return f"""Attachment: {filename}
Type: {mime_type}
Size: {len(file_data)} bytes

--- Base64 Content ---
{b64_content}"""
    
    except Exception as e:
        return f"Error fetching attachment {attachment_id} from email {email_id}: {str(e)}"

@app.post("/mcp")
async def mcp_handler(request: FastAPIRequest):
    """Handle MCP requests over HTTP"""
    try:
        body = await request.json()
        
        # Route to appropriate MCP method
        method = body.get("method")
        request_id = body.get("id")
        
        if method == "tools/list":
            # Return tool definitions manually
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [
                        {
                            "name": "search_emails",
                            "description": "Search for emails in Gmail and return lightweight metadata (ID, subject, sender, date, snippet). Use get_email_content() to fetch full email body.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string", "description": "General search query (e.g., 'receipt')."},
                                    "sender": {"type": "string", "description": "Filter by sender (e.g., 'swiggy', 'uber'). Matches names or emails."},
                                    "recipient": {"type": "string", "description": "Filter by recipient."},
                                    "subject": {"type": "string", "description": "Filter by subject line."},
                                    "start_date": {"type": "string", "description": "Start date (inclusive) in any common format (e.g., '2024-01-01', 'last week')."},
                                    "end_date": {"type": "string", "description": "End date (exclusive) in any common format."},
                                    "max_results": {"type": "integer", "description": "Maximum number of emails to return."}
                                }
                            }
                        },
                        {
                            "name": "get_email_content",
                            "description": "Get the full content of a specific email by ID, including attachment metadata. Use get_email_attachment() to download specific attachments.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "email_id": {"type": "string", "description": "The Gmail message ID (from search_emails results)."}
                                },
                                "required": ["email_id"]
                            }
                        },
                        {
                            "name": "get_email_attachment",
                            "description": "Download and read an email attachment. For PDFs, extracts text content. For other files, returns base64-encoded content.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "email_id": {"type": "string", "description": "The Gmail message ID."},
                                    "attachment_id": {"type": "string", "description": "The attachment ID (from get_email_content results)."},
                                    "password": {"type": "string", "description": "Optional password for password-protected PDF files."}
                                },
                                "required": ["email_id", "attachment_id"]
                            }
                        }
                    ]
                }
            }
        elif method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            # Call the appropriate tool
            if tool_name == "search_emails":
                result = search_emails(**arguments)
            elif tool_name == "get_email_content":
                result = get_email_content(**arguments)
            elif tool_name == "get_email_attachment":
                result = get_email_attachment(**arguments)
            else:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                })
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": result}]}
            }
        elif method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "gmail-receipts",
                        "version": "1.0.0"
                    }
                }
            }
        else:
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": body.get("id") if 'body' in dir() else None,
            "error": {"code": -32603, "message": f"Internal error: {str(e)}"}
        })

@app.get("/healthz")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}

@app.get("/mcp")
async def handle_sse(request: FastAPIRequest):
    """
    GET /mcp - Optional persistent SSE stream for server-initiated notifications.
    This is optional per MCP spec. Currently returns empty SSE stream.
    """
    async def event_generator():
        # Keep connection alive with periodic comments
        try:
            while True:
                if await request.is_disconnected():
                    break
                yield ": keepalive\n\n"
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3001))
    uvicorn.run(app, host="0.0.0.0", port=port)
