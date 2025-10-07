from typing import Dict, Any, List
import re
from app.analyzers.common import make_issue, long_function_detector, duplicate_block_hash

RESOURCE = re.compile(r"new\s+(FileInputStream|BufferedReader|Scanner)\(")
SQL_PLUS = re.compile(r"(Statement|PreparedStatement)\s+.*=\s*.*\+.*;")

def analyze_java(code: str) -> Dict[str, Any]:
    lines = code.splitlines()

    issues: List[dict] = []
    smells: List[dict] = []
    security: List[dict] = []

    # 资源未关闭
    for i, ln in enumerate(lines, start=1):
        if RESOURCE.search(ln) and "try (" not in ln:
            issues.append(make_issue("BUG.RES_NOT_CLOSED", "medium", "资源可能未关闭，建议使用 try-with-resources", i, i, ln.strip()))

    # 坏味道
    smells += long_function_detector(lines, threshold=60)
    smells += duplicate_block_hash(lines, window=6)

    # SQL 字符串拼接
    for i, ln in enumerate(lines, start=1):
        if SQL_PLUS.search(ln):
            security.append(make_issue("SEC.SQLI", "high", "SQL 语句字符串拼接，建议使用参数化 PreparedStatement", i, i, ln.strip()))

    return {"issues": issues, "smells": smells, "security": security}
