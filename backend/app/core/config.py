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
    SKILLHUB_API_KEY: str = ""
    OPENCODE_SERVER_URL: str = "http://localhost:36000"
    # Executor limits are intentionally bounded: tasks queue instead of
    # exhausting the web server or the model provider's rate limit.
    AGENT_MAX_CONCURRENCY: int = 4
    MERGE_MAX_CONCURRENCY: int = 2
    MERGE_TEST_COMMAND: str = ""
    MERGE_TEST_TIMEOUT_SECONDS: int = 300
    # HTTP diagnostics. Slow requests are logged with a correlation ID so
    # production incidents can be traced without exposing stack traces.
    SLOW_REQUEST_THRESHOLD_SECONDS: float = 2.0
    # Deterministic pre-merge quality gates. Command-based gates are
    # intentionally fail-closed: an empty required command blocks the merge.
    QUALITY_GATE_UNIT_TEST_COMMAND: str = ""
    QUALITY_GATE_STYLE_COMMAND: str = ""
    QUALITY_GATE_STATIC_SCAN_COMMAND: str = ""
    QUALITY_GATE_SECRET_SCAN_COMMAND: str = ""
    QUALITY_GATE_DEPENDENCY_AUDIT_COMMAND: str = ""
    QUALITY_GATE_COVERAGE_COMMAND: str = ""
    QUALITY_GATE_BANK_RULE_COMMAND: str = ""
    QUALITY_GATE_FORBIDDEN_PATTERNS: str = "TODO,FIXME"
    QUALITY_GATE_TIMEOUT_SECONDS: int = 300
    QUALITY_GATE_ENABLED: bool = True  # 设为 false 可跳过全部确定性门禁检查
    # Audit trail — append-only ledger recording human actions, AI dispatch
    # intents, and their impact on the project. Defaults on; never blocks the
    # main flow (the recorder swallows its own exceptions).
    AUDIT_ENABLED: bool = True
    # Nested sub-agent decomposition limits.
    MAX_SUBTASKS: int = 8                # Planner 最多拆出的直接子节点数（超出截断）
    NESTING_MAX_DEPTH: int = 2           # 递归嵌套最大深度（防爆炸，顶层为 1）
    PLANNER_DEFAULT_ON: bool = False     # 新任务默认是否开启自动划分


settings = Settings()
