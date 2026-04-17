"""Voice Engine — STT (Groq Whisper) + LLM (Claude) + TTS (OpenAI)"""
import io
import asyncio
import logging
from typing import Optional
from groq import Groq
from openai import OpenAI
import anthropic
from .config import GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY

log = logging.getLogger("voice_engine")

groq_client = Groq(api_key=GROQ_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

CALL_SYSTEM_PROMPT = """
Ты AI-агент который звонит от имени клиента.

ЗАДАНИЕ: {task}
ЯЗЫК: {language}
ПРЕДСТАВИТЬСЯ: {caller_name}

ПРАВИЛА:
- Говори естественно, как живой человек
- Отвечай КОРОТКО — максимум 2-3 предложения за раз
- Если не понял — переспроси
- Если попал на автоответчик — оставь краткое сообщение
- Если говорят "перезвоните" — запиши время и вежливо попрощайся
- Когда получил всю информацию — вежливо попрощайся
{required_info_block}
{restrictions_block}

Записывай все ответы собеседника.
"""


def build_system_prompt(task: str, language: str = "auto",
                        caller_name: str = None,
                        required_info: str = None,
                        restrictions: str = None) -> str:
    lang_map = {"auto": "Определи язык собеседника и отвечай на нём",
                "ru": "Говори по-русски", "en": "Speak English",
                "pt": "Fale em português"}
    lang = lang_map.get(language, language)
    name = caller_name or f"Звоню по поводу: {task[:50]}"
    ri = f"- Обязательно узнай: {required_info}" if required_info else ""
    rs = f"- НЕ соглашаться на: {restrictions}" if restrictions else ""
    return CALL_SYSTEM_PROMPT.format(
        task=task, language=lang, caller_name=name,
        required_info_block=ri, restrictions_block=rs
    )


async def transcribe(audio_bytes: bytes, filename: str = "chunk.wav") -> str:
    """STT: audio bytes -> text via Groq Whisper"""
    try:
        result = await asyncio.to_thread(
            groq_client.audio.transcriptions.create,
            model="whisper-large-v3",
            file=(filename, audio_bytes),
            language=None,  # auto-detect
        )
        text = result.text.strip()
        log.info(f"STT: {text[:80]}")
        return text
    except Exception as e:
        log.error(f"STT error: {e}")
        return ""


async def think(system_prompt: str, conversation: list[dict],
                user_text: str) -> str:
    """LLM: generate response via Claude"""
    conversation.append({"role": "user", "content": user_text})
    try:
        resp = await asyncio.to_thread(
            claude_client.messages.create,
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=system_prompt,
            messages=conversation,
        )
        reply = resp.content[0].text
        conversation.append({"role": "assistant", "content": reply})
        log.info(f"LLM: {reply[:80]}")
        return reply
    except Exception as e:
        log.error(f"LLM error: {e}")
        return "Извините, одну секунду..."


async def synthesize(text: str, voice: str = "alloy") -> bytes:
    """TTS: text -> audio bytes via OpenAI"""
    try:
        resp = await asyncio.to_thread(
            openai_client.audio.speech.create,
            model="tts-1",
            voice=voice,
            input=text,
            response_format="pcm",  # raw 16-bit PCM for FreeSWITCH
            speed=1.0,
        )
        audio = resp.content
        log.info(f"TTS: {len(audio)} bytes")
        return audio
    except Exception as e:
        log.error(f"TTS error: {e}")
        return b""


async def generate_report(task: str, transcript: str) -> str:
    """Generate structured call report"""
    try:
        resp = await asyncio.to_thread(
            claude_client.messages.create,
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": f"""
Проанализируй транскрипт телефонного звонка и создай структурированный отчёт.

ЗАДАНИЕ БЫЛО: {task}

ТРАНСКРИПТ:
{transcript}

Дай отчёт в формате:
## Результат звонка
- Статус: (успешно / частично / неудачно)
- Длительность общения: примерно

## Полученная информация
(что удалось узнать)

## Не удалось
(что не удалось узнать/сделать, если есть)

## Следующие шаги
(если нужны)
"""}]
        )
        return resp.content[0].text
    except Exception as e:
        log.error(f"Report generation error: {e}")
        return f"Ошибка генерации отчёта: {e}"
