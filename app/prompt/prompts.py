from textwrap import dedent
import json

def build_system_prompt() -> str:
    return dedent(
        """
        你是一名严谨的资深代码审查专家与安全工程师，熟悉 Python 与 Java 的最佳实践、OWASP Top 10、常见代码坏味道与重构手法。
        输出必须结构化、可执行，避免主观评价，尽量给出可粘贴的修改片段与原理说明。
        """
    ).strip()

SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {"type": "array", "items": {"type": "object"}},
        "smells": {"type": "array", "items": {"type": "object"}},
        "security": {"type": "array", "items": {"type": "object"}},
        "suggestions_markdown": {"type": "string"}
    },
    "required": ["suggestions_markdown"]
}

def build_user_prompt(language: str, code: str, local_findings: dict) -> str:
    local_json = json.dumps(local_findings, ensure_ascii=False)
    return dedent(f"""
    任务：对以下 {language} 代码进行严格的审查，结合我提供的本地静态检查结果，补充发现并生成可读报告。

    要求：
    1) 严格按 JSON 模式输出（见 schema），字段含义：
       - issues/smells/security: 列表，元素包含 rule_id/severity/message/start_line/end_line/snippet
       - suggestions_markdown: 面向开发者的精简建议（Markdown），包含示例代码。
    2) 不要重复本地结果，侧重高价值问题与修复建议；如与本地结果冲突，以更严格、安全的方案为准。

    本地静态检查结果（仅供参考）：
    {local_json}

    代码：
    ```{language}
    {code}
    ```

    请仅返回一个 JSON 对象，符合此 JSON Schema：
    {json.dumps(SCHEMA, ensure_ascii=False)}
    """).strip()
