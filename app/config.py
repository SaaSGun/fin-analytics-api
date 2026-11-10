from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str = "fin-analytics-api"
    bq_dataset: str = "fin_analytics"
    bq_location: str = "US"

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
