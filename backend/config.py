from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    secret_key: str = "change-me-before-deploying"

    org_name: str = "Bald Ridge Lodge"
    org_phone: str = ""
    org_email: str = ""
    org_fallback_contact_name: str = "the front office"
    # Who is asking — NOT a source of answers. Regulatory documents often cover
    # several provider types at once, and a standard written for a different
    # type reads exactly like one that applies. This lets the assistant notice
    # the mismatch instead of handing over the wrong rule.
    org_profile: str = ""

    # Named ASSISTANT_* rather than CLAUDE_* on purpose: pydantic-settings lets
    # a real OS environment variable win over the .env file, and CLAUDE_MODEL /
    # CLAUDE_EFFORT are generic enough that another tool on the host can set
    # them and silently reconfigure this app.
    assistant_model: str = "claude-opus-5"
    assistant_effort: str = "medium"
    assistant_max_tokens: int = 8192

    retrieval_top_k: int = 8
    retrieval_candidates: int = 30
    retrieval_min_score: float = 0.08
    chunk_tokens: int = 350
    chunk_overlap: int = 60

    session_ttl_minutes: int = 480
    require_2fa: bool = True
    # Comma-separated emails that sign in with password only. Everyone not on
    # this list must still enrol in two-factor. Keep it short — each entry is an
    # account whose password is the only thing protecting the whole library.
    twofa_exempt_emails: str = ""
    max_queries_per_hour: int = 60
    max_upload_mb: int = 25
    cors_origins: str = "http://localhost:3000"

    database_url: str = "sqlite:///./data/baldridge.db"
    # Neon. Kept separate from database_url so the SQLite file stays readable
    # during a migration, and so a stray DATABASE_URL cannot silently point
    # the SQLAlchemy layer at Postgres (it would reach for psycopg2).
    postgres_url: str = ""
    storage_dir: str = "./storage"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def twofa_exempt_list(self) -> list[str]:
        return [e.strip().lower() for e in self.twofa_exempt_emails.split(",") if e.strip()]

    def is_2fa_exempt(self, email: str) -> bool:
        return email.lower() in self.twofa_exempt_list

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    def escalation_text(self) -> str:
        """The exact wording used whenever the assistant will not answer.

        Deliberately degrades to 'ask a supervisor' rather than inventing a
        phone number when the operator hasn't configured one.
        """
        bits = []
        if self.org_phone:
            bits.append(f"call {self.org_phone}")
        if self.org_email:
            bits.append(f"email {self.org_email}")
        if bits:
            how = " or ".join(bits)
            return (
                f"Please reach out to {self.org_fallback_contact_name} at "
                f"{self.org_name} — {how} — and ask a person directly."
            )
        return (
            f"Please ask {self.org_fallback_contact_name} at {self.org_name} directly. "
            "(An administrator still needs to add the office phone number and email "
            "to this assistant's settings.)"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
