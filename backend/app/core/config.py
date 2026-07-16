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


settings = Settings()
