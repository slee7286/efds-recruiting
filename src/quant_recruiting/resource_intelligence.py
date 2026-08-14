"""Deterministic preparation-resource normalization and section support."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.db.models import Resource, ResourceSection
from quant_recruiting.utils import canonicalize_url


@dataclass(frozen=True)
class ResourceCandidate:
    title: str
    url: str
    resource_type: str
    description: str | None = None
    author: str | None = None
    publisher: str | None = None
    free: bool | None = None
    difficulty: str | None = None
    metadata: dict[str, Any] | None = None


def infer_resource_type(title: str, url: str = "") -> str:
    text = f"{title} {url}".lower()
    if "github.com" in text:
        return "github"
    if "youtube.com" in text or "youtu.be" in text:
        return "video"
    if "course" in text or "lecture" in text:
        return "course"
    if "problem" in text or "leetcode" in text:
        return "problem_bank"
    if "pdf" in text or "paper" in text:
        return "paper"
    return "website"


def normalize_resource(candidate: ResourceCandidate) -> ResourceCandidate:
    return ResourceCandidate(
        title=" ".join(candidate.title.split()),
        url=canonicalize_url(candidate.url),
        resource_type=candidate.resource_type
        or infer_resource_type(candidate.title, candidate.url),
        description=" ".join(candidate.description.split()) if candidate.description else None,
        author=candidate.author,
        publisher=candidate.publisher,
        free=candidate.free,
        difficulty=candidate.difficulty,
        metadata=candidate.metadata or {},
    )


def upsert_resource(session: Session, candidate: ResourceCandidate) -> tuple[Resource, bool]:
    normalized = normalize_resource(candidate)
    resource = session.scalar(select(Resource).where(Resource.url == normalized.url))
    created = resource is None
    if resource is None:
        resource = Resource(
            title=normalized.title,
            resource_type=normalized.resource_type,
            url=normalized.url,
            description=normalized.description,
            author=normalized.author,
            publisher=normalized.publisher,
            difficulty=normalized.difficulty,
            free=bool(normalized.free),
            metadata_=normalized.metadata or {},
        )
        session.add(resource)
    else:
        resource.title = normalized.title
        resource.description = normalized.description
        resource.metadata_ = {**resource.metadata_, **(normalized.metadata or {})}
    session.flush()
    return resource, created


def extract_sections(resource: Resource, content: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(re.finditer(r"(?m)^#{1,4}\s+(.+?)\s*$", content)):
        sections.append(
            {
                "title": match.group(1).strip(),
                "section_type": "heading",
                "order_index": index,
                "metadata": {
                    "heading_level": len(match.group(0)) - len(match.group(0).lstrip("#"))
                },
            }
        )
    return sections


def persist_sections(session: Session, resource: Resource, sections: list[dict[str, Any]]) -> int:
    created = 0
    for item in sections:
        existing = session.scalar(
            select(ResourceSection).where(
                ResourceSection.resource_id == resource.id,
                ResourceSection.order_index == item["order_index"],
            )
        )
        if existing is None:
            session.add(ResourceSection(resource=resource, **item))
            created += 1
    session.flush()
    return created
