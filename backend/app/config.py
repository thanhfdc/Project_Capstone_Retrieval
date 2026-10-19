from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=("settings_",))

    database_url: str = "postgresql://capstone:capstone@localhost:5432/capstone"
    data_dir: Path = Path("data")
    model_dir: Path = Path("models/siglip2")
    # siglip: model that is mounted from models/; hash: deterministic fake encoder for CI and tests
    encoder_backend: str = "siglip"
    embedding_dim: int = 768
    encoder_threads: int = 4

    top_k_default: int = 20
    candidate_k: int = 100
    rrf_k: int = 60
    hnsw_ef_search: int = 100
    request_deadline_ms: int = 2700
    result_cache_size: int = 512
    result_cache_enabled: bool = True

    # Optional LLM fallback for queries the rule parser cannot plan. Off when no key is set.
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5-5"
    llm_timeout_s: float = 1.2

    download_concurrency: int = 32
    download_per_host: int = 8
    download_max_bytes: int = 20 * 1024 * 1024
    thumb_size: int = 480

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
