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
    # Connections per API process. Each uvicorn worker has its own pool, so workers x db_pool_max must stay
    # below Postgres max_connections (50 in compose.yaml).
    db_pool_max: int = 10

    top_k_default: int = 20
    candidate_k: int = 100
    rrf_k: int = 60
    hnsw_ef_search: int = 100
    # Description-only searches over the whole corpus drop images whose cosine similarity is below this,
    # so "con mèo" answers "no results" instead of the least-unrelated photos. Measured with app.jobs.calibrate on
    # the 90K corpus: absent subjects top out at 0.139, present ones start at 0.158.
    min_visual_score: float = 0.148
    request_deadline_ms: int = 2700
    result_cache_size: int = 512
    result_cache_enabled: bool = True

    # Optional LLM fallback for queries the rule parser cannot plan. Off when no key is set.
    anthropic_api_key: str = ""
    llm_model: str = ""
    llm_timeout_s: float = 1.2

    download_concurrency: int = 32
    download_per_host: int = 8
    download_host_rps: float = 4.0     # starting request rate per host; halves when a host answers 403/429
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
