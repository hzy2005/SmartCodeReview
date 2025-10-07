# app/services/llm.py
import os
import re
import json
import asyncio
import random
from typing import Dict, Any, List

import httpx
from dotenv import load_dotenv
from app.prompt.prompts import build_system_prompt, build_user_prompt

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").lower()  # deepseek / openai
MODEL = os.getenv("MODEL_NAME", "deepseek-chat")
TIMEOUT = int(os.getenv("TIMEOUT_SECONDS", "45"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "12000"))
MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "4"))
BASE_BACKOFF = float(os.getenv("LLM_BASE_BACKOFF", "0.8"))
JITTER = float(os.getenv("LLM_JITTER", "0.4"))

def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    head = int(limit * 0.7)
    tail = limit - head
    return s[:head] + "\n...\n/* truncated */\n" + s[-tail:]

def _cleanup_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)

def _extract_json(text: str) -> Dict[str, Any]:
    """提取最外层 JSON，增强容错性"""
    if not isinstance(text, str):
        raise ValueError("not string")
    
    # 清理文本
    t = text.strip().lstrip("\ufeff")
    
    # 尝试直接解析
    try:
        return json.loads(t)
    except Exception:
        pass
    
    # 尝试提取最外层的大括号内容
    start = t.find("{")
    if start == -1:
        raise ValueError("no { found")
    
    # 增强的括号配对扫描
    depth = 0
    in_str = False
    esc = False
    end_pos = None
    
    for i, ch in enumerate(t[start:], start=start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        
        if ch == '"':
            in_str = True
            esc = False
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_pos = i + 1
                break
    
    if end_pos:
        chunk = t[start:end_pos]
        try:
            return json.loads(chunk)
        except Exception as e:
            # 尝试修复常见的JSON问题
            try:
                # 修复尾随逗号
                cleaned = re.sub(r',\s*([}\]])', r'\1', chunk)
                # 修复未转义的控制字符
                cleaned = cleaned.replace('\n', '\\n').replace('\t', '\\t')
                return json.loads(cleaned)
            except Exception:
                raise ValueError(f"JSON parsing failed: {e}")
    
    raise ValueError("unbalanced braces or incomplete JSON")


def detect_truncation(text: str) -> bool:
    """检测文本是否被截断"""
    if not text or len(text) < 100:
        return False
    
    # 检查明显的截断迹象
    indicators = [
        # JSON结构不完整
        text.count('{') != text.count('}'),
        text.count('[') != text.count(']'),
        text.count('"') % 2 != 0,
        
        # Markdown结构不完整
        '```' in text and text.count('```') % 2 != 0,
        
        # 代码示例不完整
        '```python' in text and '```' not in text.split('```python')[-1],
        '```java' in text and '```' not in text.split('```java')[-1],
        
        # 在重要内容中间突然结束
        any(marker in text.lower() and not text.strip().endswith(marker) 
            for marker in ['修复:', '问题:', '建议:', '示例:', '代码:']),
        
        # 在代码块中间结束
        text.strip().endswith('\\n') and len(text) > 300,
        
        # 在转义字符中间结束
        text.endswith('\\') and not text.endswith('\\\\')
    ]
    
    return any(indicators)

def deep_clean_markdown(text):
    """深度清理Markdown文本"""
    if not text:
        return ""
    
    # 处理多层转义
    text = (text.replace('\\\\n', '\n')
               .replace('\\\\t', '\t')
               .replace('\\\\"', '"')
               .replace("\\\\'", "'")
               .replace('\\\\\\\\', '\\'))
    
    # 修复常见的格式问题
    text = (text.replace('# 安全修复建议\\n\\n', '# 安全修复建议\n\n')
               .replace('\\n## ', '\n## ')
               .replace('\\n```', '\n```')
               .replace('```\\n', '```\n'))
    
    return text

def extract_inner_suggestions(content_json):
    """从嵌套结构中提取 suggestions_markdown"""
    suggestions = content_json.get("suggestions_markdown", "")
    
    # 如果 suggestions 本身包含 JSON，尝试提取内层的 suggestions_markdown
    if isinstance(suggestions, str) and '"suggestions_markdown"' in suggestions:
        try:
            # 尝试解析为 JSON
            inner_data = json.loads(suggestions)
            if isinstance(inner_data, dict) and "suggestions_markdown" in inner_data:
                return inner_data["suggestions_markdown"]
        except:
            # 如果解析失败，使用正则提取
            import re
            match = re.search(r'"suggestions_markdown"\s*:\s*"([^"]*)"', suggestions)
            if match:
                return match.group(1)
    
    return suggestions

def fix_broken_markdown(text):
    """修复破损的Markdown格式"""
    if not text:
        return ""
    
    # 修复空的代码块
    text = re.sub(r'```\s*\n\s*```', '', text)
    
    # 修复转义字符
    text = (text.replace('\\\\n', '\n')
               .replace('\\\\t', '\t')
               .replace('\\\\"', '"')
               .replace("\\\\'", "'"))
    
    # 修复不完整的代码块
    text = re.sub(r'(##\s*\d+\.\s*[^\n]+)\s*```\s*\n\s*```', r'\1\n\n*代码示例缺失*', text)
    
    return text

# def _normalize_md(s: str) -> str:
#     if not s: 
#         return ""
#     t = s.replace("\r\n", "\n")
    
#     # 保护代码块内的内容
#     code_blocks = []
#     code_block_index = 0
    
#     # 提取代码块
#     def save_code_block(match):
#         nonlocal code_block_index
#         placeholder = f"___CODE_BLOCK_{code_block_index}___"
#         code_blocks.append({
#             'placeholder': placeholder,
#             'content': match.group(0)
#         })
#         code_block_index += 1
#         return placeholder
    
#     # 先用占位符替换所有代码块
#     t = re.sub(r"```(?:\w+)?\n.*?\n```", save_code_block, t, flags=re.DOTALL)
    
#     # 统一围栏为 ```
#     t = re.sub(r"^\s*`{3,}(\w+)?\s*$", lambda m: "```" + (m.group(1) or ""), t, flags=re.MULTILINE)
#     t = re.sub(r"^\s*`{3,}\s*$", "```", t, flags=re.MULTILINE)
#     t = re.sub(r"`{4,}\s*$", "```", t)
    
#     # 修复常见畸形
#     t = re.sub(r"(^|\n)\s*`?python`?\s*(?=\n|$)", r"\n```python", t, flags=re.IGNORECASE)
#     t = re.sub(r"\n`\s*$", "\n```", t)
    
#     # 自动补齐闭合
#     lines = t.split("\n")
#     out = []
#     in_fence = False
    
#     for i, raw in enumerate(lines):
#         line = raw.strip()
#         if in_fence:
#             if re.match(r"^```", line):
#                 out.append("```")
#                 in_fence = False
#                 continue
#             out.append(raw)
#             if i == len(lines)-1:
#                 out.append("```")
#                 in_fence = False
#             continue
        
#         m = re.match(r"^```(\w+)?\s*$", line)
#         if m:
#             out.append("```" + (m.group(1) or ""))
#             in_fence = True
#             continue
        
#         if re.match(r"^\s*``\s*$", line):
#             out.append("```")
#             continue
        
#         out.append(raw)
    
#     t = "\n".join(out)
    
#     # 恢复代码块
#     for block in code_blocks:
#         t = t.replace(block['placeholder'], block['content'])
    
#     # 头部像代码但没围栏 → 包起来
#     head = t.split("\n")[:6]
#     looks_code = sum(bool(re.search(r"^\s{2,}|[{}();]|:=|^\s*import\s+|^\s*from\s+|^\s*class\s+|^\s*def\s+", l)) for l in head) >= 3
#     if not re.match(r"^```", t.strip()) and looks_code:
#         t = "```\n" + t + "\n```"
    
#     t = re.sub(r"``\s*$", "```", t)
#     return t

def _normalize_md(s: str) -> str:
    if not s: 
        return ""
    
    # 基本清理
    t = s.replace("\r\n", "\n")
    
    # 处理转义字符
    t = (t.replace('\\\\n', '\n')
         .replace('\\\\t', '\t')
         .replace('\\\\"', '"')
         .replace("\\\\'", "'")
         .replace('\\\\\\\\', '\\')
         .replace('\\n', '\n')
         .replace('\\t', '\t')
         .replace('\\"', '"')
         .replace("\\'", "'"))
    
    # 确保代码块格式正确
    lines = t.split("\n")
    result = []
    in_code_block = False
    
    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith('```'):
            if not in_code_block:
                # 开始代码块
                result.append(stripped)
                in_code_block = True
            else:
                # 结束代码块
                result.append('```')
                in_code_block = False
        elif in_code_block:
            # 在代码块中，保留原样
            result.append(line)
        else:
            # 不在代码块中，简单清理
            if stripped:
                result.append(stripped)
    
    # 如果最后还在代码块中，添加结束标记
    if in_code_block:
        result.append('```')
    
    return '\n'.join(result)

def _extract_inner_from_sugg(s: str):
    """从 suggestions_markdown 中解析内层 JSON，增强容错性"""
    if not isinstance(s, str):
        return None
    
    t = s.strip()
    
    # 优先提取 ```json ... ``` 里的内容
    json_block_match = re.search(r"```json\s*([\s\S]*?)```", t, re.IGNORECASE)
    if json_block_match:
        body = json_block_match[1]
        try:
            return _extract_json(body)
        except Exception:
            # 如果提取失败，继续尝试其他方法
            pass
    
    # 尝试直接提取整个文本中的JSON
    try:
        return _extract_json(t)
    except Exception:
        # 如果都失败，尝试手动提取关键字段
        return _salvage_broken_json(t)
    
def _salvage_broken_json(text: str) -> Dict[str, Any]:
    """从不完整的JSON文本中抢救数据"""
    result = {
        "issues": [],
        "smells": [], 
        "security": [],
        "suggestions_markdown": ""
    }
    
    # 提取 suggestions_markdown
    sugg_match = re.search(r'"suggestions_markdown"\s*:\s*"([^"]*)"', text)
    if sugg_match:
        result["suggestions_markdown"] = sugg_match.group(1)
    
    # 提取各个数组字段
    for field in ["issues", "smells", "security"]:
        field_match = re.search(f'"{field}"\\s*:\\s*\\[([\\s\\S]*?)\\]', text)
        if field_match:
            array_content = field_match.group(1)
            # 提取数组中的对象
            objects = re.findall(r'\{[^{}]*\}', array_content)
            for obj_str in objects:
                try:
                    # 修复常见的JSON问题
                    fixed_obj = obj_str.replace("'", '"')
                    obj = json.loads(fixed_obj)
                    if any(key in obj for key in ["rule_id", "message", "severity"]):
                        result[field].append(obj)
                except Exception:
                    # 如果解析失败，跳过这个对象
                    continue
    
    return result

async def _post_with_retry(url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
    attempt = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    if attempt >= MAX_RETRIES:
                        r.raise_for_status()
                    retry_after = r.headers.get("retry-after")
                    delay = float(retry_after) if retry_after else (BASE_BACKOFF * (2 ** attempt) + random.uniform(0, JITTER))
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError:
            if attempt >= MAX_RETRIES:
                raise
            delay = BASE_BACKOFF * (2 ** attempt) + random.uniform(0, JITTER)
            attempt += 1
            await asyncio.sleep(delay)

async def _call_deepseek(messages: List[Dict[str, str]]) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": messages, "temperature": 0.1, "max_tokens": 4096}
    data = await _post_with_retry(f"{base}/chat/completions", headers, payload)
    return data["choices"][0]["message"]["content"]

async def _call_openai(messages: List[Dict[str, str]]) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 OPENAI_API_KEY")
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": messages, "temperature": 0.1, "max_tokens": 4096}
    data = await _post_with_retry(f"{base}/chat/completions", headers, payload)
    return data["choices"][0]["message"]["content"]

async def llm_review(language: str, code: str, local_findings: Dict[str, Any]) -> Dict[str, Any]:
    safe_code = _truncate(code, MAX_INPUT_CHARS)
    system = build_system_prompt()
    user = build_user_prompt(language, safe_code, local_findings)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    if PROVIDER == "deepseek":
        content = await _call_deepseek(messages)
    elif PROVIDER == "openai":
        content = await _call_openai(messages)
    else:
        raise RuntimeError("Provider not implemented: " + PROVIDER)

    print(f"LLM原始响应: {content}")  # 调试输出

    # 先解析顶层 JSON
    try:
        content_json = _extract_json(content)
    except Exception as e:
        print(f"顶层JSON解析失败: {e}")
        content_json = {"suggestions_markdown": content}

    # 确保必要字段存在
    for k in ("issues", "smells", "security"):
        content_json.setdefault(k, [])
    
    # 处理 suggestions_markdown - 关键修复！
    raw_suggestions = content_json.get("suggestions_markdown", "")
    
    # 检查是否被截断 - 更严格的检测
   
    is_truncated = detect_truncation(raw_suggestions)
   
        
    if is_truncated:
        print("检测到截断，添加提示...")
        # 保留原始内容，但添加提示
        content_json["suggestions_markdown"] = raw_suggestions + "\n\n---\n**注意**: 响应可能被截断，建议:\n1. 减少代码长度\n2. 分模块分析\n3. 检查API的token限制设置"
    else:
        content_json["suggestions_markdown"] = raw_suggestions

    # 从 suggestions_markdown 中提取内层 JSON - 修复逻辑
    inner_data = None
    raw_suggestions_content = content_json.get("suggestions_markdown", "")
    
    if raw_suggestions_content and not is_truncated:
        try:
            inner_data = _extract_inner_from_sugg(raw_suggestions_content)
        except Exception as e:
            print(f"内层JSON提取失败: {e}")
            inner_data = None

    # 合并数据
    if inner_data:
        def dedup(lst):
            seen = set()
            out = []
            for x in lst or []:
                k = (x.get("rule_id"), x.get("message"), x.get("start_line"), x.get("end_line"))
                if k in seen:
                    continue
                seen.add(k)
                out.append(x)
            return out
        
        # 合并数组数据
        content_json["issues"] = dedup((content_json.get("issues") or []) + (inner_data.get("issues") or []))
        content_json["smells"] = dedup((content_json.get("smells") or []) + (inner_data.get("smells") or []))
        content_json["security"] = dedup((content_json.get("security") or []) + (inner_data.get("security") or []))
        
        # 只有当内层的suggestions_markdown更完整时才使用
        inner_suggestions = inner_data.get("suggestions_markdown", "")
        if inner_suggestions and len(inner_suggestions) > len(raw_suggestions_content):
            content_json["suggestions_markdown"] = inner_suggestions

    # 深度清理和修复Markdown
    final_suggestions = content_json.get("suggestions_markdown", "")
    final_suggestions = deep_clean_markdown(final_suggestions)
    final_suggestions = fix_broken_markdown(final_suggestions)
    final_suggestions = _normalize_md(final_suggestions)
    content_json["suggestions_markdown"] = final_suggestions

    # 添加元数据
    content_json["meta"] = {
        "llm": True,
        "truncated": is_truncated,
        "provider": PROVIDER
    }

    return content_json