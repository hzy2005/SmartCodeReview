from typing import Dict, Any, List
import re
from app.analyzers.common import make_issue, long_function_detector, duplicate_block_hash

SQL_PAT = re.compile(r"execute\(.*[\"'](SELECT|UPDATE|DELETE|INSERT).*[\"']\s*\+", re.I)
OS_SYSTEM = re.compile(r"os\.system\(.*\+.*\)")
RANDOM_INSECURE = re.compile(r"random\.(random|randint|choice)\(\)")

def analyze_python(code: str) -> Dict[str, Any]:
    lines = code.splitlines()

    issues: List[dict] = []
    smells: List[dict] = []
    security: List[dict] = []

    # 资源未关闭
    for i, ln in enumerate(lines, start=1):
        if "open(" in ln and "with " not in ln:
            issues.append(make_issue("BUG.FILE_NOT_CLOSED", "medium", "文件打开未使用 with 上下文管理，可能导致资源泄露", i, i, ln.strip()))

    # 坏味道
    smells += long_function_detector(lines, threshold=50)
    smells += duplicate_block_hash(lines, window=6)

    # 安全
    for i, ln in enumerate(lines, start=1):
        if SQL_PAT.search(ln):
            security.append(make_issue("SEC.SQLI", "high", "可能的字符串拼接 SQL 注入风险，建议使用参数化查询", i, i, ln.strip()))
        if OS_SYSTEM.search(ln):
            security.append(make_issue("SEC.CMD_INJECT", "high", "可能的命令注入风险，避免字符串拼接系统命令", i, i, ln.strip()))
        if RANDOM_INSECURE.search(ln):
            security.append(make_issue("SEC.WEAK_RNG", "low", "安全用途请改用 secrets 模块生成随机数", i, i, ln.strip()))

    return {"issues": issues, "smells": smells, "security": security}
