from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from app.analyzers.python_static import analyze_python
from app.analyzers.java_static import analyze_java
from app.services.llm import llm_review

app = FastAPI(title="Smart Code Review Assistant", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 如需更安全可填具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    language: str = Field(..., description="python 或 java")
    code: str = Field(..., description="待分析代码")
    enable_llm: bool = True

class Issue(BaseModel):
    rule_id: str
    severity: str
    message: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    snippet: Optional[str] = None

class AnalyzeResponse(BaseModel):
    issues: List[Issue]
    smells: List[Issue]
    security: List[Issue]
    suggestions_markdown: str
    meta: Dict[str, Any] = {}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    code = req.code or ""
    lang = req.language.lower()
    if not code.strip():
        raise HTTPException(status_code=400, detail="代码内容为空")

    if lang == "python":
        local = analyze_python(code)
    elif lang == "java":
        local = analyze_java(code)
    else:
        raise HTTPException(status_code=400, detail="不支持的语言，只支持 python/java")

    issues = local.get("issues", [])
    smells = local.get("smells", [])
    security = local.get("security", [])

    suggestions_md = ""
    if req.enable_llm:
        try:
            llm = await llm_review(language=lang, code=code, local_findings=local)
            suggestions_md = llm.get("suggestions_markdown", "")
            issues += llm.get("issues", [])
            smells += llm.get("smells", [])
            security += llm.get("security", [])
        except Exception as e:
            suggestions_md += f"\n> [LLM 调用失败，已仅使用本地规则] {e}\n"

    def key(x):
        return (x.get("rule_id"), x.get("message"), x.get("start_line"), x.get("end_line"))
    def dedup(lst):
        seen, out = set(), []
        for it in lst:
            k = key(it)
            if k in seen:
                continue
            seen.add(k)
            out.append(it)
        return out

    return AnalyzeResponse(
        issues=[Issue(**x) for x in dedup(issues)],
        smells=[Issue(**x) for x in dedup(smells)],
        security=[Issue(**x) for x in dedup(security)],
        suggestions_markdown=suggestions_md or "- 暂无额外建议",
        meta={"llm": req.enable_llm}
    )
