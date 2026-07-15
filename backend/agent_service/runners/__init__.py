"""Agent runner backends.

Each runner implements the BaseRunner interface for a specific agent framework:
  - CrewAIRunner: multi-agent sequential pipeline (current default)
  - ClaudeCodeRunner: Anthropic Claude Agent SDK (single powerful agent)
  - OpenCodeRunner: OpenCode HTTP API (provider-agnostic single agent)
"""

from .factory import get_runner
from .base import BaseRunner, RunResult

__all__ = ["BaseRunner", "RunResult", "get_runner"]
