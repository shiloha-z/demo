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
    # Audit trail — append-only ledger recording human actions, AI dispatch
    # intents, and their impact on the project. Defaults on; never blocks the
    # main flow (the recorder swallows its own exceptions).
    AUDIT_ENABLED: bool = True
    # Nested sub-agent decomposition limits.
    MAX_SUBTASKS: int = 8                # Planner 最多拆出的直接子节点数（超出截断）
    NESTING_MAX_DEPTH: int = 2           # 递归嵌套最大深度（防爆炸，顶层为 1）
    PLANNER_DEFAULT_ON: bool = False     # 新任务默认是否开启自动划分


settings = Settings()
