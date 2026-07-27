"""Security scanner for imported skill prompt content.

Scans skill text for dangerous patterns before the skill is saved to the
local library.  The scan runs synchronously during import so the user gets
immediate feedback.

Checks performed:
  - Dangerous shell commands  (rm -rf, sudo, curl | sh, …)
  - Prompt-injection attempts  (ignore previous instructions, system override, …)
  - Hard-coded secrets         (API keys, tokens, private keys)
  - Malicious / suspicious URLs
  - Code-execution patterns    (os.system, subprocess, exec, eval …)

The result is a JSON-serialisable dict stored on the Skill row and returned
to the frontend so the user can review findings before confirming.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

# ── Rule severity ───────────────────────────────────────────────────────────
CRITICAL = "critical"   # Block import
HIGH = "high"           # Strong warning
MEDIUM = "medium"       # Advisory
LOW = "low"             # Informational

# ── Rule categories ─────────────────────────────────────────────────────────
CAT_DANGEROUS_CMD   = "dangerous_command"
CAT_PROMPT_INJECT   = "prompt_injection"
CAT_SECRET_LEAK     = "secret_leak"
CAT_MALICIOUS_URL   = "malicious_url"
CAT_CODE_EXEC       = "code_execution"


@dataclass(slots=True)
class ScanRule:
    category: str
    severity: str
    message: str
    pattern: re.Pattern[str]


def _rule(category: str, severity: str, message: str, regex: str) -> ScanRule:
    return ScanRule(category, severity, message, re.compile(regex, re.IGNORECASE | re.MULTILINE))


# ── Rule set ────────────────────────────────────────────────────────────────
RULES: list[ScanRule] = [
    # ── Dangerous shell commands ────────────────────────────────────────
    _rule(CAT_DANGEROUS_CMD, CRITICAL, "高危命令: rm -rf 递归强制删除", r"\brm\s+-rf\b"),
    _rule(CAT_DANGEROUS_CMD, CRITICAL, "高危命令: sudo 提权执行", r"\bsudo\s+"),
    _rule(CAT_DANGEROUS_CMD, CRITICAL, "高危命令: curl 管道执行 (curl | sh/bash)", r"curl\s+.*\|\s*(?:sh|bash|zsh)\b"),
    _rule(CAT_DANGEROUS_CMD, CRITICAL, "高危命令: wget 管道执行 (wget | sh)", r"wget\s+.*\|\s*(?:sh|bash)\b"),
    _rule(CAT_DANGEROUS_CMD, HIGH,     "权限放宽: chmod 777", r"\bchmod\s+.*777\b"),
    _rule(CAT_DANGEROUS_CMD, HIGH,     "权限放宽: chmod -R", r"\bchmod\s+-R\b"),
    _rule(CAT_DANGEROUS_CMD, MEDIUM,   "危险的命令替换: $(...) 或反引号", r"\$\([^)]*(?:rm|sudo|curl|wget|nc|telnet)[^)]*\)|`[^`]*(?:rm|sudo|curl|wget|nc|telnet)[^`]*`"),
    _rule(CAT_DANGEROUS_CMD, MEDIUM,   "网络连接工具: nc / netcat / telnet 出站", r"\b(?:nc|netcat|ncat|telnet)\s+"),

    # ── Prompt injection ─────────────────────────────────────────────────
    _rule(CAT_PROMPT_INJECT, CRITICAL, "提示注入: 要求忽略之前的所有指令", r"(?:ignore|disregard|forget|do\s+not\s+follow)\s+(?:all\s+)?(?:previous|prior|above|earlier|original)\s+(?:instructions?|prompts?|directives?|rules?)"),
    _rule(CAT_PROMPT_INJECT, CRITICAL, "提示注入: 试图重新定义系统角色", r"(?:you\s+are\s+now|from\s+now\s+on\s+you\s+are|your\s+new\s+role\s+is|act\s+as\s+a\s+different)"),
    _rule(CAT_PROMPT_INJECT, HIGH,     "提示注入: 试图覆盖系统提示", r"(?:override|overwrite|replace)\s+(?:the\s+)?(?:system|original|built-in)\s+(?:prompt|instruction|message)"),
    _rule(CAT_PROMPT_INJECT, HIGH,     "提示注入: 声称有紧急授权或特殊权限", r"(?:urgent\s+authorization|emergency\s+override|admin\s+bypass|security\s+override)"),
    _rule(CAT_PROMPT_INJECT, MEDIUM,   "提示注入: 试图让模型无视安全限制", r"(?:no\s+(?:ethical|safety|security)\s+(?:constraints|restrictions|limits|boundaries))"),
    _rule(CAT_PROMPT_INJECT, MEDIUM,   "提示注入: System: 伪装前缀", r"^(?:system|assistant|user|human)\s*:\s*[A-Z]"),
    _rule(CAT_PROMPT_INJECT, MEDIUM,   "提示注入: 要求输出系统提示词", r"(?:reveal|output|print|show|display|leak)\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions?|directives?)"),
    _rule(CAT_PROMPT_INJECT, LOW,      "提示注入: 伪装成新对话开始", r"^\s*<\|endoftext\|>|^\s*<\|end\|>"),

    # ── Secret leaks ────────────────────────────────────────────────────
    _rule(CAT_SECRET_LEAK, CRITICAL, "发现私钥内容", r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-----"),
    _rule(CAT_SECRET_LEAK, CRITICAL, "发现疑似 AWS Access Key", r"\bAKIA[0-9A-Z]{16}\b"),
    _rule(CAT_SECRET_LEAK, CRITICAL, "发现疑似硬编码凭据 (password/passwd/secret/api_key = ...)", r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*[\"'][^\"'\\n]{8,}[\"']"),
    _rule(CAT_SECRET_LEAK, HIGH,     "发现疑似 JWT Token", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    _rule(CAT_SECRET_LEAK, HIGH,     "发现疑似 GitHub Token", r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b"),
    _rule(CAT_SECRET_LEAK, HIGH,     "发现疑似 OpenAI / Anthropic API Key", r"\bsk-(?:ant-)?[A-Za-z0-9]{32,}\b"),
    _rule(CAT_SECRET_LEAK, MEDIUM,   "发现疑似 Generic API Key", r"(?i)\b(?:api[_-]?key|apikey|access[_-]?key)\s*[:=]\s*[\"'][A-Za-z0-9_-]{16,}[\"']"),
    _rule(CAT_SECRET_LEAK, MEDIUM,   "发现疑似内网地址 + 凭据", r"(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}.*(?:password|token|secret)"),

    # ── Malicious URLs ──────────────────────────────────────────────────
    _rule(CAT_MALICIOUS_URL, HIGH,   "可疑的 IP 地址直连 URL", r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    _rule(CAT_MALICIOUS_URL, MEDIUM, "可疑的 data: / javascript: 协议 URL", r"\b(?:data|javascript|vbscript)\s*:"),
    _rule(CAT_MALICIOUS_URL, LOW,    "URL 短链接服务", r"https?://(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl|ow\.ly|is\.gd|buff\.ly|shorte\.st)/"),

    # ── Code execution ──────────────────────────────────────────────────
    _rule(CAT_CODE_EXEC, CRITICAL, "代码执行: os.system 调用", r"\bos\.system\s*\("),
    _rule(CAT_CODE_EXEC, CRITICAL, "代码执行: subprocess 调用", r"\bsubprocess\.(?:call|run|Popen|check_call|check_output)\s*\("),
    _rule(CAT_CODE_EXEC, CRITICAL, "代码执行: exec() / eval() 调用", r"\b(?:exec|eval)\s*\("),
    _rule(CAT_CODE_EXEC, HIGH,     "代码执行: __import__ 动态导入", r"__import__\s*\("),
    _rule(CAT_CODE_EXEC, HIGH,     "代码执行: compile() 动态编译", r"\bcompile\s*\("),
    _rule(CAT_CODE_EXEC, MEDIUM,   "代码执行: 使用 importlib 动态加载", r"\bimportlib\.(?:import_module|load_module)\s*\("),
    _rule(CAT_CODE_EXEC, MEDIUM,   "代码执行: Python 内建危险函数", r"\b(?:getattr|setattr|delattr)\s*\([^)]*__[a-z]+__"),
]


@dataclass(slots=True)
class ScanFinding:
    severity: str
    category: str
    message: str
    line: int = 0
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScanResult:
    status: str            # "safe" | "warning" | "danger"
    findings: list[ScanFinding] = field(default_factory=list)
    scanned_at: str = ""

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == HIGH)

    @property
    def blocked(self) -> bool:
        """Whether the import should be blocked (critical findings present)."""
        return self.critical_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": sum(1 for f in self.findings if f.severity == MEDIUM),
            "low_count": sum(1 for f in self.findings if f.severity == LOW),
            "blocked": self.blocked,
            "scanned_at": self.scanned_at,
        }


# ── Placeholder values to suppress false-positive secrets ───────────────────
PLACEHOLDER_VALUES: frozenset[str] = frozenset({
    "", "changeme", "changeit", "password", "secret", "token", "example",
    "your_token_here", "your_password_here", "********", "<token>", "<password>",
    "none", "null", "test", "demo", "xxx", "todo",
})


def _is_secret_placeholder(value: str) -> bool:
    return value.strip().lower() in PLACEHOLDER_VALUES


# ── Public API ──────────────────────────────────────────────────────────────

def scan_skill_content(name: str, content: str) -> ScanResult:
    """Run all security rules against *content* and return a ScanResult.

    *name* is used only for context in the result — rules are applied to
    *content* line-by-line.
    """
    lines = content.splitlines()
    findings: list[ScanFinding] = []

    for rule in RULES:
        for idx, line in enumerate(lines, start=1):
            match = rule.pattern.search(line)
            if not match:
                continue
            # Suppress false-positive secrets that are obvious placeholders.
            # Only suppress when we can extract a quoted value; bare-key rules
            # (e.g. JWT, AWS key, private key) are never placeholders.
            if rule.category == CAT_SECRET_LEAK:
                inner = re.search(r"[\"']([^\"']*)[\"']", match.group(0))
                if inner:
                    value = inner.group(1).strip()
                    if _is_secret_placeholder(value):
                        continue
            snippet = line.strip()
            if len(snippet) > 120:
                snippet = snippet[:120] + "…"
            findings.append(ScanFinding(
                severity=rule.severity,
                category=rule.category,
                message=rule.message,
                line=idx,
                snippet=snippet,
            ))
            break  # one finding per rule per skill

    findings.sort(key=lambda f: (0 if f.severity == CRITICAL else 1 if f.severity == HIGH else 2, f.line))

    if any(f.severity == CRITICAL for f in findings):
        status = "danger"
    elif any(f.severity == HIGH for f in findings):
        status = "warning"
    else:
        status = "safe"

    return ScanResult(
        status=status,
        findings=findings,
        scanned_at=datetime.now(timezone.utc).isoformat(),
    )
