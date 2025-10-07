from typing import List, Dict, Any

def make_issue(rule_id: str, severity: str, message: str, start=None, end=None, snippet: str = None):
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "start_line": start,
        "end_line": end,
        "snippet": snippet,
    }

def long_function_detector(lines: List[str], threshold: int = 50) -> List[Dict[str, Any]]:
    issues = []
    in_func, start, count = False, 0, 0
    for i, ln in enumerate(lines, start=1):
        if ("def " in ln or "function " in ln or "public " in ln or "void " in ln) and "(" in ln and ")" in ln:
            if in_func and count > threshold:
                issues.append(make_issue("SML.LONG_FUNC", "medium", f"函数过长: {count} 行", start, i-1))
            in_func, start, count = True, i, 1
        elif in_func:
            count += 1
    if in_func and count > threshold:
        issues.append(make_issue("SML.LONG_FUNC", "medium", f"函数过长: {count} 行", start, start+count-1))
    return issues

def duplicate_block_hash(lines: List[str], window: int = 6) -> List[Dict[str, Any]]:
    import hashlib
    sig2pos = {}
    out = []
    for i in range(len(lines)-window):
        block = "\n".join(x.strip() for x in lines[i:i+window] if x.strip())
        if not block:
            continue
        sig = hashlib.md5(block.encode()).hexdigest()
        if sig in sig2pos:
            out.append(make_issue("SML.DUP_CODE", "low", "疑似重复代码块", sig2pos[sig], i+window, block))
        else:
            sig2pos[sig] = i+1
    return out
