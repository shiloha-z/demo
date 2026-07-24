"""Deterministic, fail-closed pre-merge quality gates.

The AI review and human vote decide whether a change is worth integrating.
These checks independently verify that the staged merge satisfies executable
engineering policy. Required command-based checks never silently skip: if an
administrator has not configured a command, the gate fails with a clear
remediation message.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from app.core.config import settings
from app.services import git_service as git


SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".java", ".kt", ".kts",
    ".go", ".rs", ".cs", ".c", ".cc", ".cpp", ".h", ".hpp", ".sql",
    ".sh", ".ps1", ".json", ".yaml", ".yml", ".toml", ".xml", ".properties",
}
TEXT_SUFFIXES = SOURCE_SUFFIXES | {".md", ".txt", ".env", ".ini", ".cfg"}
SKIP_PARTS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "coverage",
    "__pycache__", ".pytest_cache", ".mypy_cache",
}
SUPPRESSION_MARKERS = ("quality-gate: allow", "nosec", "pragma: allowlist secret")
MAX_SCANNED_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_CHARS = 4000

# 视为占位符而非真实凭据的明文值，密钥扫描会跳过这些内容。
SECRET_PLACEHOLDER_VALUES = frozenset({
    "", "changeme", "changeit", "password", "secret", "token", "example",
    "your_token_here", "your_password_here", "********", "<token>", "<password>",
    "none", "null", "test", "demo", "xxx", "todo",
})


@dataclass(frozen=True)
class GateModeProfile:
    """同一套检查在不同严格度下的阈值与开关。"""
    required_configuration: bool        # 未配置强制命令时是否判失败
    max_line_length: int                # 单行超长阈值（字符）
    check_trailing_whitespace: bool     # 行尾空白是否判失败
    check_forbidden_patterns: bool      # TODO/FIXME 等禁止文本是否判失败
    secret_min_value_length: int        # 密钥值最小长度，低于则视为非真实凭据
    exclude_secret_placeholders: bool   # 是否跳过占位符明文


STRICT_PROFILE = GateModeProfile(
    required_configuration=True,
    max_line_length=160,
    check_trailing_whitespace=True,
    check_forbidden_patterns=True,
    secret_min_value_length=8,
    exclude_secret_placeholders=False,
)
LENIENT_PROFILE = GateModeProfile(
    required_configuration=False,
    max_line_length=200,
    check_trailing_whitespace=False,
    check_forbidden_patterns=False,
    secret_min_value_length=16,
    exclude_secret_placeholders=True,
)


def resolve_gate_profile() -> GateModeProfile:
    mode = (settings.QUALITY_GATE_MODE or "strict").strip().lower()
    return STRICT_PROFILE if mode != "lenient" else LENIENT_PROFILE


@dataclass(slots=True)
class GateCheckResult:
    key: str
    label: str
    status: str
    required: bool
    output: str
    duration_ms: int
    command: str = ""
    findings: int = 0
    failure_scope: str = ""
    agent_actionable: bool = True

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict:
        return asdict(self)


def serialize_results(results: Iterable[GateCheckResult]) -> str:
    return json.dumps([result.to_dict() for result in results], ensure_ascii=False)


def is_agent_actionable_failure(check: dict) -> bool:
    """Classify persisted checks, including records created before this flag existed."""
    if check.get("status") != "failed":
        return False
    explicit = check.get("agent_actionable")
    if isinstance(explicit, bool):
        return explicit
    output = str(check.get("output") or "").lower()
    platform_markers = (
        "未配置", "执行环境缺少", "no module named", "command not found",
        "is not recognized as an internal or external command", "无法启动检查命令",
    )
    return not any(marker in output for marker in platform_markers)


def staged_changed_files(workspace: str) -> list[str]:
    repo = git.get_repo(workspace)
    if not repo:
        return []
    try:
        names = repo.git.diff(
            "--cached", "--name-only", "--diff-filter=ACMR"
        ).splitlines()
    except Exception:
        return []
    finally:
        repo.close()
    return sorted({name.replace("\\", "/") for name in names if name.strip()})


def _iter_changed_text_files(workspace: str, changed_files: Iterable[str]):
    root = Path(workspace).resolve()
    for relative in changed_files:
        rel_path = Path(relative)
        if any(part in SKIP_PARTS for part in rel_path.parts):
            continue
        if rel_path.suffix.lower() not in TEXT_SUFFIXES and rel_path.name != ".env":
            continue
        path = (root / rel_path).resolve()
        try:
            if not path.is_relative_to(root) or not path.is_file():
                continue
            if path.stat().st_size > MAX_SCANNED_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        yield relative.replace("\\", "/"), path, content


def _visible_lines(content: str):
    for number, line in enumerate(content.splitlines(), start=1):
        if any(marker in line.lower() for marker in SUPPRESSION_MARKERS):
            continue
        yield number, line


def _result(
    key: str,
    label: str,
    started: float,
    findings: list[str],
    success_message: str,
) -> GateCheckResult:
    duration = int((time.perf_counter() - started) * 1000)
    if findings:
        shown = findings[:50]
        remainder = len(findings) - len(shown)
        output = "\n".join(shown)
        if remainder:
            output += f"\n另有 {remainder} 项未展示"
        return GateCheckResult(
            key=key,
            label=label,
            status="failed",
            required=True,
            output=output[-MAX_OUTPUT_CHARS:],
            duration_ms=duration,
            findings=len(findings),
        )
    return GateCheckResult(
        key=key,
        label=label,
        status="passed",
        required=True,
        output=success_message,
        duration_ms=duration,
    )


def _run_command(
    workspace: str,
    *,
    key: str,
    label: str,
    command: str,
    required_configuration: bool,
) -> GateCheckResult:
    started = time.perf_counter()
    command = command.strip()
    if not command:
        if required_configuration:
            return GateCheckResult(
                key=key,
                label=label,
                status="failed",
                required=True,
                output=f"未配置 {label} 命令；严格门禁不会将未执行视为通过",
                duration_ms=int((time.perf_counter() - started) * 1000),
                failure_scope="platform",
                agent_actionable=False,
            )
        return GateCheckResult(
            key=key,
            label=label,
            status="passed",
            required=True,
            output="内置检查已通过，未配置额外扫描命令",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    try:
        executable = shlex.split(command, posix=os.name != "nt")[0].strip("\"'")
    except (ValueError, IndexError):
        executable = ""
    runtime_bin = str(Path(sys.executable).resolve().parent)
    command_path = os.pathsep.join(filter(None, (runtime_bin, os.environ.get("PATH", ""))))
    if (
        executable
        and not Path(executable).exists()
        and shutil.which(executable, path=command_path) is None
    ):
        return GateCheckResult(
            key=key,
            label=label,
            status="failed",
            required=True,
            output=f"门禁执行环境缺少命令：{executable}。请由平台管理员安装或修正门禁配置",
            duration_ms=int((time.perf_counter() - started) * 1000),
            command=command,
            findings=1,
            failure_scope="platform",
            agent_actionable=False,
        )

    timeout = max(1, int(settings.QUALITY_GATE_TIMEOUT_SECONDS))
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env["PATH"] = command_path
    scratch = tempfile.TemporaryDirectory(prefix="agentcollab-gate-")
    env["COVERAGE_FILE"] = str(Path(scratch.name) / ".coverage")
    pytest_options = env.get("PYTEST_ADDOPTS", "").strip()
    if "-p no:cacheprovider" not in pytest_options:
        env["PYTEST_ADDOPTS"] = f"{pytest_options} -p no:cacheprovider".strip()
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        output = ((completed.stdout or "") + (completed.stderr or "")).strip()
        duration = int((time.perf_counter() - started) * 1000)
        if completed.returncode:
            lowered = output.lower()
            missing_runtime = any(marker in lowered for marker in (
                "no module named",
                "command not found",
                "is not recognized as an internal or external command",
                "无法将",
            ))
            return GateCheckResult(
                key=key,
                label=label,
                status="failed",
                required=True,
                output=(
                    f"命令退出码 {completed.returncode}\n"
                    f"{output[-MAX_OUTPUT_CHARS:] or '命令未输出详细信息'}"
                ),
                duration_ms=duration,
                command=command,
                findings=1,
                failure_scope="platform" if missing_runtime else "code",
                agent_actionable=not missing_runtime,
            )
        return GateCheckResult(
            key=key,
            label=label,
            status="passed",
            required=True,
            output=output[-MAX_OUTPUT_CHARS:] or "命令执行成功",
            duration_ms=duration,
            command=command,
        )
    except subprocess.TimeoutExpired as exc:
        partial = ((exc.stdout or "") + (exc.stderr or ""))
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        return GateCheckResult(
            key=key,
            label=label,
            status="failed",
            required=True,
            output=f"检查超过 {timeout} 秒，已终止\n{partial[-MAX_OUTPUT_CHARS:]}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            command=command,
            findings=1,
            failure_scope="code",
        )
    except OSError as exc:
        return GateCheckResult(
            key=key,
            label=label,
            status="failed",
            required=True,
            output=f"无法启动检查命令：{exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            command=command,
            findings=1,
            failure_scope="platform",
            agent_actionable=False,
        )
    finally:
        scratch.cleanup()


DEPENDENCY_MANIFESTS = {
    "requirements.txt", "requirements-dev.txt", "constraints.txt",
    "pyproject.toml", "poetry.lock", "Pipfile", "Pipfile.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "go.mod", "Cargo.toml",
}


def _dependency_audit_check(workspace: str) -> GateCheckResult:
    profile = resolve_gate_profile()
    started = time.perf_counter()
    try:
        manifests = sorted(
            path.name for path in Path(workspace).iterdir()
            if path.is_file() and path.name in DEPENDENCY_MANIFESTS
        )
    except OSError as exc:
        return GateCheckResult(
            key="dependency_audit",
            label="依赖漏洞检查",
            status="failed",
            required=True,
            output=f"无法读取项目依赖清单：{exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            findings=1,
            failure_scope="platform",
            agent_actionable=False,
        )
    if not manifests:
        return GateCheckResult(
            key="dependency_audit",
            label="依赖漏洞检查",
            status="passed",
            required=True,
            output="未发现依赖清单，当前项目没有可审计的第三方依赖",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    return _run_command(
        workspace,
        key="dependency_audit",
        label="依赖漏洞检查",
        command=settings.QUALITY_GATE_DEPENDENCY_AUDIT_COMMAND,
        required_configuration=profile.required_configuration,
    )


def _style_check(workspace: str, changed_files: list[str]) -> GateCheckResult:
    profile = resolve_gate_profile()
    started = time.perf_counter()
    findings: list[str] = []
    for relative, path, content in _iter_changed_text_files(workspace, changed_files):
        for line_number, line in _visible_lines(content):
            if profile.check_trailing_whitespace and line.rstrip(" \t") != line:
                findings.append(f"{relative}:{line_number} 行尾包含多余空白")
            if len(line) > profile.max_line_length:
                findings.append(
                    f"{relative}:{line_number} 单行超过 {profile.max_line_length} 个字符"
                )
        if path.suffix.lower() == ".py":
            try:
                ast.parse(content, filename=relative)
            except SyntaxError as exc:
                findings.append(f"{relative}:{exc.lineno or 1} Python 语法错误：{exc.msg}")
        elif path.suffix.lower() == ".json":
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                findings.append(f"{relative}:{exc.lineno} JSON 格式错误：{exc.msg}")
    built_in = _result(
        "style",
        "代码格式与规范",
        started,
        findings,
        "内置格式检查通过：语法、行尾空白和超长行均符合要求",
    )
    if not built_in.passed:
        return built_in
    external = _run_command(
        workspace,
        key="style",
        label="代码格式与规范",
        command=settings.QUALITY_GATE_STYLE_COMMAND,
        required_configuration=False,
    )
    external.duration_ms += built_in.duration_ms
    if external.passed and settings.QUALITY_GATE_STYLE_COMMAND.strip():
        external.output = f"{built_in.output}\n{external.output}"
    return external


STATIC_RULES = (
    (
        re.compile(r"\bos\.system\s*\(", re.IGNORECASE),
        "发现 os.system，可能造成命令注入",
    ),
    (
        re.compile(
            r"\bsubprocess\.(?:run|Popen|call|check_output)\s*\([^)]*shell\s*=\s*True",
            re.IGNORECASE | re.DOTALL,
        ),
        "发现 shell=True，必须证明输入不可控或改用参数数组",
    ),
    (
        re.compile(r"\b(?:cursor\.)?execute\s*\(\s*f[\"']", re.IGNORECASE),
        "SQL execute 使用 f-string，可能造成 SQL 注入",
    ),
    (
        re.compile(r"\b(?:cursor\.)?execute\s*\([^\n)]*\+", re.IGNORECASE),
        "SQL execute 使用字符串拼接，可能造成 SQL 注入",
    ),
    (
        re.compile(r"\bchild_process\.(?:exec|execSync)\s*\(", re.IGNORECASE),
        "发现 child_process.exec，可能造成命令注入",
    ),
)


def _static_check(workspace: str, changed_files: list[str]) -> GateCheckResult:
    started = time.perf_counter()
    findings: list[str] = []
    for relative, _, content in _iter_changed_text_files(workspace, changed_files):
        visible = "\n".join(line for _, line in _visible_lines(content))
        for pattern, message in STATIC_RULES:
            for match in pattern.finditer(visible):
                line_number = visible.count("\n", 0, match.start()) + 1
                findings.append(f"{relative}:{line_number} {message}")
    built_in = _result(
        "static_analysis",
        "静态安全扫描",
        started,
        findings,
        "内置 SQL 注入与命令注入规则检查通过",
    )
    if not built_in.passed:
        return built_in
    external = _run_command(
        workspace,
        key="static_analysis",
        label="静态安全扫描",
        command=settings.QUALITY_GATE_STATIC_SCAN_COMMAND,
        required_configuration=False,
    )
    external.duration_ms += built_in.duration_ms
    if external.passed and settings.QUALITY_GATE_STATIC_SCAN_COMMAND.strip():
        external.output = f"{built_in.output}\n{external.output}"
    return external


SECRET_RULES = (
    (
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "发现私钥内容",
    ),
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "发现疑似 AWS Access Key",
    ),
    (
        re.compile(
            r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)"
            r"\s*[:=]\s*[\"'][^\"'\\n]{8,}[\"']"
        ),
        "发现疑似硬编码凭据",
    ),
)


def _secret_check(workspace: str, changed_files: list[str]) -> GateCheckResult:
    profile = resolve_gate_profile()
    started = time.perf_counter()
    findings: list[str] = []
    ignored_names = {".env.example", "package-lock.json", "poetry.lock", "uv.lock"}
    for relative, path, content in _iter_changed_text_files(workspace, changed_files):
        if path.name in ignored_names:
            continue
        for line_number, line in _visible_lines(content):
            for pattern, message in SECRET_RULES:
                match = pattern.search(line)
                if not match:
                    continue
                if (
                    profile.exclude_secret_placeholders
                    and "硬编码凭据" in message
                ):
                    inner = re.search(r"[\"']([^\"']*)[\"']", match.group(0))
                    value = (inner.group(1) if inner else "").strip()
                    if value.lower() in SECRET_PLACEHOLDER_VALUES:
                        continue
                    if (
                        profile.secret_min_value_length
                        and len(value) < profile.secret_min_value_length
                    ):
                        continue
                findings.append(f"{relative}:{line_number} {message}")
    built_in = _result(
        "secret_scan",
        "硬编码密钥扫描",
        started,
        findings,
        "内置私钥、访问密钥和硬编码凭据规则检查通过",
    )
    if not built_in.passed:
        return built_in
    external = _run_command(
        workspace,
        key="secret_scan",
        label="硬编码密钥扫描",
        command=settings.QUALITY_GATE_SECRET_SCAN_COMMAND,
        required_configuration=False,
    )
    external.duration_ms += built_in.duration_ms
    if external.passed and settings.QUALITY_GATE_SECRET_SCAN_COMMAND.strip():
        external.output = f"{built_in.output}\n{external.output}"
    return external


def _bank_rule_check(workspace: str, changed_files: list[str]) -> GateCheckResult:
    profile = resolve_gate_profile()
    started = time.perf_counter()
    findings: list[str] = []
    forbidden = [
        item.strip() for item in settings.QUALITY_GATE_FORBIDDEN_PATTERNS.split(",")
        if item.strip()
    ]
    forbidden_file_suffixes = {".pem", ".key", ".p12", ".pfx", ".jks"}
    forbidden_file_names = {"id_rsa", "id_ed25519", ".env"}
    for relative, path, content in _iter_changed_text_files(workspace, changed_files):
        if path.suffix.lower() in forbidden_file_suffixes or path.name.lower() in forbidden_file_names:
            findings.append(f"{relative} 禁止提交证书、私钥或真实环境配置文件")
        if not profile.check_forbidden_patterns:
            continue
        for line_number, line in _visible_lines(content):
            lowered = line.lower()
            for item in forbidden:
                if item.lower() in lowered:
                    findings.append(f"{relative}:{line_number} 命中银行内部禁止项：{item}")
    built_in = _result(
        "bank_policy",
        "银行内部禁止项",
        started,
        findings,
        "银行禁止文本及敏感文件类型检查通过",
    )
    if not built_in.passed:
        return built_in
    external = _run_command(
        workspace,
        key="bank_policy",
        label="银行内部禁止项",
        command=settings.QUALITY_GATE_BANK_RULE_COMMAND,
        required_configuration=False,
    )
    external.duration_ms += built_in.duration_ms
    if external.passed and settings.QUALITY_GATE_BANK_RULE_COMMAND.strip():
        external.output = f"{built_in.output}\n{external.output}"
    return external


def run_quality_gates(
    workspace: str,
    *,
    changed_files: list[str] | None = None,
    on_result: Callable[[GateCheckResult, list[GateCheckResult]], None] | None = None,
) -> list[GateCheckResult]:
    """Execute all seven required checks in a stable, user-facing order."""
    profile = resolve_gate_profile()
    changed_files = (
        staged_changed_files(workspace)
        if changed_files is None
        else sorted(set(changed_files))
    )
    results: list[GateCheckResult] = []

    def append(result: GateCheckResult) -> None:
        results.append(result)
        if on_result:
            on_result(result, list(results))

    unit_command = (
        settings.QUALITY_GATE_UNIT_TEST_COMMAND.strip()
        or settings.MERGE_TEST_COMMAND.strip()
    )
    append(_run_command(
        workspace,
        key="unit_tests",
        label="单元测试",
        command=unit_command,
        required_configuration=profile.required_configuration,
    ))
    append(_style_check(workspace, changed_files))
    append(_static_check(workspace, changed_files))
    append(_secret_check(workspace, changed_files))
    append(_dependency_audit_check(workspace))
    append(_run_command(
        workspace,
        key="coverage",
        label="测试覆盖率",
        command=settings.QUALITY_GATE_COVERAGE_COMMAND,
        required_configuration=profile.required_configuration,
    ))
    append(_bank_rule_check(workspace, changed_files))
    return results


def gate_passed(results: Iterable[GateCheckResult]) -> bool:
    results = list(results)
    return len(results) == 7 and all(result.passed for result in results)


def execute_and_persist(
    db,
    *,
    task,
    review,
    workspace: str,
    commit_hash: str,
    changed_files: list[str],
):
    """Run the gates on the task branch before human voting is allowed."""
    from app.api.ws import broadcast_sync
    from app.models.models import (
        AuditAction,
        AuditActorType,
        QualityGateRun,
    )
    from app.services.audit_service import record as audit_record

    attempt = db.query(QualityGateRun).filter(
        QualityGateRun.task_id == task.id
    ).count() + 1
    run = QualityGateRun(
        task_id=task.id,
        review_id=review.id,
        attempt=attempt,
        commit_hash=commit_hash,
        status="running",
        results_json="[]",
        summary="正在执行七项确定性检查",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    audit_record(
        action=AuditAction.QUALITY_GATE_START,
        actor_type=AuditActorType.SYSTEM,
        project_id=task.project_id,
        task_id=task.id,
        target_type="quality_gate",
        target_id=run.id,
        intent="AI 审查完成，开始执行人工审批前确定性检查",
        payload={"commit_hash": commit_hash},
    )
    broadcast_sync("quality_gate_update", {
        "id": run.id,
        "task_id": task.id,
        "project_id": task.project_id,
        "review_id": review.id,
        "commit_hash": commit_hash,
        "status": "running",
        "checks": [],
    })

    def persist_result(_result, current_results) -> None:
        run.results_json = serialize_results(current_results)
        db.commit()
        broadcast_sync("quality_gate_update", {
            "id": run.id,
            "task_id": task.id,
            "project_id": task.project_id,
            "review_id": review.id,
            "commit_hash": commit_hash,
            "status": "running",
            "checks": [item.to_dict() for item in current_results],
        })

    try:
        results = run_quality_gates(
            workspace,
            changed_files=changed_files,
            on_result=persist_result,
        )
    except Exception as exc:
        results = [GateCheckResult(
            key="gate_runtime",
            label="门禁执行器",
            status="failed",
            required=True,
            output=f"门禁执行异常：{exc}",
            duration_ms=0,
            findings=1,
            failure_scope="platform",
            agent_actionable=False,
        )]

    passed = gate_passed(results)
    failed_labels = [item.label for item in results if not item.passed]
    run.status = "passed" if passed else "failed"
    run.results_json = serialize_results(results)
    run.summary = (
        "七项确定性检查全部通过，可以开始人工审批"
        if passed
        else f"确定性检查未通过：{'、'.join(failed_labels)}"
    )
    run.completed_at = datetime.now(timezone.utc)
    task.merge_error = "" if passed else run.summary
    db.commit()

    audit_record(
        action=AuditAction.QUALITY_GATE_PASS if passed else AuditAction.QUALITY_GATE_FAIL,
        actor_type=AuditActorType.SYSTEM,
        project_id=task.project_id,
        task_id=task.id,
        target_type="quality_gate",
        target_id=run.id,
        intent=(
            "确定性检查全部通过，开放人工审批"
            if passed
            else "确定性检查未全部通过，禁止投通过票"
        ),
        payload={
            "commit_hash": commit_hash,
            "failed_checks": failed_labels,
        },
        impact=(
            "允许进入人工审批环节"
            if passed
            else "等待人工将失败项打回 Agent 修改"
        ),
    )
    broadcast_sync("quality_gate_update", {
        "id": run.id,
        "task_id": task.id,
        "project_id": task.project_id,
        "review_id": review.id,
        "commit_hash": commit_hash,
        "status": run.status,
        "summary": run.summary,
        "checks": [item.to_dict() for item in results],
    })
    return run
