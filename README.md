# AI Caller Service

SaaS: client gives a text task -> AI makes a phone call -> talks -> reports back.

## Stack
- **Backend**: FastAPI + Python 3.12
- **STT**: Groq Whisper
- **LLM**: Claude Sonnet
- **TTS**: OpenAI TTS-1
- **Telephony**: FreeSWITCH ESL + GoIP GSM Gateway

## Run
```bash
cd /home/administrator/ai-caller
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8091
```

## API
- POST /api/calls — create call
- GET /api/calls — list calls
- GET /api/calls/{id} — call status
- GET /api/calls/{id}/transcript — transcript + report
- WS /ws/calls/{id} — live updates
