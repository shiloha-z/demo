from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="allow")

    DATABASE_URL: str = "sqlite:///./data.db"
    JWT_SECRET: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours
    WORKSPACE_ROOT: str = "../workspaces"
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    ANTHROPIC_API_KEY: str = ""
    OPENCODE_SERVER_URL: str = "http://localhost:36000"
    # Executor limits are intentionally bounded: tasks queue instead of
    # exhausting the web server or the model provider's rate limit.
    AGENT_MAX_CONCURRENCY: int = 4
    MERGE_MAX_CONCURRENCY: int = 2
    MERGE_TEST_COMMAND: str = ""
    MERGE_TEST_TIMEOUT_SECONDS: int = 300


settings = Settings()
