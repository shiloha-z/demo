"""银行转账服务演示项目种子脚本 — 场景化核心。

一键创建一个"银行转账服务"演示项目，workspace 中预置含多个安全漏洞
的银行转账服务代码样本。这些漏洞正好能被平台的质量门禁（密钥扫描、
银行禁止项、静态分析）和银行安全审查技能包检出，形成完整的演示闭环。

预设风险点（5 类，覆盖文档要求的转账/账户/权限场景）：
  1. 越权访问：查询接口未校验账户归属，可遍历他人账户
  2. 敏感日志：日志中明文记录卡号、手机号、密码
  3. SQL 注入：查询使用字符串拼接
  4. 硬编码密钥：API key、数据库密码硬编码在源码中
  5. 缺少事务：转账扣款与入账未在同一事务内

用法：
  python -m backend.scripts.seed_demo_project --owner admin
  python -m backend.scripts.seed_demo_project --owner admin --force

演示流程参见生成的 DEMO_GUIDE.md。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 预设风险点代码样本 — 一个"处处是坑"的银行转账服务
DEMO_FILES = {
    "README.md": """# 银行转账服务（演示用 — 含预设安全漏洞）

> ⚠️ 本项目为 AgentCollab 答辩演示专用，代码中**故意**包含多个安全漏洞，
> 用于展示平台的质量门禁、风险评分和银行安全审查能力。
> **切勿用于生产环境。**

## 模块说明

- `transfer_service.py` — 转账服务（缺少事务、SQL 注入、硬编码密钥）
- `account_service.py` — 账户查询服务（越权访问、敏感日志）
- `auth_service.py` — 认证服务（硬编码密钥、弱密码哈希）
- `config.py` — 配置（硬编码数据库密码、API key）
- `requirements.txt` — 依赖

## 预设风险点

| 编号 | 类型 | 位置 | 说明 |
|------|------|------|------|
| 1 | 越权访问 | account_service.py:get_account | 未校验账户归属 |
| 2 | 敏感日志 | account_service.py:log_transaction | 明文记录卡号 |
| 3 | SQL 注入 | transfer_service.py:get_balance | 字符串拼接 SQL |
| 4 | 硬编码密钥 | config.py / auth_service.py | API key、DB 密码 |
| 5 | 缺少事务 | transfer_service.py:transfer | 扣款入账未原子化 |
""",

    "config.py": '''"""应用配置 — ⚠️ 含硬编码密钥（预设漏洞 #4）"""

# 数据库配置（硬编码密码 — 质量门禁密钥扫描应检出）
DATABASE_URL = "mysql://root:P@ssw0rd123@10.0.0.5:3306/bank_db"
DB_PASSWORD = "P@ssw0rd123"

# 第三方支付 API Key（硬编码 — 质量门禁密钥扫描应检出）
PAYMENT_API_KEY = "sk-prod-ak7sJf8Kd2mNp9Qr4Tv6Wx1Yz3Ab5Cd7Ef9Gh"
ALIPAY_APP_SECRET = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQD"

# JWT 签名密钥（硬编码弱密钥）
JWT_SECRET = "bank_secret_123"
JWT_ALGORITHM = "HS256"

# Redis
REDIS_URL = "redis://:redis_pwd_456@10.0.0.6:6379/0"

# 日志
LOG_LEVEL = "INFO"
LOG_FILE = "/var/log/bank/transfer.log"
''',

    "auth_service.py": '''"""认证服务 — ⚠️ 含硬编码密钥和弱哈希（预设漏洞 #4）"""

import hashlib
import jwt
from config import JWT_SECRET, JWT_ALGORITHM


def hash_password(password: str) -> str:
    """密码哈希 — ⚠️ 使用 MD5（弱哈希，预设缺陷）"""
    # 不应使用 MD5，应使用 bcrypt/argon2
    return hashlib.md5(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def create_token(user_id: int, username: str) -> str:
    """创建 JWT token — 使用硬编码弱密钥"""
    payload = {"user_id": user_id, "username": username}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """验证 token — 未校验过期时间"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None
''',

    "account_service.py": '''"""账户查询服务 — ⚠️ 含越权访问和敏感日志（预设漏洞 #1, #2）"""

import logging
from config import DATABASE_URL

logger = logging.getLogger("account_service")


def get_account(account_id: int, current_user_id: int):
    """查询账户信息 — ⚠️ 越权访问漏洞（预设漏洞 #1）

    未校验 account_id 是否属于 current_user_id，攻击者可遍历任意账户。
    正确做法：WHERE owner_id = current_user_id
    """
    import pymysql
    conn = pymysql.connect(host="10.0.0.5", user="root", password="P@ssw0rd123", db="bank_db")

    # ⚠️ 越权：未校验账户归属
    sql = f"SELECT id, account_no, owner_name, balance, card_number, phone FROM accounts WHERE id = {account_id}"
    cursor = conn.cursor()
    cursor.execute(sql)
    row = cursor.fetchone()

    # ⚠️ 敏感日志：明文记录完整卡号和手机号（预设漏洞 #2）
    logger.info(f"查询账户 {account_id}，卡号={row[4]}，手机={row[5]}，余额={row[3]}")
    print(f"[DEBUG] 账户详情: {row}")  # ⚠️ 调试日志泄露完整信息

    conn.close()
    return {
        "id": row[0],
        "account_no": row[1],
        "owner_name": row[2],
        "balance": row[3],
        "card_number": row[4],   # ⚠️ 未脱敏返回完整卡号
        "phone": row[5],         # ⚠️ 未脱敏返回完整手机号
    }


def list_transactions(account_id: int, current_user_id: int):
    """查询交易明细 — ⚠️ 同样存在越权问题"""
    import pymysql
    conn = pymysql.connect(host="10.0.0.5", user="root", password="P@ssw0rd123", db="bank_db")

    # ⚠️ 越权 + SQL 拼接
    sql = f"SELECT * FROM transactions WHERE account_id = {account_id} ORDER BY created_at DESC LIMIT 100"
    cursor = conn.cursor()
    cursor.execute(sql)
    rows = cursor.fetchall()

    # ⚠️ 敏感日志
    for row in rows:
        logger.info(f"交易记录: {row}")

    conn.close()
    return rows
''',

    "transfer_service.py": '''"""转账服务 — ⚠️ 含 SQL 注入、缺少事务、硬编码密钥（预设漏洞 #3, #4, #5）"""

import logging
import pymysql
from config import DATABASE_URL, PAYMENT_API_KEY

logger = logging.getLogger("transfer_service")


def get_balance(account_id: int):
    """查询余额 — ⚠️ SQL 注入漏洞（预设漏洞 #3）

    使用字符串拼接，account_id 来自用户输入可被注入。
    正确做法：cursor.execute("... WHERE id = %s", (account_id,))
    """
    conn = pymysql.connect(host="10.0.0.5", user="root", password="P@ssw0rd123", db="bank_db")
    # ⚠️ SQL 拼接注入
    sql = "SELECT balance FROM accounts WHERE id = " + str(account_id)
    cursor = conn.cursor()
    cursor.execute(sql)
    balance = cursor.fetchone()[0]
    conn.close()
    return balance


def transfer(from_account: int, to_account: int, amount: float, current_user_id: int):
    """执行转账 — ⚠️ 缺少事务控制（预设漏洞 #5）

    扣款和入账分两条 SQL 执行，中间若崩溃会导致资金丢失。
    正确做法：在同一事务内执行，失败回滚。
    同时存在越权（未校验 from_account 归属）。
    """
    conn = pymysql.connect(host="10.0.0.5", user="root", password="P@ssw0rd123", db="bank_db")
    cursor = conn.cursor()

    # ⚠️ 未校验 from_account 是否属于 current_user_id（越权）
    # ⚠️ 未使用事务
    # 扣款
    sql1 = f"UPDATE accounts SET balance = balance - {amount} WHERE id = {from_account}"
    cursor.execute(sql1)

    # 入账（如果这里崩溃，扣款已执行但入账未完成 — 资金丢失）
    sql2 = f"UPDATE accounts SET balance = balance + {amount} WHERE id = {to_account}"
    cursor.execute(sql2)

    conn.commit()

    # ⚠️ 敏感日志：记录完整账户信息和金额
    logger.info(f"转账成功: from={from_account}, to={to_account}, amount={amount}")
    logger.info(f"支付渠道 API Key: {PAYMENT_API_KEY}")  # ⚠️ 日志泄露 API Key

    conn.close()
    return {"status": "success", "from": from_account, "to": to_account, "amount": amount}
''',

    "requirements.txt": """pymysql==1.1.0
pyjwt==2.8.0
flask==2.3.0
# 注意：以下依赖含已知 CVE（用于演示依赖漏洞扫描）
cryptography==2.8
requests==2.20.0
""",
}


def _build_demo_files() -> dict[str, str]:
    """返回演示文件清单（剔除空占位）。"""
    return {k: v for k, v in DEMO_FILES.items() if v}


def create_demo_project(owner_username: str, force: bool = False) -> dict:
    """创建银行转账服务演示项目。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from app.core.config import settings
    from app.core.database import SessionLocal, init_db
    from app.models.models import (
        User, Project, ProjectMember, ProjectRole, Agent, AgentStatus,
        Task, TaskStatus,
    )
    from app.services import git_service as git

    init_db()

    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.username == owner_username).first()
        if not owner:
            print(f"[ERROR] 用户 '{owner_username}' 不存在，请先注册。")
            sys.exit(1)

        # 检查是否已存在演示项目
        existing = db.query(Project).filter(
            Project.owner_id == owner.id,
            Project.name == "银行转账服务（演示）",
        ).first()
        if existing and not force:
            print(f"[SKIP] 演示项目已存在 (id={existing.id})，使用 --force 重建")
            return {"project_id": existing.id, "skipped": True}

        # 创建项目
        import uuid
        project_id_str = f"demo-{uuid.uuid4().hex[:8]}"
        project = Project(
            name="银行转账服务（演示）",
            description=(
                "AgentCollab 答辩演示项目。workspace 预置含 5 类安全漏洞的"
                "银行转账服务代码，用于展示质量门禁、风险评分、银行安全审查"
                "和多人投票审批的完整闭环。"
            ),
            owner_id=owner.id,
            project_id=project_id_str,
        )
        db.add(project)
        db.flush()
        db.add(ProjectMember(
            project_id=project.id, user_id=owner.id, role=ProjectRole.OWNER,
        ))

        # 创建 workspace
        workspace_root = os.path.abspath(settings.WORKSPACE_ROOT)
        os.makedirs(workspace_root, exist_ok=True)
        workspace = os.path.join(workspace_root, f"bank_transfer_demo_{project.id}")
        os.makedirs(workspace, exist_ok=True)
        project.workspace_path = workspace
        git.init_repo(workspace)

        # 写入预设风险点代码样本
        files = _build_demo_files()
        for rel_path, content in files.items():
            full_path = os.path.join(workspace, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

        # 提交初始代码
        git.commit(workspace, "init: 银行转账服务初始版本（含预设安全漏洞）")

        # 创建演示 Agent
        agent = Agent(
            name="银行安全审查 Agent",
            description="绑定银行安全编码规范技能包，负责转账/账户类代码的安全审查与改造",
            creator_id=owner.id,
            project_id=project.id,
            status=AgentStatus.READY,
            runner_type="deepseek",
            model_name="deepseek-chat",
        )
        db.add(agent)

        db.commit()

        print(f"[OK] 演示项目已创建")
        print(f"     项目 ID:    {project.id}")
        print(f"     项目名:     {project.name}")
        print(f"     workspace:  {workspace}")
        print(f"     Agent:      {agent.name} (id={agent.id})")
        print(f"     预置文件:   {len(files)} 个（含 5 类安全漏洞）")
        print()
        print("预设风险点：")
        print("  1. 越权访问  — account_service.py:get_account 未校验账户归属")
        print("  2. 敏感日志  — account_service.py 明文记录卡号/手机号")
        print("  3. SQL 注入  — transfer_service.py:get_balance 字符串拼接")
        print("  4. 硬编码密钥— config.py / auth_service.py API key/DB 密码")
        print("  5. 缺少事务  — transfer_service.py:transfer 扣款入账未原子化")
        print()
        print("下一步：在平台中创建任务「修复转账服务安全漏洞」，观察：")
        print("  - 质量门禁如何检出密钥/SQL注入/银行禁止项")
        print("  - 风险评分如何判定为高风险并要求安全复核人")
        print("  - 银行安全审查技能包如何指导 Agent 修复")

        return {"project_id": project.id, "agent_id": agent.id, "workspace": workspace}

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="创建银行转账服务演示项目")
    parser.add_argument(
        "--owner", default="admin",
        help="项目所有者用户名（须已注册，默认 admin）",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="若演示项目已存在则重建",
    )
    args = parser.parse_args()

    create_demo_project(owner_username=args.owner, force=args.force)


if __name__ == "__main__":
    main()
