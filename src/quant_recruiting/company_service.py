from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.db.models import Company, CompanyAlias, CompanyDomain
from quant_recruiting.utils import normalize_text, slugify_text


def normalized_company_name(value: str) -> str:
    return normalize_text(value).replace(" corporation", "").replace(" limited", "").strip()


def resolve_company(session: Session, value: str) -> Company:
    """Resolve a firm using exact deterministic rules; raise on ambiguity."""
    requested = value.strip()
    slug_match = session.scalar(select(Company).where(Company.slug == slugify_text(requested)))
    if slug_match:
        return slug_match
    normalized = normalized_company_name(requested)
    companies = list(session.scalars(select(Company)))
    name_matches = [
        company
        for company in companies
        if normalized_company_name(company.name) == normalized
        or (company.normalized_name and company.normalized_name == normalized)
    ]
    if len(name_matches) == 1:
        return name_matches[0]
    alias_matches = list(
        session.scalars(
            select(Company).join(CompanyAlias).where(CompanyAlias.normalized_alias == normalized)
        )
    )
    unique_aliases = {company.id: company for company in alias_matches}
    if len(unique_aliases) == 1:
        return next(iter(unique_aliases.values()))
    domain = urlsplit(requested if "://" in requested else f"https://{requested}").hostname
    if domain:
        domain = domain.lower().removeprefix("www.")
        domain_matches = list(
            session.scalars(
                select(Company).join(CompanyDomain).where(CompanyDomain.domain == domain)
            )
        )
        unique_domains = {company.id: company for company in domain_matches}
        if len(unique_domains) == 1:
            return next(iter(unique_domains.values()))
    matches = name_matches + list(unique_aliases.values())
    if len({company.id for company in matches}) > 1:
        raise ValueError(f"ambiguous company identifier: {value}")
    raise LookupError(f"company not found: {value}")


def add_company_alias(
    session: Session, company: Company, alias: str, source_id: UUID | None = None
) -> CompanyAlias:
    normalized = normalized_company_name(alias)
    existing = session.scalar(
        select(CompanyAlias).where(
            CompanyAlias.company_id == company.id,
            CompanyAlias.normalized_alias == normalized,
        )
    )
    if existing:
        return existing
    item = CompanyAlias(
        company=company,
        alias=alias.strip(),
        normalized_alias=normalized,
        source_id=source_id,
    )
    session.add(item)
    session.flush()
    return item


def add_company_domain(
    session: Session,
    company: Company,
    domain: str,
    *,
    domain_type: str = "other",
    canonical: bool = False,
    verified: bool = False,
    source_id: UUID | None = None,
) -> CompanyDomain:
    hostname = urlsplit(domain if "://" in domain else f"https://{domain}").hostname
    if not hostname:
        raise ValueError(f"invalid domain: {domain}")
    hostname = hostname.lower().removeprefix("www.")
    existing = session.scalar(
        select(CompanyDomain).where(
            CompanyDomain.company_id == company.id, CompanyDomain.domain == hostname
        )
    )
    if existing:
        existing.domain_type = domain_type
        existing.canonical = canonical
        existing.verified = verified
        return existing
    item = CompanyDomain(
        company=company,
        domain=hostname,
        domain_type=domain_type,
        canonical=canonical,
        verified=verified,
        source_id=source_id,
    )
    session.add(item)
    session.flush()
    return item
