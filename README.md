# 智能代码审查助手（Smart Code Review Assistant）

> 面向团队协作的轻量级代码审查工具：支持 **Python / Java** 粘贴式分析，提供 **潜在 Bug、坏味道、常见安全风险** 的本地规则检测，并可选接入 **LLM** 生成优化建议与补充发现。

---

## 1. 项目亮点（What & Why）

* **开箱即用**：本地规则无外部依赖，起后端 + 打开 `web/index.html` 即可使用。
* **结构化输出**：按 `issues / smells / security` 分类返回，适合对接 CI 或导出报告。
* **LLM 可选**：在 `.env` 配置后，自动融合 LLM 结论，生成面向开发者的 Markdown 建议。
* **可扩展**：规则引擎与提示词均模块化，便于新增语言/规则或替换模型供应商。

---

## 2. 目录结构（How it's organized）

```text
SmartCodeReview
├─ app                         # 后端（FastAPI）
│  ├─ analyzers                # 本地静态规则（按语言划分）
│  │  ├─ __init__.py
│  │  ├─ common.py             # 通用工具/抽象：构造告警、重复检测、长函数等
│  │  ├─ python_static.py      # Python 规则：文件未关闭、命令注入、SQL 拼接、弱随机…
│  │  └─ java_static.py        # Java 规则：try-with-resources、SQL 拼接…
│  ├─ prompt                   # LLM 提示词与 Schema
│  │  ├─ __init__.py
│  │  └─ prompts.py            # system/user prompt + JSON Schema 约束
│  ├─ services
│  │  └─ llm.py                # LLM 调用与输出解析（OpenAI/可扩展）
│  └─ main.py                  # FastAPI 入口 + /analyze 实现
├─ web
│  └─ index.html               # 极简前端：语言切换、粘贴代码、一键分析
├─ .vscode/                    # VS Code 调试配置（可选）
├─ .env                        # 环境变量（可选，启用 LLM）
├─ requirements.txt            # Python 依赖
└─ README.md                   # 建议将本说明另存为 README
```

---

## 3. 功能清单（Features）

* **潜在 Bug**：

  * Python：`open()` 未配合 `with`（资源未关闭）等
  * Java：资源创建未使用 `try-with-resources`
* **代码坏味道（Smells）**：

  * 过长函数（基于行数阈值的启发式）
  * 重复代码块（滑动窗口 + hash 签名）
* **安全风险（Security）**：

  * 字符串拼接 SQL（SQL 注入风险）
  * `os.system()` 命令拼接（命令注入）
  * 非安全随机（`random`）用于安全语境
* **LLM 建议（可选）**：

  * 基于本地检查结果与代码上下文，生成补充问题与**可操作的重构/修复建议**（Markdown），并尝试 JSON 结构化返回更多发现。

> 说明：规则为启发式/轻量静态分析，旨在课堂项目与原型演示，**并非工业级 SAST**；可用 AST/tree-sitter 增强精度。

---

## 4. 快速上手（Windows + Conda + VS Code）

> 详细步骤见“团队内快速跑通”，这里给最短路径。

1. 创建环境并安装依赖：

   ```powershell
   conda create -n screview python=3.11 -y
   conda activate screview
   pip install -r requirements.txt
   ```
2. 运行后端：

   ```powershell
   uvicorn app.main:app --reload --port 8000
   # 健康检查: http://localhost:8000/health
   ```
3. 打开前端：

   * 直接双击 `web/index.html`（或 VS Code 扩展 **Live Server** 打开）。
4. 粘贴 Python/Java 代码 → 选择语言 → 点击 **Analyze**。

### 启用 LLM（可选）

根目录创建 `.env`：

```ini
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
MODEL_NAME=gpt-4o-mini
LLM_PROVIDER=openai
TIMEOUT_SECONDS=45
```

> 前端勾选 **Enable LLM**；如不配置 Key，保持未勾选即可仅用本地规则。

---

## 5. API 规范（Backend API）

**Base URL**：`http://localhost:8000`

### `POST /analyze`

* **请求体**

```json
{
  "language": "python" | "java",
  "code": "...源代码...",
  "enable_llm": true
}
```

* **响应体（示例）**

```json
{
  "issues": [
    {"rule_id":"BUG.FILE_NOT_CLOSED","severity":"medium","message":"文件打开未使用 with 上下文管理","start_line":5,"end_line":5,"snippet":"f = open(\"a.txt\", \"w\")"}
  ],
  "smells": [
    {"rule_id":"SML.LONG_FUNC","severity":"medium","message":"函数过长: 78 行","start_line":10,"end_line":88}
  ],
  "security": [
    {"rule_id":"SEC.SQLI","severity":"high","message":"字符串拼接 SQL 注入风险，改用参数化查询","start_line":22,"end_line":22}
  ],
  "suggestions_markdown": "### 修复建议...",
  "meta": {"llm": true}
}
```

> 注意：当启用 LLM 时，服务会融合 LLM 返回的结构化问题并去重；LLM 失败会在 `suggestions_markdown` 里提示，不影响本地规则结果。

---

## 6. 规则实现与扩展（Analyzers）

* **`app/analyzers/common.py`**：

  * `make_issue()`：统一构造问题对象。
  * `long_function_detector()`：基于行数简单统计识别过长函数，阈值可调。
  * `duplicate_block_hash()`：滑动窗口 + MD5 签名识别重复代码片段。
* **`python_static.py`**：

  * 资源使用：`open()` 未配合 `with`。
  * 安全：SQL 拼接、命令注入、弱随机。
* **`java_static.py`**：

  * 资源管理：`FileInputStream/Scanner/...` 未使用 `try (...)`。
  * 安全：`Statement/PreparedStatement` 行内字符串拼接。

### 如何新增规则

1. 在对应语言文件新增正则/启发式/AST 检测；
2. 使用 `make_issue(rule, severity, message, start, end, snippet)` 返回；
3. 在 `main.py` 的合并阶段自动纳入并按 `(rule_id, message, start, end)` 去重；
4. 更新前端展示文案（如需新分类）。

---

## 7. LLM 集成（services/prompt）

* **`prompt/prompts.py`**：

  * `build_system_prompt()`：设定专家角色与风格。
  * `build_user_prompt(language, code, local_findings)`：把本地结果与代码拼装到 User Prompt 中，并附带 **JSON Schema** 指导模型按结构化输出。
* **`services/llm.py`**：

  * 通过环境变量选择 Provider（默认 OpenAI）。
  * 解析模型回复中 JSON 片段（容错：无法解析时将全文作为 `suggestions_markdown`）。

> 要接入其他模型（如 DeepSeek/CodeLlama/Together），实现 `_call_other()` 并在 `.env` 切换 `LLM_PROVIDER` 即可。

---

## 8. 前端交互（web/index.html）

* 简洁单页：语言下拉 + LLM 开关 + 代码粘贴区 + 结果区域。
* 调用 `POST /analyze` 后渲染三类问题清单 + 建议（Markdown 文本以 `<pre>` 呈现）。
* 可替换为任意框架（React/Vue）或接入更丰富的可视化。

---

## 10. 测试与质量保证

* 框架建议：`pytest` 进行规则命中率与回归测试。
* 最小样例（示意）：

  ```python
  from app.analyzers.python_static import analyze_python
  def test_detect_sql_and_file():
      code = 'conn.execute("SELECT * FROM t" + user)\nopen("a.txt", "w")\n'
      result = analyze_python(code)
      rules = [x["rule_id"] for x in result["security"] + result["issues"]]
      assert "SEC.SQLI" in rules
      assert "BUG.FILE_NOT_CLOSED" in rules
  ```

---

## 12. 已知限制 & 路线图

* 规则为启发式，**存在误报/漏报**；建议用 AST 或 tree-sitter 强化解析。
* 目前只含 **Python/Java** 的基础规则；下一步可拓展 JS/Go/C#。
* LLM 输出解析基于 JSON 片段定位，需改进稳健性（可考虑 `response_format` / function calling）。

**Roadmap（建议）**：

1. 引入 AST / 复杂度度量（圈复杂度、参数过多等）；
2. 增加 SARIF 导出以便与安全平台联动；


---

## 13. 常见问题（FAQ）

* **Q：没有配置 Key 能用吗？**

  * A：可以。把前端的 **Enable LLM** 取消勾选即可，仅使用本地规则。
* **Q：跨域/CORS 报错？**

  * A：后端默认放开 `allow_origins=["*"]`。如自定义端口/域名仍异常，检查浏览器缓存或手动指定允许来源。
* **Q：如何新增一条规则？**

  * A：在 `python_static.py/java_static.py` 按示例新增匹配逻辑 → 返回 `make_issue()` → 前端自动展示。

