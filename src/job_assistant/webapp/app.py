from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from job_assistant import config
from job_assistant.webapp.db import WebAppStore
from job_assistant.webapp.service import WebAppService

try:
    import pypdf
except ImportError:  # pragma: no cover - optional dependency
    pypdf = None


SESSION_COOKIE = "job_assistant_session"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class AuthPayload(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class ProfilePayload(BaseModel):
    profile: dict[str, Any]


class ThreadPayload(BaseModel):
    title: str = "新会话"


class MessagePayload(BaseModel):
    message: str = ""
    jdText: str = ""
    jdTitle: str = ""
    jdCity: str = ""


class SearchPayload(BaseModel):
    keywords: list[str]
    cities: list[str] = []
    salaryMinK: int | None = None
    salaryMaxK: int | None = None
    maxResults: int = 10
    refresh: bool = False
    threadId: str = ""


class PlanPayload(BaseModel):
    timeframe: str = "3months"


class GitHubSearchPayload(BaseModel):
    user_query: str
    min_stars: int = 1000
    top_n: int = 5
    include_audit: bool = False
    include_similar: bool = True
    use_profile: bool = False  # 是否使用用户画像
    user_choice: str | None = None
    retry_context: dict[str, Any] | None = None


class AuditRepoPayload(BaseModel):
    expected_capabilities: list[str] = []
    allow_light_run: bool = True
    keep_workspace: bool = False


def create_app() -> FastAPI:
    config.ensure_dirs()
    app = FastAPI(title="AI Job Assistant Web", version="0.2.0")
    store = WebAppStore(config.APP_DB_PATH)
    service = WebAppService(store)
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def current_user(session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict[str, Any]:
        if not session_id:
            raise HTTPException(status_code=401, detail="未登录")
        user = service.get_user_from_session(session_id)
        if not user:
            raise HTTPException(status_code=401, detail="登录已失效")
        return user

    @app.post("/api/auth/register")
    def register(payload: AuthPayload):
        try:
            user = service.register_user(payload.username, payload.password)
            session = service.create_session(user["id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        response = {"user": user}
        from fastapi.responses import JSONResponse

        res = JSONResponse(response)
        res.set_cookie(
            SESSION_COOKIE,
            session["session_id"],
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=60 * 60 * 24 * 30,
        )
        return res

    @app.post("/api/auth/login")
    def login(payload: AuthPayload):
        user = service.authenticate_user(payload.username, payload.password)
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        session = service.create_session(user["id"])
        from fastapi.responses import JSONResponse

        res = JSONResponse({"user": user})
        res.set_cookie(
            SESSION_COOKIE,
            session["session_id"],
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=60 * 60 * 24 * 30,
        )
        return res

    @app.post("/api/auth/logout")
    def logout(session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
        from fastapi.responses import JSONResponse

        if session_id:
            service.logout(session_id)
        res = JSONResponse({"ok": True})
        res.delete_cookie(SESSION_COOKIE)
        return res

    @app.get("/api/me")
    def me(user: dict[str, Any] = Depends(current_user)):
        profile = service.get_profile(user["id"])
        return {"user": user, "hasProfile": bool(profile), "profileSummary": service.get_dashboard(user["id"]).get("profile_summary", "")}

    @app.get("/api/dashboard")
    def dashboard(user: dict[str, Any] = Depends(current_user)):
        return service.get_dashboard(user["id"])

    @app.get("/api/profile")
    def get_profile(user: dict[str, Any] = Depends(current_user)):
        return {"profile": service.get_profile(user["id"])}

    @app.put("/api/profile")
    def put_profile(payload: ProfilePayload, user: dict[str, Any] = Depends(current_user)):
        profile = service.save_profile(user["id"], payload.profile)
        return {"profile": profile}

    @app.post("/api/profile/resume")
    async def upload_resume(
        user: dict[str, Any] = Depends(current_user),
        resume_text: str = Form(default=""),
        resume_file: UploadFile | None = File(default=None),
    ):
        text = (resume_text or "").strip()
        if not text and resume_file is not None:
            text = await _read_resume_upload(resume_file)
        if not text:
            raise HTTPException(status_code=400, detail="请提供简历文本或文件")
        try:
            profile = service.extract_profile_from_resume_text(user["id"], text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"profile": profile}

    @app.get("/api/threads")
    def list_threads(user: dict[str, Any] = Depends(current_user)):
        return {"items": service.list_threads(user["id"])}

    @app.post("/api/threads")
    def create_thread(payload: ThreadPayload, user: dict[str, Any] = Depends(current_user)):
        return service.create_thread(user["id"], title=payload.title)

    @app.get("/api/threads/{thread_id}")
    def get_thread(thread_id: str, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.get_thread_detail(user["id"], thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/threads/{thread_id}/messages")
    def post_message(thread_id: str, payload: MessagePayload, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.post_thread_message(
                user["id"],
                thread_id,
                message=payload.message,
                jd_text=payload.jdText,
                jd_title=payload.jdTitle,
                jd_city=payload.jdCity,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/searches")
    def list_searches(user: dict[str, Any] = Depends(current_user)):
        return {"items": service.list_search_runs(user["id"])}

    @app.post("/api/searches")
    def create_search(payload: SearchPayload, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.search_jobs(
                user["id"],
                keywords=payload.keywords,
                cities=payload.cities,
                salary_min_k=payload.salaryMinK,
                salary_max_k=payload.salaryMaxK,
                max_results=payload.maxResults,
                refresh=payload.refresh,
                thread_id=payload.threadId,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/searches/{run_id}")
    def get_search(run_id: str, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.get_search_run(user["id"], run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, user: dict[str, Any] = Depends(current_user)):
        snapshot = service.store.get_job_snapshot(user["id"], job_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="职位不存在")
        return snapshot

    @app.post("/api/jobs/{job_id}/analyze")
    def analyze_job(job_id: str, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.analyze_job(user["id"], job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/plan")
    def create_plan(job_id: str, payload: PlanPayload, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.create_learning_plan(user["id"], job_id, payload.timeframe)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/plans")
    def list_plans(user: dict[str, Any] = Depends(current_user)):
        return {"items": service.list_learning_plans(user["id"])}

    @app.get("/api/audits")
    def list_audits(user: dict[str, Any] = Depends(current_user)):
        return {"items": service.list_repo_audits(user["id"])}

    @app.get("/api/audits/{audit_id}")
    def get_audit(audit_id: str, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.get_repo_audit(user["id"], audit_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/artifacts")
    def list_artifacts(kind: str | None = None, user: dict[str, Any] = Depends(current_user)):
        return {"items": service.list_artifacts(user["id"], kind=kind)}

    @app.get("/api/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.get_artifact(user["id"], artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: str, user: dict[str, Any] = Depends(current_user)):
        artifact = service.get_artifact(user["id"], artifact_id)
        path = Path(artifact["file_path"]).resolve()
        if not path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        return FileResponse(path, filename=path.name)

    @app.post("/api/github/search")
    def search_github_projects(payload: GitHubSearchPayload, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.search_github_projects(
                user["id"],
                user_query=payload.user_query,
                min_stars=payload.min_stars,
                top_n=payload.top_n,
                include_audit=payload.include_audit,
                include_similar=payload.include_similar,
                user_choice=payload.user_choice,
                retry_context=payload.retry_context,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/github/searches")
    def list_github_searches(user: dict[str, Any] = Depends(current_user)):
        return {"items": service.list_github_searches(user["id"])}

    @app.get("/api/github/searches/{search_id}")
    def get_github_search_result(search_id: str, user: dict[str, Any] = Depends(current_user)):
        result = service.get_github_search(user["id"], search_id)
        if result is None:
            raise HTTPException(status_code=404, detail="搜索记录不存在")
        return result

    @app.post("/api/github/repos/{owner}/{repo}/audit")
    def audit_github_repo(owner: str, repo: str, payload: AuditRepoPayload, user: dict[str, Any] = Depends(current_user)):
        try:
            return service.audit_github_repo(
                user["id"],
                owner=owner,
                repo=repo,
                expected_capabilities=payload.expected_capabilities,
                allow_light_run=payload.allow_light_run,
                keep_workspace=payload.keep_workspace,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        candidate = STATIC_DIR / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")

    return app


async def _read_resume_upload(upload: UploadFile) -> str:
    content = await upload.read()
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix in {".txt", ".md"}:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("gbk", errors="replace")
    if suffix == ".pdf":
        if pypdf is None:
            raise HTTPException(status_code=400, detail="缺少 pypdf，无法解析 PDF")
        reader = pypdf.PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise HTTPException(status_code=400, detail="仅支持 .txt / .md / .pdf 简历文件")
