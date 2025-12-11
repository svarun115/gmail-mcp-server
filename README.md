# Gmail MCP Server

A Model Context Protocol (MCP) server that connects to your Gmail account to retrieve and parse email receipts from various services like Swiggy, Zomato, Uber, and more. This provides a robust alternative to using private APIs.

## Features

- **Email Search**: Search emails using Gmail query syntax with flexible filters (sender, date range, subject, etc.)
- **Full Email Content**: Retrieve complete email content including body and metadata
- **Receipt Parsing**: Specialized parsers for:
  - Swiggy orders (with detailed item breakdown, prices, dates)
  - Future support planned for Zomato, Uber, Blinkit, and more

## Prerequisites

- Python 3.8 or higher
- A Google Cloud account
- Gmail API enabled on your Google Cloud project

## Setup Guide

### Step 1: Google Cloud Console Setup

1. **Create a Google Cloud Project**
   - Go to the [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project (e.g., "Personal Assistant MCP")

2. **Enable the Gmail API**
   - Navigate to "APIs & Services" > "Library"
   - Search for "Gmail API" and click "Enable"

3. **Configure OAuth Consent Screen**
   - Go to "APIs & Services" > "OAuth consent screen"
   - Choose "External" user type (or "Internal" if you have Google Workspace)
   - Fill in required fields:
     - App name: e.g., "Gmail MCP Server"
     - User support email: your email
     - Developer contact information: your email
   - Click "Save and Continue"
   - Add the scope: `https://www.googleapis.com/auth/gmail.readonly`
   - Add your email address as a **Test User** (critical for external apps)

4. **Create OAuth 2.0 Credentials**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Application type: **Desktop app**
   - Name: "Gmail MCP Client"
   - Click "Create"
   - **Download the JSON file** and save it as `credentials.json` in the `gmail-mcp-server` directory

### Step 2: Local Installation

1. **Clone or download this repository**

2. **Navigate to the project directory**
   ```bash
   cd gmail-mcp-server
   ```

3. **Create a virtual environment**
   ```bash
   python -m venv venv
   ```

4. **Activate the virtual environment**
   - Windows:
     ```bash
     venv\Scripts\activate
     ```
   - Mac/Linux:
     ```bash
     source venv/bin/activate
     ```

5. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

6. **Copy your credentials file**
   - Ensure `credentials.json` (downloaded from Google Cloud Console) is in the root of the `gmail-mcp-server` directory
   - You can use `credentials.json.example` as a reference for the expected structure

### Step 3: First Run & Authentication

1. **Run the server for the first time**
   ```bash
   python src/server.py
   ```

2. **Authenticate with Google**
   - A browser window will automatically open
   - Sign in to your Google account
   - Grant the requested permissions (read-only Gmail access)
   - After successful authentication, a `token.json` file will be created
   - This token will be used for future runs (no need to re-authenticate)

3. **Verify the server is running**
   - You should see log output indicating the MCP server is ready

## Configuration for MCP Clients

### VS Code Configuration

Add this to your VS Code `settings.json` or MCP configuration file:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "python",
      "args": [
        "path/to/gmail-mcp-server/src/server.py"
      ],
      "cwd": "path/to/gmail-mcp-server",
      "env": {}
    }
  }
}
```

**Important**: Replace `path/to/gmail-mcp-server` with the absolute path to your installation directory.

### Claude Desktop Configuration

Add this to your Claude Desktop MCP configuration file (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gmail": {
      "command": "python",
      "args": [
        "path/to/gmail-mcp-server/src/server.py"
      ],
      "cwd": "path/to/gmail-mcp-server"
    }
  }
}
```

**Note**: Ensure the Python executable is from your virtual environment, or activate the virtual environment before launching the MCP client.

## Available Tools

### 1. `search_emails`
Search for emails with flexible filters.

**Parameters**:
- `query` (optional): General Gmail search query
- `sender` (optional): Filter by sender (e.g., "swiggy", "uber")
- `recipient` (optional): Filter by recipient
- `subject` (optional): Filter by subject line
- `start_date` (optional): Start date in common formats (e.g., "2024-01-01", "last week")
- `end_date` (optional): End date (exclusive)
- `max_results` (optional): Maximum number of emails to return (default: 10)

**Returns**: List of emails with ID, subject, sender, date, and snippet

### 2. `get_email_content`
Retrieve full content of a specific email.

**Parameters**:
- `email_id` (required): Gmail message ID from search results

**Returns**: Complete email content including body, headers, and metadata

### 3. `get_swiggy_orders`
Fetch and parse Swiggy order receipts.

**Parameters**:
- `start_date` (optional): Filter orders after this date (inclusive)
- `end_date` (optional): Filter orders before this date (exclusive)
- `limit` (optional): Maximum number of orders to return

**Returns**: Parsed order data with items, prices, dates, and order details

## Security & Privacy

- **Credentials**: Your `credentials.json` and `token.json` files contain sensitive authentication data and are excluded from version control via `.gitignore`
- **Read-Only Access**: This server only requests read-only Gmail permissions
- **Local Processing**: All email parsing happens locally on your machine
- **No Data Storage**: Email data is not stored persistently by this server

## Troubleshooting

### "credentials.json not found"
- Ensure you've downloaded the OAuth client credentials from Google Cloud Console
- Place the file in the root directory of this project
- Rename it to exactly `credentials.json`

### Authentication issues
- Delete `token.json` and re-run the server to re-authenticate
- Ensure your email is added as a Test User in the OAuth consent screen
- Check that the Gmail API is enabled in your Google Cloud project

### Import errors
- Ensure your virtual environment is activated
- Reinstall dependencies: `pip install -r requirements.txt`

### Server not connecting to VS Code/Claude
- Verify the absolute path in your MCP configuration
- Ensure Python is accessible from the command line
- Check that the `cwd` points to the correct directory
- Review logs for any startup errors

## Development

To modify or extend this server:

1. The main server logic is in `src/server.py`
2. Authentication handling is in `src/auth.py`
3. Add new receipt parsers by following the Swiggy parser pattern
4. Submit pull requests for new features or bug fixes

## License

MIT License - see LICENSE file for details

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests for:
- New receipt parsers (Zomato, Uber, Blinkit, etc.)
- Bug fixes
- Documentation improvements
- Feature enhancements
