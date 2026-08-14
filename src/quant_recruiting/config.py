import importlib
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import BaseModel, Field

try:
    toml_parser: Any = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    toml_parser = importlib.import_module("tomli")


def default_local_data_dir() -> Path:
    """Return an OS-appropriate private application-data directory."""
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "RecruitingAssistant"
    return Path.home() / ".recruiting-assistant"


class Settings(BaseModel):
    storage_mode: str = "local_first"
    database_url: str = Field(default="postgresql+psycopg://localhost/quant_recruiting")
    shared_database_url: str | None = None
    shared_transport: str = "api"
    shared_api_url: str | None = None
    shared_api_timeout_seconds: float = 15.0
    shared_api_max_retries: int = 2
    local_database_url: str | None = None
    local_data_dir: Path = Field(default_factory=default_local_data_dir)
    shared_enabled: bool = True
    auto_pull_shared: bool = True
    auto_push_private: bool = False
    ai_default_provider: str = "chatgpt"
    browser_headless: bool = False
    browser_slow_mo_ms: int = 0
    browser_timeout_seconds: float = 30.0
    browser_profile_dir: Path | None = None
    browser_screenshots: bool = True
    browser_redact_sensitive_screenshots: bool = True
    browser_default_mode: str = "autofill"
    browser_screenshot_retention_days: int = 30
    browser_failed_run_retention_days: int = 90
    local_host: str = "127.0.0.1"
    local_port: int = 8765
    auto_open_browser: bool = False
    offline_mode: bool = False
    secret_store: str = "auto"
    api_environment: str = "development"
    api_allowed_origins: list[str] = []
    api_allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    api_docs_enabled: bool = True
    test_database_url: str | None = None
    data_dir: Path = Path("data")
    research_dir: Path = Path("research")
    http_user_agent: str = "quant-recruiting/0.1 (+private research)"
    http_timeout_seconds: float = 30.0
    http_max_response_bytes: int = 5_000_000
    http_max_retries: int = 2
    http_per_host_delay_seconds: float = 0.5
    discovery_max_pages: int = 200
    discovery_max_depth: int = 2
    discovery_freshness_hours: int = 24
    job_freshness_hours: int = 6
    search_provider: str | None = None
    search_api_key: str | None = None
    search_endpoint: str = "https://api.search.brave.com/res/v1/web/search"
    search_daily_budget: int = 100
    search_default_limit: int = 10
    tex_engine: str = "pdflatex"
    email_sync_interval_minutes: int = 15
    email_storage_mode: str = "text_and_metadata"
    gmail_oauth_client_id: str | None = None
    gmail_oauth_client_secret: str | None = None
    gmail_oauth_client_secret_file: Path | None = None
    gmail_lookback_days: int = 60
    reminder_deadline_24h: bool = True
    reminder_deadline_3h: bool = True
    reminder_interview_24h: bool = True
    reminder_interview_1h: bool = True
    prep_daily_minutes: int = 120
    background_email_sync: bool = True
    background_shared_sync: bool = True
    background_reminders: bool = True
    background_active_job_refresh: bool = True
    background_job_alerts: bool = True
    background_interval_minutes: int = 30

    @classmethod
    def from_environment(cls) -> "Settings":
        values = {**dotenv_values(".env"), **os.environ}

        config_root = values.get("LOCAL_DATA_DIR") or str(default_local_data_dir())
        config_path = Path(config_root).expanduser() / "config.toml"
        if config_path.exists():
            with config_path.open("rb") as handle:
                local_config = toml_parser.load(handle)
            values = {
                **{
                    "LOCAL_DATA_DIR": local_config.get("storage", {}).get("local_data_dir"),
                    "SHARED_DATABASE_URL": local_config.get("shared", {}).get("database_url"),
                    "SHARED_TRANSPORT": local_config.get("shared", {}).get("transport"),
                    "SHARED_API_URL": local_config.get("shared", {}).get("api_base_url"),
                    "SHARED_ENABLED": local_config.get("shared", {}).get("enabled"),
                    "AI_DEFAULT_PROVIDER": local_config.get("ai", {}).get("default_provider"),
                    "BROWSER_HEADLESS": local_config.get("browser", {}).get("headless"),
                    "BROWSER_SLOW_MO_MS": local_config.get("browser", {}).get("slow_mo_ms"),
                    "BROWSER_TIMEOUT_SECONDS": local_config.get("browser", {}).get(
                        "timeout_seconds"
                    ),
                    "BROWSER_PROFILE_DIR": local_config.get("browser", {}).get("profile_dir"),
                    "BROWSER_SCREENSHOTS": local_config.get("browser", {}).get("screenshots"),
                    "BROWSER_REDACT_SENSITIVE_SCREENSHOTS": local_config.get("browser", {}).get(
                        "redact_sensitive_screenshots"
                    ),
                    "BROWSER_DEFAULT_MODE": local_config.get("browser", {}).get("default_mode"),
                    "BROWSER_SCREENSHOT_RETENTION_DAYS": local_config.get("browser", {}).get(
                        "screenshot_retention_days"
                    ),
                    "BROWSER_FAILED_RUN_RETENTION_DAYS": local_config.get("browser", {}).get(
                        "failed_run_retention_days"
                    ),
                    "LOCAL_HOST": local_config.get("app", {}).get("host"),
                    "LOCAL_PORT": local_config.get("app", {}).get("port"),
                    "AUTO_OPEN_BROWSER": local_config.get("app", {}).get("open_browser"),
                    "AUTO_PULL_SHARED": local_config.get("sync", {}).get("auto_pull_shared"),
                    "OFFLINE_MODE": local_config.get("sync", {}).get("offline_mode"),
                    "API_ENV": local_config.get("api", {}).get("environment"),
                    "API_ALLOWED_HOSTS": ",".join(
                        local_config.get("api", {}).get("allowed_hosts", [])
                    ),
                    "API_ALLOWED_ORIGINS": ",".join(
                        local_config.get("api", {}).get("allowed_origins", [])
                    ),
                    "API_DOCS_ENABLED": local_config.get("api", {}).get("docs_enabled"),
                    "EMAIL_SYNC_INTERVAL_MINUTES": local_config.get("email", {}).get(
                        "sync_interval_minutes"
                    ),
                    "EMAIL_STORAGE_MODE": local_config.get("email", {}).get("storage_mode"),
                    "GOOGLE_OAUTH_CLIENT_ID": local_config.get("email", {}).get(
                        "google_oauth_client_id"
                    ),
                    "GOOGLE_OAUTH_CLIENT_SECRET": local_config.get("email", {}).get(
                        "google_oauth_client_secret"
                    ),
                    "GOOGLE_OAUTH_CLIENT_SECRET_FILE": local_config.get("email", {}).get(
                        "google_oauth_client_secret_file"
                    ),
                    "GMAIL_LOOKBACK_DAYS": local_config.get("email", {}).get("lookback_days"),
                    "REMINDER_DEADLINE_24H": local_config.get("reminders", {}).get("deadline_24h"),
                    "REMINDER_DEADLINE_3H": local_config.get("reminders", {}).get("deadline_3h"),
                    "REMINDER_INTERVIEW_24H": local_config.get("reminders", {}).get(
                        "interview_24h"
                    ),
                    "REMINDER_INTERVIEW_1H": local_config.get("reminders", {}).get("interview_1h"),
                    "PREP_DAILY_MINUTES": local_config.get("prep", {}).get("daily_minutes"),
                    "BACKGROUND_EMAIL_SYNC": local_config.get("background", {}).get("email_sync"),
                    "BACKGROUND_SHARED_SYNC": local_config.get("background", {}).get("shared_sync"),
                    "BACKGROUND_REMINDERS": local_config.get("background", {}).get("reminders"),
                    "BACKGROUND_ACTIVE_JOB_REFRESH": local_config.get("background", {}).get(
                        "active_job_refresh"
                    ),
                    "BACKGROUND_JOB_ALERTS": local_config.get("background", {}).get("job_alerts"),
                    "BACKGROUND_INTERVAL_MINUTES": local_config.get("background", {}).get(
                        "interval_minutes"
                    ),
                },
                **values,
            }

        def value(name: str, default: object) -> str:
            raw = values.get(name)
            return raw if isinstance(raw, str) and raw else str(default)

        def boolean(name: str, default: bool) -> bool:
            raw = values.get(name, default)
            if isinstance(raw, bool):
                return raw
            return str(raw).lower() not in {"0", "false", "no", "off"}

        return cls(
            storage_mode=value("STORAGE_MODE", "local_first"),
            database_url=value("DATABASE_URL", cls.model_fields["database_url"].default),
            shared_database_url=values.get("SHARED_DATABASE_URL") or values.get("DATABASE_URL"),
            shared_transport=value("SHARED_TRANSPORT", "api"),
            shared_api_url=values.get("SHARED_API_URL") or None,
            shared_api_timeout_seconds=float(value("SHARED_API_TIMEOUT_SECONDS", 15)),
            shared_api_max_retries=int(value("SHARED_API_MAX_RETRIES", 2)),
            local_database_url=values.get("LOCAL_DATABASE_URL") or None,
            local_data_dir=Path(value("LOCAL_DATA_DIR", default_local_data_dir())).expanduser(),
            shared_enabled=boolean("SHARED_ENABLED", True),
            auto_pull_shared=boolean("AUTO_PULL_SHARED", True),
            auto_push_private=False,
            ai_default_provider=value("AI_DEFAULT_PROVIDER", "chatgpt"),
            browser_headless=boolean("BROWSER_HEADLESS", False),
            browser_slow_mo_ms=int(value("BROWSER_SLOW_MO_MS", 0)),
            browser_timeout_seconds=float(value("BROWSER_TIMEOUT_SECONDS", 30)),
            browser_profile_dir=(
                Path(value("BROWSER_PROFILE_DIR", "")).expanduser()
                if value("BROWSER_PROFILE_DIR", "")
                else None
            ),
            browser_screenshots=boolean("BROWSER_SCREENSHOTS", True),
            browser_redact_sensitive_screenshots=boolean(
                "BROWSER_REDACT_SENSITIVE_SCREENSHOTS", True
            ),
            browser_default_mode=value("BROWSER_DEFAULT_MODE", "autofill"),
            browser_screenshot_retention_days=int(value("BROWSER_SCREENSHOT_RETENTION_DAYS", 30)),
            browser_failed_run_retention_days=int(value("BROWSER_FAILED_RUN_RETENTION_DAYS", 90)),
            local_host=value("LOCAL_HOST", "127.0.0.1"),
            local_port=int(value("LOCAL_PORT", 8765)),
            auto_open_browser=boolean("AUTO_OPEN_BROWSER", False),
            offline_mode=boolean("OFFLINE_MODE", False),
            secret_store=value("SECRET_STORE", "auto"),
            api_environment=value("API_ENV", "development"),
            api_allowed_origins=[
                item.strip() for item in value("API_ALLOWED_ORIGINS", "").split(",") if item.strip()
            ],
            api_allowed_hosts=[
                item.strip()
                for item in value("API_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
                if item.strip()
            ],
            api_docs_enabled=boolean("API_DOCS_ENABLED", True),
            test_database_url=values.get("TEST_DATABASE_URL"),
            data_dir=Path(value("DATA_DIR", cls.model_fields["data_dir"].default)),
            research_dir=Path(value("RESEARCH_DIR", cls.model_fields["research_dir"].default)),
            http_user_agent=value("HTTP_USER_AGENT", cls.model_fields["http_user_agent"].default),
            http_timeout_seconds=float(value("HTTP_TIMEOUT_SECONDS", 30)),
            http_max_response_bytes=int(value("HTTP_MAX_RESPONSE_BYTES", 5_000_000)),
            http_max_retries=int(value("HTTP_MAX_RETRIES", 2)),
            http_per_host_delay_seconds=float(value("HTTP_PER_HOST_DELAY_SECONDS", 0.5)),
            discovery_max_pages=int(value("DISCOVERY_MAX_PAGES", 200)),
            discovery_max_depth=int(value("DISCOVERY_MAX_DEPTH", 2)),
            discovery_freshness_hours=int(value("DISCOVERY_FRESHNESS_HOURS", 24)),
            job_freshness_hours=int(value("JOB_FRESHNESS_HOURS", 6)),
            search_provider=values.get("SEARCH_PROVIDER") or None,
            search_api_key=values.get("SEARCH_API_KEY") or None,
            search_endpoint=value(
                "SEARCH_ENDPOINT", "https://api.search.brave.com/res/v1/web/search"
            ),
            search_daily_budget=int(value("SEARCH_DAILY_BUDGET", 100)),
            search_default_limit=int(value("SEARCH_DEFAULT_LIMIT", 10)),
            tex_engine=value("TEX_ENGINE", "pdflatex"),
            email_sync_interval_minutes=int(value("EMAIL_SYNC_INTERVAL_MINUTES", 15)),
            email_storage_mode=value("EMAIL_STORAGE_MODE", "text_and_metadata"),
            gmail_oauth_client_id=values.get("GOOGLE_OAUTH_CLIENT_ID") or None,
            gmail_oauth_client_secret=values.get("GOOGLE_OAUTH_CLIENT_SECRET") or None,
            gmail_oauth_client_secret_file=(
                Path(value("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "")).expanduser()
                if value("GOOGLE_OAUTH_CLIENT_SECRET_FILE", "")
                else None
            ),
            gmail_lookback_days=max(1, min(365, int(value("GMAIL_LOOKBACK_DAYS", 60)))),
            reminder_deadline_24h=boolean("REMINDER_DEADLINE_24H", True),
            reminder_deadline_3h=boolean("REMINDER_DEADLINE_3H", True),
            reminder_interview_24h=boolean("REMINDER_INTERVIEW_24H", True),
            reminder_interview_1h=boolean("REMINDER_INTERVIEW_1H", True),
            prep_daily_minutes=int(value("PREP_DAILY_MINUTES", 120)),
            background_email_sync=boolean("BACKGROUND_EMAIL_SYNC", True),
            background_shared_sync=boolean("BACKGROUND_SHARED_SYNC", True),
            background_reminders=boolean("BACKGROUND_REMINDERS", True),
            background_active_job_refresh=boolean("BACKGROUND_ACTIVE_JOB_REFRESH", True),
            background_job_alerts=boolean("BACKGROUND_JOB_ALERTS", True),
            background_interval_minutes=int(value("BACKGROUND_INTERVAL_MINUTES", 30)),
        )

    def ensure_directories(self) -> None:
        for path in (
            self.local_data_dir,
            self.local_data_dir / "profile",
            self.local_data_dir / "applications",
            self.local_data_dir / "conversations",
            self.local_data_dir / "research-cache",
            self.local_data_dir / "exports",
            self.local_data_dir / "browser-profiles",
            self.local_data_dir / "logs",
            self.local_data_dir / "cache",
            self.local_data_dir / "email" / "raw",
            self.local_data_dir / "email" / "html",
            self.local_data_dir / "cache" / "ats-fixtures",
        ):
            path.mkdir(parents=True, exist_ok=True)
        for path in (
            self.data_dir / "raw",
            self.data_dir / "normalized",
            self.data_dir / "ai_queue",
            self.data_dir / "cache",
            self.research_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings.from_environment()
    settings.ensure_directories()
    return settings
