import os.path
import base64
import json
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

@mcp.tool()
def get_email_content(email_id: str) -> str:
    """
    Get the full content of a specific email by ID.
    
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
        
        # Extract body
        body = ""
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    if 'data' in part['body']:
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                        break
                elif part['mimeType'] == 'text/html' and not body:
                    if 'data' in part['body']:
                        html_body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                        soup = BeautifulSoup(html_body, 'html.parser')
                        body = soup.get_text()
        elif 'body' in payload and 'data' in payload['body']:
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
        
        return f"""Email ID: {email_id}
From: {sender}
To: {to}
Date: {date}
Subject: {subject}

--- Body ---
{body}"""
    
    except Exception as e:
        return f"Error fetching email {email_id}: {str(e)}"

@mcp.tool()
def get_swiggy_orders(start_date: str = None, end_date: str = None, limit: int = 10) -> str:
    """
    Fetch and parse Swiggy order receipts from Gmail.
    
    Args:
        start_date: Filter orders after this date (inclusive).
        end_date: Filter orders before this date (exclusive).
        limit: Maximum number of orders to return.
    """
    service = get_gmail_service()
    # Swiggy order emails usually come from 'no-reply@swiggy.in' with subject containing 'Order'
    query_parts = ['from:no-reply@swiggy.in', 'subject:"Order delivered"']
    
    if start_date:
        dt = dateparser.parse(start_date)
        if dt:
            query_parts.append(f"after:{dt.strftime('%Y/%m/%d')}")
            
    if end_date:
        dt = dateparser.parse(end_date)
        if dt:
            query_parts.append(f"before:{dt.strftime('%Y/%m/%d')}")
            
    query = " ".join(query_parts)
    
    results = service.users().messages().list(userId='me', q=query, maxResults=limit).execute()
    messages = results.get('messages', [])

    if not messages:
        return "No Swiggy orders found."

    orders = []
    for message in messages:
        try:
            msg = service.users().messages().get(userId='me', id=message['id']).execute()
            payload = msg['payload']
            
            # Get HTML body
            body = ""
            if 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/html':
                        data = part['body']['data']
                        body = base64.urlsafe_b64decode(data).decode()
                        break
            elif 'body' in payload and 'data' in payload['body']:
                data = payload['body']['data']
                body = base64.urlsafe_b64decode(data).decode()

            if body:
                soup = BeautifulSoup(body, 'html.parser')
                # Basic parsing logic - this will need to be refined based on actual email structure
                # This is a placeholder for the parsing logic
                text_content = soup.get_text()
                
                # Extract date from headers
                headers = msg['payload']['headers']
                date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
                
                orders.append(f"Order ID: {message['id']} | Date: {date_str} | Content Preview: {text_content[:100]}...")
        except Exception as e:
            orders.append(f"Error parsing message {message['id']}: {str(e)}")

    return "\n".join(orders)

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
                            "description": "Get the full content of a specific email by ID.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "email_id": {"type": "string", "description": "The Gmail message ID (from search_emails results)."}
                                },
                                "required": ["email_id"]
                            }
                        },
                        {
                            "name": "get_swiggy_orders",
                            "description": "Fetch and parse Swiggy order receipts from Gmail.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "start_date": {"type": "string", "description": "Filter orders after this date (inclusive)."},
                                    "end_date": {"type": "string", "description": "Filter orders before this date (exclusive)."},
                                    "limit": {"type": "integer", "description": "Maximum number of orders to return."}
                                }
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
            elif tool_name == "get_swiggy_orders":
                result = get_swiggy_orders(**arguments)
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
