# JotForm Webhook Receiver

A lightweight FastAPI application that receives, logs, and stores JotForm webhook submissions so you can inspect the raw data structure before building automations.

---

## Project Structure

```
WebHook/
├── app/
│   ├── main.py                  # FastAPI app entry point
│   ├── config.py                # Settings (loaded from .env)
│   ├── logger.py                # Console + rotating file logger
│   ├── routes/
│   │   └── webhook.py           # POST /webhook endpoint
│   └── services/
│       └── submission_service.py  # Save submissions + future integration stubs
├── data/
│   └── submissions/             # One JSON file per submission
├── logs/
│   └── webhook.log              # Rotating log file
├── .env                         # Environment variables (not committed)
├── requirements.txt
└── README.md
```

---

## Running Locally

### 1. Create a virtual environment

```powershell
cd "D:\Alexander Job\WebHook"
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Start the FastAPI server

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The server will be available at: `http://localhost:8000`

Interactive API docs: `http://localhost:8000/docs`

### 4. Test the webhook endpoint locally

Using PowerShell:

```powershell
$body = @{
    submissionID = "6123456789"
    formID       = "123456789"
    formTitle    = "Contact Form"
    rawRequest   = '{"q1_name":"John Doe","q2_email":"john@example.com","q3_message":"Hello!"}'
    pretty       = '{"Name":"John Doe","Email":"john@example.com","Message":"Hello!"}'
}
Invoke-RestMethod -Uri "http://localhost:8000/webhook" -Method POST -Body $body
```

Using curl (Git Bash or WSL):

```bash
curl -X POST http://localhost:8000/webhook \
  -d "submissionID=6123456789" \
  -d "formID=123456789" \
  -d "formTitle=Contact Form" \
  --data-urlencode 'rawRequest={"q1_name":"John Doe","q2_email":"john@example.com"}' \
  --data-urlencode 'pretty={"Name":"John Doe","Email":"john@example.com"}'
```

---

## Exposing with Cloudflare Tunnel (Quick Tunnel)

A Cloudflare Quick Tunnel gives you a public HTTPS URL with no account needed — perfect for testing JotForm webhooks.

### 1. Install Cloudflared on Windows

**Option A — Winget (recommended):**
```powershell
winget install --id Cloudflare.cloudflared
```

**Option B — Direct download:**

Download `cloudflared-windows-amd64.exe` from the [Cloudflare releases page](https://github.com/cloudflare/cloudflared/releases/latest), rename it to `cloudflared.exe`, and place it somewhere on your PATH (e.g. `C:\Windows\System32\`).

Verify installation:
```powershell
cloudflared --version
```

### 2. Start the FastAPI server (keep this terminal open)

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Start the Cloudflare Quick Tunnel (new terminal)

```powershell
cloudflared tunnel --url http://localhost:8000
```

After a few seconds you will see output similar to:

```
2024-01-15T10:23:45Z INF +--------------------------------------------------------------------------------------------+
2024-01-15T10:23:45Z INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
2024-01-15T10:23:45Z INF |  https://random-words-here.trycloudflare.com                                               |
2024-01-15T10:23:45Z INF +--------------------------------------------------------------------------------------------+
```

### 4. Copy your public webhook URL

Your webhook URL will be:
```
https://random-words-here.trycloudflare.com/webhook
```

> The URL changes every time you restart `cloudflared`. For a stable URL you need a free Cloudflare account and a named tunnel.

### 5. Configure JotForm

1. Open your form in JotForm.
2. Go to **Settings → Integrations → WebHooks**.
3. Paste your webhook URL: `https://random-words-here.trycloudflare.com/webhook`
4. Click **Complete Integration**.
5. Submit a test entry — watch the FastAPI terminal for the incoming data.

---

## Sample JotForm Webhook Payload

JotForm sends a `POST` request with `application/x-www-form-urlencoded` body. The key fields are:

| Field         | Description                                          |
|---------------|------------------------------------------------------|
| `submissionID`| Unique ID for this submission                        |
| `formID`      | Your JotForm form ID                                 |
| `formTitle`   | Name of the form                                     |
| `rawRequest`  | JSON string with all field values (keyed by question ID) |
| `pretty`      | Human-readable version of field values               |
| `ip`          | Submitter IP address                                 |
| `username`    | Your JotForm username                                |

### Example raw payload (as received)

```
submissionID=6123456789012345678
&formID=123456789
&formTitle=Job Application
&ip=203.0.113.42
&username=yourjotformaccount
&rawRequest={"q3_fullName":"Jane Smith","q5_email":"jane@example.com","q7_phone":{"area":"555","phone":"0100"},"q9_position":"Developer"}
&pretty={"Full Name":"Jane Smith","Email":"jane@example.com","Phone":"555-0100","Position":"Developer"}
```

### How it is saved to disk

Each submission is stored in `data/submissions/` as a timestamped JSON file:

**Filename:** `20240115_102345_6123456789012345678.json`

```json
{
  "received_at": "2024-01-15T10:23:45.123456+00:00",
  "submission_id": "6123456789012345678",
  "payload": {
    "submissionID": "6123456789012345678",
    "formID": "123456789",
    "formTitle": "Job Application",
    "ip": "203.0.113.42",
    "username": "yourjotformaccount",
    "rawRequest": {
      "q3_fullName": "Jane Smith",
      "q5_email": "jane@example.com",
      "q7_phone": { "area": "555", "phone": "0100" },
      "q9_position": "Developer"
    },
    "pretty": "{\"Full Name\":\"Jane Smith\",\"Email\":\"jane@example.com\"}"
  }
}
```

---

## API Endpoints

| Method | Path       | Description                          |
|--------|------------|--------------------------------------|
| GET    | `/`        | Health check — returns app info      |
| GET    | `/health`  | Simple health check                  |
| GET    | `/docs`    | Swagger UI (interactive API docs)    |
| POST   | `/webhook` | Receives JotForm webhook submissions |

---

## Future Integrations

The following stubs exist in [`app/services/submission_service.py`](app/services/submission_service.py) and are ready to implement:

| Integration     | Stub function          | Env variable                     |
|-----------------|------------------------|----------------------------------|
| HubSpot CRM     | `push_to_hubspot()`    | `HUBSPOT_API_KEY`                |
| OpenAI / NVIDIA | `enrich_with_ai()`     | `OPENAI_API_KEY` / `NVIDIA_API_KEY` |
| Google Drive    | `upload_to_google_drive()` | `GOOGLE_DRIVE_CREDENTIALS_PATH` |

To activate an integration, fill in the relevant key in `.env` and implement the stub function.

---

## Logs

- **Console:** Live output in the terminal running uvicorn.
- **File:** `logs/webhook.log` — rotating, max 5 MB per file, 3 backups kept.

To tail the log file in PowerShell:

```powershell
Get-Content logs\webhook.log -Wait -Tail 50
```
