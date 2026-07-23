"""敏感数据外发守卫。

在向外部 LLM 发送 prompt 之前对敏感信息进行识别和脱敏，避免客户数据、
凭据、私钥等通过模型调用外泄。同时提供模型 base URL 白名单校验。

识别规则（正则 + 关键词，零外部依赖）：
  - 手机号（11 位，1 开头）
  - 身份证号（18 位，末位 X）
  - 银行卡号（16-19 位连续数字）
  - 邮箱
  - API key / Access token（sk-、AKIA、Bearer 等）
  - 私钥（-----BEGIN ... PRIVATE KEY-----）
  - 疑似密码赋值（password = "..."）
  - JWT

脱敏策略：
  - 可识别的 PII（手机/身份证/卡号/邮箱）：保留首尾，中间打码
  - 私钥/凭据：整段替换为 [REDACTED:private_key] 等占位符
  - 命中但无法安全脱敏的（如 strict 模式下的私钥）：返回 block=True
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── 正则规则 ────────────────────────────────────────────────────────────

# 手机号：1 开头 11 位，前后需边界（避免匹配长数字串片段）
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# 身份证号：18 位，前 17 位数字，末位数字或 X
IDCARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

# 银行卡号：16-19 位连续数字（排除前后仍是数字的片段）
BANKCARD_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")

# 邮箱
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# API key 形态
APIKEY_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                    # OpenAI 风格
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS Access Key
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE),  # Bearer token
    re.compile(r"\b(?:access|api)[_-]?token\s*[:=]\s*[\"'][A-Za-z0-9._-]{16,}[\"']", re.IGNORECASE),
)

# 私钥
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
    re.DOTALL,
)

# 疑似密码赋值
PASSWORD_ASSIGN_RE = re.compile(
    r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*[\"'][^\"'\n]{4,}[\"']"
)

# JWT（三段式，以 ey 开头）
JWT_RE = re.compile(r"\bey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


@dataclass
class MaskReport:
    """脱敏报告。"""
    masked_count: int = 0
    blocked: bool = False
    block_reason: str = ""
    hits: list[dict] = field(default_factory=list)

    def add(self, kind: str, sample: str) -> None:
        self.masked_count += 1
        # 仅保留前 8 字符作为样本，避免报告本身泄露敏感数据
        self.hits.append({"kind": kind, "sample": sample[:8] + "***"})


def _mask_phone(match: re.Match) -> str:
    s = match.group(0)
    return s[:3] + "****" + s[-4:]


def _mask_idcard(match: re.Match) -> str:
    s = match.group(0)
    return s[:6] + "********" + s[-4:]


def _mask_bankcard(match: re.Match) -> str:
    s = match.group(0)
    return s[:6] + "*" * (len(s) - 10) + s[-4:]


def _mask_email(match: re.Match) -> str:
    s = match.group(0)
    local, _, domain = s.partition("@")
    if len(local) <= 2:
        return f"{local[0]}***@{domain}"
    return f"{local[:2]}***@{domain}"


def mask_text(text: str) -> tuple[str, MaskReport]:
    """对文本进行脱敏，返回 (脱敏后文本, 报告)。

    当 SENSITIVE_DATA_BLOCK_STRICT=True 且命中私钥等无法安全脱敏的内容时，
    报告 blocked=True，调用方应阻止发送。
    """
    report = MaskReport()
    if not text:
        return text, report

    masked = text

    # 私钥：strict 模式下阻止发送；非 strict 替换为占位符
    def _replace_private_key(match: re.Match) -> str:
        report.add("private_key", "-----BEGI")
        return "[REDACTED:private_key]"

    if PRIVATE_KEY_RE.search(masked):
        if settings.SENSITIVE_DATA_BLOCK_STRICT:
            report.blocked = True
            report.block_reason = "命中私钥内容，strict 模式下阻止发送给外部模型"
            return text, report
        masked = PRIVATE_KEY_RE.sub(_replace_private_key, masked)

    # PII 脱敏
    masked, n = PHONE_RE.subn(_mask_phone, masked)
    for _ in range(n):
        report.add("phone", "1**")

    masked, n = IDCARD_RE.subn(_mask_idcard, masked)
    for _ in range(n):
        report.add("idcard", "******")

    masked, n = BANKCARD_RE.subn(_mask_bankcard, masked)
    for _ in range(n):
        report.add("bankcard", "******")

    masked, n = EMAIL_RE.subn(_mask_email, masked)
    for _ in range(n):
        report.add("email", "**@")

    # API key / token
    for pattern in APIKEY_PATTERNS:
        def _replace_token(match: re.Match, _kind: str = "api_key") -> str:
            report.add(_kind, match.group(0)[:8])
            return f"[REDACTED:{_kind}]"
        masked = pattern.sub(_replace_token, masked)

    # 密码赋值
    def _replace_password(match: re.Match) -> str:
        report.add("password", "password=")
        return re.sub(r"[\"'][^\"'\n]{4,}[\"']", "\"***\"", match.group(0))
    masked = PASSWORD_ASSIGN_RE.sub(_replace_password, masked)

    # JWT
    def _replace_jwt(match: re.Match) -> str:
        report.add("jwt", "ey")
        return "[REDACTED:jwt]"
    masked = JWT_RE.sub(_replace_jwt, masked)

    return masked, report


def is_base_url_allowed(base_url: str) -> bool:
    """校验 LLM base URL 是否在白名单内。

    白名单为空时返回 True（仅用于开发环境）。生产环境应配置为银行内网
    模型或私有化部署地址，如：
      LLM_BASE_URL_WHITELIST=https://llm.internal.bank/,http://10.0.0.5:8000/
    """
    whitelist = settings.LLM_BASE_URL_WHITELIST.strip()
    if not whitelist:
        return True
    if not base_url:
        return False
    allowed_prefixes = [p.strip().rstrip("/") for p in whitelist.split(",") if p.strip()]
    normalized = base_url.strip().rstrip("/")
    return any(normalized.startswith(prefix) for prefix in allowed_prefixes)


def guard_prompt_for_llm(prompt: str, *, base_url: str = "") -> tuple[str, MaskReport, bool]:
    """对发往外部 LLM 的 prompt 做统一守卫。

    返回 (处理后prompt, 脱敏报告, 是否允许发送)。
    base_url 非空时同时校验白名单。
    """
    if base_url and not is_base_url_allowed(base_url):
        report = MaskReport()
        report.blocked = True
        report.block_reason = f"模型地址 {base_url} 不在白名单内"
        return prompt, report, False

    if not settings.SENSITIVE_DATA_MASK_ENABLED:
        return prompt, MaskReport(), True

    masked, report = mask_text(prompt)
    if report.blocked:
        return masked, report, False
    return masked, report, True
