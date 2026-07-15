"""Runner factory — maps runner_type string to BaseRunner instance.

Uses lazy imports so missing SDKs only error when the backend is actually used,
not at import time.
"""

import importlib
import logging
from .base import BaseRunner

logger = logging.getLogger(__name__)

# Registry: runner_type → module_path:ClassName
REGISTRY: dict[str, str] = {
    "crewai": "agent_service.runners.crewai_runner:CrewAIRunner",
    "claude_code": "agent_service.runners.claude_runner:ClaudeCodeRunner",
    "opencode": "agent_service.runners.opencode_runner:OpenCodeRunner",
}


def get_runner(runner_type: str) -> BaseRunner:
    """Return a runner instance for the given runner_type.

    Raises ValueError if the runner_type is unknown.
    Raises ImportError if the runner's SDK is not installed (with install hint).
    """
    if runner_type not in REGISTRY:
        raise ValueError(
            f"Unknown runner type: {runner_type!r}. "
            f"Available: {list(REGISTRY)}"
        )

    module_path, class_name = REGISTRY[runner_type].split(":")
    try:
        mod = importlib.import_module(module_path)
    except ImportError as e:
        _hint = _install_hints.get(runner_type, "")
        raise ImportError(
            f"Failed to import runner for '{runner_type}'. {_hint}\n"
            f"Original error: {e}"
        ) from e

    runner_cls = getattr(mod, class_name)
    return runner_cls()


_install_hints: dict[str, str] = {
    "crewai": "Ensure `crewai` is installed: pip install crewai",
    "claude_code": "Install the Claude Agent SDK: pip install claude-agent-sdk",
    "opencode": "OpenCode requires the `opencode` CLI. Install from https://opencode.ai or use `pip install opencode-cli`",
}
