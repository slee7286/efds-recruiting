"""Provider-neutral local AI handoff and conversation archive utilities."""

from __future__ import annotations

import hashlib
import json
import re
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from quant_recruiting.config import Settings, get_settings
from quant_recruiting.local_models import (
    AIConversation,
    AIConversationLink,
    AIConversationMessage,
)
from quant_recruiting.storage import get_local_session

UTC = getattr(timezone, "UTC", timezone.utc)  # noqa: UP017 - Python 3.10 compatibility
PROVIDER_URLS = {
    "chatgpt": "https://chatgpt.com/",
    "claude": "https://claude.ai/",
    "gemini": "https://gemini.google.com/",
    "custom": "",
}


def provider_url(provider: str, settings: Settings | None = None) -> str:
    del settings  # Reserved for future provider-specific settings.
    if provider not in PROVIDER_URLS:
        raise ValueError(f"unsupported AI provider: {provider}")
    env_name = f"AI_{provider.upper()}_URL"
    return str(__import__("os").environ.get(env_name) or PROVIDER_URLS[provider])


def _copy_prompt(text_value: str) -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text_value)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def open_task(
    task_id: UUID, provider: str | None = None, settings: Settings | None = None
) -> dict[str, Any]:
    config = settings or get_settings()
    selected = provider or config.ai_default_provider
    url = provider_url(selected, config)
    with get_local_session(config) as session:
        from quant_recruiting.db.models import AITask

        task = session.get(AITask, task_id)
        if task is None:
            raise LookupError(f"local AI task not found: {task_id}")
        if not task.input_manifest_path:
            raise ValueError("AI task has no local input manifest")
        manifest = Path(task.input_manifest_path)
        if not manifest.exists():
            raise FileNotFoundError(manifest)
        instructions = manifest.parent / "instructions.md"
        prompt = instructions.read_text(encoding="utf-8") if instructions.exists() else ""
        copied = _copy_prompt(prompt)
        if url:
            webbrowser.open(url)
        return {
            "task_id": str(task_id),
            "provider": selected,
            "url": url,
            "prompt_copied": copied,
            "result_path": str(manifest.parent / "output" / "result.json"),
        }


def _content_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "parts"):
            if key in value:
                return _flatten_text(value[key])
    return str(value) if value is not None else ""


def _parse_chatgpt(payload: Any) -> list[dict[str, Any]]:
    records = payload if isinstance(payload, list) else payload.get("conversations", [])
    output = []
    for item in records:
        messages = []
        mapping = item.get("mapping", {})
        for node in mapping.values():
            message = node.get("message") or {}
            role = (message.get("author") or {}).get("role")
            content = _flatten_text((message.get("content") or {}).get("parts", ""))
            if role and content:
                messages.append(
                    {"role": role, "content": content, "timestamp": message.get("create_time")}
                )
        messages.sort(key=lambda row: row.get("timestamp") or 0)
        output.append(
            {
                "external_id": item.get("conversation_id"),
                "title": item.get("title"),
                "messages": messages,
            }
        )
    return output


def _parse_generic(payload: Any) -> list[dict[str, Any]]:
    records = payload if isinstance(payload, list) else payload.get("conversations", [payload])
    output = []
    for item in records:
        raw_messages = item.get("messages") or item.get("chat_messages") or item.get("turns") or []
        messages = []
        for message in raw_messages:
            role = (
                message.get("role") or message.get("sender") or message.get("author") or "unknown"
            )
            content = _flatten_text(
                message.get("content") or message.get("text") or message.get("parts")
            )
            if content:
                messages.append(
                    {"role": str(role), "content": content, "timestamp": message.get("timestamp")}
                )
        if messages:
            output.append(
                {
                    "external_id": item.get("id") or item.get("conversation_id"),
                    "title": item.get("title"),
                    "messages": messages,
                }
            )
    return output


def _parse_markdown(path: Path) -> list[dict[str, Any]]:
    text_value = path.read_text(encoding="utf-8")
    chunks = re.split(r"\n(?=##\s+)", text_value)
    messages = []
    for chunk in chunks:
        match = re.match(r"##\s+(User|Assistant|System)\s*\n", chunk, re.IGNORECASE)
        if match:
            messages.append(
                {"role": match.group(1).lower(), "content": chunk[match.end() :].strip()}
            )
    if not messages and text_value.strip():
        messages = [{"role": "unknown", "content": text_value.strip()}]
    return [{"external_id": None, "title": path.stem, "messages": messages}] if messages else []


def _conversation_markdown(
    provider: str, conversation: AIConversation, messages: list[AIConversationMessage]
) -> str:
    lines = [
        "---",
        f"provider: {provider}",
        f"conversation_id: {conversation.id}",
        f"captured_at: {conversation.captured_at.isoformat()}",
        "---",
        "",
        f"# {conversation.title or 'Conversation'}",
        "",
    ]
    for message in messages:
        lines.extend([f"## {message.role}", "", message.content, ""])
    return "\n".join(lines)


def import_conversations(
    provider: str, path: Path, settings: Settings | None = None, *, dry_run: bool = False
) -> dict[str, int]:
    if provider not in PROVIDER_URLS:
        raise ValueError(f"unsupported AI provider: {provider}")
    files = [path] if path.is_file() else sorted(path.rglob("*.json")) + sorted(path.rglob("*.md"))
    parsed: list[tuple[Path, dict[str, Any]]] = []
    for file in files:
        raw = file.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8")) if file.suffix.lower() == ".json" else None
        except json.JSONDecodeError:
            continue
        records = (
            _parse_chatgpt(payload)
            if provider == "chatgpt" and file.name == "conversations.json"
            else (_parse_generic(payload) if payload is not None else _parse_markdown(file))
        )
        parsed.extend((file, record) for record in records)
    if dry_run:
        return {"found": len(parsed), "new": 0, "duplicates": 0, "linked": 0}
    config = settings or get_settings()
    new_count = duplicate_count = 0
    with get_local_session(config) as session:
        for source_file, record in parsed:
            raw_hash = _content_hash(source_file.read_bytes())
            existing = session.scalar(
                select(AIConversation).where(AIConversation.content_hash == raw_hash)
            )
            if existing:
                duplicate_count += 1
                continue
            conversation = AIConversation(
                provider=provider,
                external_conversation_id=record.get("external_id"),
                title=record.get("title"),
                source_method=f"{provider}_export",
                captured_at=datetime.now(UTC),
                raw_path=str(source_file.resolve()),
                content_hash=raw_hash,
                metadata_={"source_filename": source_file.name},
            )
            session.add(conversation)
            session.flush()
            messages = []
            for sequence, item in enumerate(record.get("messages", []), start=1):
                message = AIConversationMessage(
                    conversation_id=conversation.id,
                    sequence=sequence,
                    role=str(item.get("role", "unknown")),
                    content=str(item.get("content", "")),
                    metadata_={"source_timestamp": item.get("timestamp")},
                )
                session.add(message)
                messages.append(message)
            session.flush()
            archive_dir = config.local_data_dir / "conversations" / provider
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"{conversation.id}.md"
            archive_path.write_text(
                _conversation_markdown(provider, conversation, messages), encoding="utf-8"
            )
            conversation.markdown_path = str(archive_path)
            session.execute(
                text(
                    "INSERT INTO ai_conversation_fts("
                    "rowid, conversation_id, title, content) "
                    "VALUES (:rowid, :cid, :title, :content)"
                ),
                {
                    "rowid": conversation.id.int % (2**63 - 1),
                    "cid": str(conversation.id),
                    "title": conversation.title or "",
                    "content": "\n".join(item.content for item in messages),
                },
            )
            new_count += 1
    return {"found": len(parsed), "new": new_count, "duplicates": duplicate_count, "linked": 0}


def search_conversations(query: str, settings: Settings | None = None) -> list[dict[str, Any]]:
    with get_local_session(settings) as session:
        rows = session.execute(
            text(
                "SELECT conversation_id, title, content FROM ai_conversation_fts "
                "WHERE ai_conversation_fts MATCH :query LIMIT 50"
            ),
            {"query": query},
        ).mappings()
        return [dict(row) for row in rows]


def list_conversations(settings: Settings | None = None) -> list[dict[str, Any]]:
    with get_local_session(settings) as session:
        rows = session.scalars(select(AIConversation).order_by(AIConversation.captured_at.desc()))
        return [
            {
                "id": str(row.id),
                "provider": row.provider,
                "title": row.title,
                "captured_at": row.captured_at.isoformat(),
                "application_id": str(row.application_id) if row.application_id else None,
            }
            for row in rows
        ]


def show_conversation(conversation_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    with get_local_session(settings) as session:
        conversation = session.get(AIConversation, conversation_id)
        if conversation is None:
            raise LookupError(f"conversation not found: {conversation_id}")
        messages = session.scalars(
            select(AIConversationMessage)
            .where(AIConversationMessage.conversation_id == conversation_id)
            .order_by(AIConversationMessage.sequence)
        )
        return {
            "id": str(conversation.id),
            "provider": conversation.provider,
            "title": conversation.title,
            "messages": [
                {"sequence": message.sequence, "role": message.role, "content": message.content}
                for message in messages
            ],
        }


def link_conversation(
    conversation_id: UUID, entity_type: str, entity_id: str, settings: Settings | None = None
) -> None:
    with get_local_session(settings) as session:
        session.merge(
            AIConversationLink(
                conversation_id=conversation_id, entity_type=entity_type, entity_id=entity_id
            )
        )
