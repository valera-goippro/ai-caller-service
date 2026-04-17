"""Call Manager — FreeSWITCH ESL via raw socket + audio bridge"""
import asyncio
import logging
import wave
import time
from datetime import datetime, timezone
from typing import Optional, Callable
from .config import FS_ESL_HOST, FS_ESL_PORT, FS_ESL_PASSWORD

log = logging.getLogger("call_manager")


class ESLClient:
    """Async FreeSWITCH Event Socket client (inbound mode)"""

    def __init__(self):
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(
                FS_ESL_HOST, FS_ESL_PORT
            )
            header = await self._read_event()
            if "auth/request" in header.get("Content-Type", ""):
                self.writer.write(f"auth {FS_ESL_PASSWORD}\n\n".encode())
                await self.writer.drain()
                resp = await self._read_event()
                if "Reply-Text" in resp and "+OK" in resp["Reply-Text"]:
                    self.connected = True
                    log.info("ESL connected")
                    return True
                else:
                    log.error(f"ESL auth failed: {resp}")
                    return False
        except Exception as e:
            log.error(f"ESL connection failed: {e}")
            return False

    async def _read_event(self) -> dict:
        headers = {}
        while True:
            line = await self.reader.readline()
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                break
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        cl = int(headers.get("Content-Length", 0))
        if cl > 0:
            body = await self.reader.readexactly(cl)
            headers["_body"] = body.decode("utf-8", errors="replace")
        return headers

    async def api(self, cmd: str) -> str:
        if not self.connected:
            if not await self.connect():
                return "ERROR: not connected"
        self.writer.write(f"api {cmd}\n\n".encode())
        await self.writer.drain()
        resp = await self._read_event()
        return resp.get("_body", resp.get("Reply-Text", ""))

    async def close(self):
        if self.writer:
            self.writer.close()
            self.connected = False


class CallSession:
    """Manages a single outbound call lifecycle"""

    def __init__(self, call_id: str, destination: str, system_prompt: str):
        self.call_id = call_id
        self.destination = destination
        self.system_prompt = system_prompt
        self.uuid: Optional[str] = None
        self.status = "pending"
        self.transcript_lines: list[dict] = []
        self.conversation: list[dict] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.esl = ESLClient()
        self._status_callbacks: list[Callable] = []

    def on_status_change(self, cb: Callable):
        self._status_callbacks.append(cb)

    def _notify(self, status: str, **kwargs):
        self.status = status
        for cb in self._status_callbacks:
            try:
                cb(status, **kwargs)
            except Exception:
                pass

    async def originate(self) -> bool:
        if not await self.esl.connect():
            log.error("Cannot connect to FreeSWITCH ESL")
            self._notify("failed", reason="ESL connection failed")
            return False

        self._notify("dialing")
        dest = self.destination
        if not dest.startswith("+"):
            dest = f"+{dest}"

        cmd = (
            f"originate "
            f"{{origination_caller_id_number=+351932442040,"
            f"originate_timeout=45,"
            f"call_timeout=120,"
            f"origination_uuid={self.call_id}}}"
            f"sofia/gateway/goip8/{dest} "
            f"&park()"
        )
        log.info(f"Originate: {cmd}")
        result = await self.esl.api(cmd)
        log.info(f"Originate result: {result[:200]}")

        if "ERR" in result.upper() or "FAIL" in result.upper():
            self._notify("failed", reason=result[:200])
            return False

        self.uuid = self.call_id
        self.start_time = time.time()
        self._notify("in_progress")
        return True

    async def play_audio(self, pcm_data: bytes):
        if not self.uuid:
            return
        wav_path = f"/tmp/ai_caller_{self.call_id}_{int(time.time()*1000)}.wav"
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm_data)
        await self.esl.api(f"uuid_broadcast {self.uuid} {wav_path} aleg")

    async def record_start(self) -> str:
        rec_path = f"/tmp/ai_caller_rec_{self.call_id}.wav"
        if self.uuid:
            await self.esl.api(f"uuid_record {self.uuid} start {rec_path}")
        return rec_path

    async def hangup(self):
        if self.uuid:
            await self.esl.api(f"uuid_kill {self.uuid}")
        self.end_time = time.time()
        self._notify("completed")

    @property
    def duration(self) -> int:
        if self.start_time:
            end = self.end_time or time.time()
            return int(end - self.start_time)
        return 0

    @property
    def full_transcript(self) -> str:
        lines = []
        for entry in self.transcript_lines:
            role = entry.get("role", "?")
            text = entry.get("text", "")
            ts = entry.get("timestamp", "")
            prefix = "AI" if role == "assistant" else "Собеседник"
            lines.append(f"[{ts}] {prefix}: {text}")
        return "\n".join(lines)

    def add_transcript(self, role: str, text: str):
        self.transcript_lines.append({
            "role": role,
            "text": text,
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S")
        })

    async def close(self):
        await self.esl.close()
