from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_recruiting.company_service import normalized_company_name
from quant_recruiting.db.models import Company, CompanyAlias, InterviewStage, RoleFamily, Skill
from quant_recruiting.utils import slugify_text

SKILL_TREE = {
    "Probability": [
        "combinatorics",
        "conditional probability",
        "Bayes",
        "independence",
        "random variables",
        "expectation",
        "variance",
        "distributions",
        "order statistics",
        "Markov chains",
    ],
    "Statistics": ["estimation", "hypothesis testing", "regression", "MLE", "Bayesian inference"],
    "Mathematics": ["linear algebra", "calculus", "optimization"],
    "Coding": [
        "Python",
        "C++",
        "algorithms",
        "data structures",
        "complexity",
        "dynamic programming",
    ],
    "Machine Learning": [
        "regression",
        "tree models",
        "neural networks",
        "evaluation",
        "time series",
    ],
    "Trading": ["expected value", "market making", "options", "game theory", "mental arithmetic"],
    "Finance": [
        "accounting",
        "financial statements",
        "valuation",
        "DCF",
        "comparable companies",
        "precedent transactions",
        "M&A",
        "LBO",
        "corporate finance",
        "capital markets",
        "equities",
        "fixed income",
        "credit",
        "derivatives",
        "portfolio management",
        "macroeconomics",
        "microeconomics",
    ],
    "Investment Research": [
        "company analysis",
        "industry analysis",
        "investment thesis",
        "financial modelling",
        "market research",
        "due diligence",
    ],
    "Software Engineering": [
        "system design",
        "databases",
        "operating systems",
        "networking",
        "distributed systems",
        "APIs",
        "testing",
        "debugging",
        "Java",
        "JavaScript",
        "TypeScript",
    ],
    "Data and Machine Learning": [
        "machine learning",
        "deep learning",
        "statistics",
        "experimentation",
        "SQL",
        "data engineering",
        "time series",
        "NLP",
        "computer vision",
    ],
    "Professional": [
        "leadership",
        "teamwork",
        "communication",
        "conflict resolution",
        "problem solving",
        "commercial awareness",
    ],
}

ROLE_FAMILIES = {
    "Quant": [
        ("quantitative_research", "Quantitative Research"),
        ("quantitative_trading", "Quantitative Trading"),
    ],
    "Finance": [
        ("investment_banking", "Investment Banking"),
        ("sales_and_trading", "Sales and Trading"),
        ("asset_management", "Asset Management"),
        ("private_equity", "Private Equity"),
        ("venture_capital", "Venture Capital"),
        ("hedge_fund", "Hedge Fund"),
        ("equity_research", "Equity Research"),
        ("credit_research", "Credit Research"),
        ("investment_research", "Investment Research"),
        ("corporate_finance", "Corporate Finance"),
    ],
    "Engineering": [("software_engineering", "Software Engineering")],
    "Data": [
        ("machine_learning", "Machine Learning"),
        ("data_science", "Data Science"),
        ("data_engineering", "Data Engineering"),
    ],
    "Product": [("product_management", "Product Management")],
    "Consulting": [("consulting", "Consulting"), ("strategy", "Strategy")],
    "Business": [("trading", "Trading"), ("research", "Research"), ("operations", "Operations")],
    "Other": [("other", "Other")],
}

INTERVIEW_STAGES = {
    "application": "Application",
    "resume_screen": "Resume Screen",
    "online_assessment": "Online Assessment",
    "psychometric_test": "Psychometric Test",
    "coding_assessment": "Coding Assessment",
    "numerical_test": "Numerical Test",
    "case_study": "Case Study",
    "hirevue": "HireVue",
    "phone_screen": "Phone Screen",
    "recruiter_screen": "Recruiter Screen",
    "technical_interview": "Technical Interview",
    "behavioural_interview": "Behavioural Interview",
    "case_interview": "Case Interview",
    "superday": "Superday",
    "assessment_centre": "Assessment Centre",
    "final_round": "Final Round",
    "offer": "Offer",
    "rejection": "Rejection",
    "other": "Other",
}

SEED_COMPANIES = [
    "Citadel",
    "Citadel Securities",
    "Jane Street",
    "Jump Trading",
    "D. E. Shaw",
    "Five Rings",
    "Susquehanna International Group",
    "DRW",
    "Optiver",
    "IMC",
    "HRT",
    "G-Research",
    "GSA Capital",
    "Virtu Financial",
    "Wincent",
    "Da Vinci",
    "Chicago Trading Company",
    "TransMarket Group",
    "Voloridge Investment Management",
    "Castleton Commodities International",
    "EDF Trading",
]

SEED_ALIASES = {
    "citadel": ["Citadel Securities"],
    "jane-street": ["Jane Street Capital", "JS"],
    "jump-trading": ["Jump"],
    "susquehanna-international-group": ["SIG", "Susquehanna"],
    "hrt": ["Hudson River Trading"],
}


def seed_skills(session: Session) -> int:
    count = 0
    for category, names in SKILL_TREE.items():
        parent_slug = slugify_text(category)
        parent = session.scalar(select(Skill).where(Skill.slug == parent_slug))
        if parent is None:
            parent = Skill(slug=parent_slug, name=category, category=category)
            session.add(parent)
            session.flush()
            count += 1
        for name in names:
            slug = slugify_text(name)
            skill = session.scalar(select(Skill).where(Skill.slug == slug))
            if skill is None:
                session.add(Skill(slug=slug, name=name, category=category, parent_id=parent.id))
                count += 1
    session.flush()
    return count


def seed_role_families(session: Session) -> int:
    count = 0
    parents: dict[str, RoleFamily] = {}
    for category, entries in ROLE_FAMILIES.items():
        parent_slug = f"category-{slugify_text(category)}"
        parent = session.scalar(select(RoleFamily).where(RoleFamily.slug == parent_slug))
        if parent is None:
            parent = RoleFamily(slug=parent_slug, name=category, category=slugify_text(category))
            session.add(parent)
            session.flush()
            count += 1
        parents[category] = parent
        for slug, name in entries:
            role = session.scalar(select(RoleFamily).where(RoleFamily.slug == slug))
            if role is None:
                session.add(
                    RoleFamily(
                        slug=slug, name=name, category=slugify_text(category), parent_id=parent.id
                    )
                )
                count += 1
    session.flush()
    return count


def seed_interview_stages(session: Session) -> int:
    count = 0
    for slug, name in INTERVIEW_STAGES.items():
        if session.scalar(select(InterviewStage).where(InterviewStage.slug == slug)) is None:
            session.add(InterviewStage(slug=slug, name=name, category="recruiting"))
            count += 1
    session.flush()
    return count


def seed_companies(session: Session) -> int:
    count = 0
    for name in SEED_COMPANIES:
        slug = slugify_text(name)
        if session.scalar(select(Company).where(Company.slug == slug)) is None:
            session.add(
                Company(slug=slug, name=name, normalized_name=normalized_company_name(name))
            )
            count += 1
    for slug, aliases in SEED_ALIASES.items():
        company = session.scalar(select(Company).where(Company.slug == slug))
        if company is None:
            continue
        for alias in aliases:
            if (
                session.scalar(
                    select(CompanyAlias).where(
                        CompanyAlias.company_id == company.id,
                        CompanyAlias.normalized_alias == normalized_company_name(alias),
                    )
                )
                is None
            ):
                session.add(
                    CompanyAlias(
                        company=company,
                        alias=alias,
                        normalized_alias=normalized_company_name(alias),
                    )
                )
                count += 1
    session.flush()
    return count
