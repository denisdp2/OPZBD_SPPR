"""HTTP API. Справочники и импорт работают через интерфейс Repository.

Оценка выбранного набора пока не подключена. Подбор набора идёт через алгоритмы
из app.optimization. Описание API: /docs.
"""

import asyncio
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from app import __version__, paths
from app.auth.deps import COOKIE_NAME, current_user, require_admin, require_login
from app.auth.schemas import AuthUser, LoginRequest, RegisterRequest, UserDraft
from app.auth.store import AuthStore, User
from app.core.interfaces import NotFoundError, Repository
from app.core.models import (
    DataBundle,
    EvaluationResult,
    ImportReport,
    Item,
    ItemKind,
    OptimizeRequest,
    OptimizerInfo,
    Profile,
    Requirement,
    Scenario,
    Solution,
)
from app.core.problem import ScenarioError, build_problem
from app.importers.registry_download import download_registry_export, download_registry_xml
from app.importers.service import RegistryService
from app.optimization import UnknownOptimizer, get_optimizer
from app.optimization import list_optimizers as optimizer_catalog
from app.optimization.cancel import OptimizationCancelled, bind, reset
from app.storage.registry import RegistryStore
from app.storage.registry_export import export_registry_xlsx
from app.storage.sqlite import SQLiteRepository


def not_implemented() -> HTTPException:
    return HTTPException(status_code=501, detail="Ещё не реализовано")


class ManualRegistryPrice(BaseModel):
    value: float | None = Field(ge=0, allow_inf_nan=False)


def create_app(
    repo: Repository | None = None,
    on_shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    app = FastAPI(title="СППР: подбор средств и мер защиты", version=__version__)
    repo = repo if repo is not None else SQLiteRepository(paths.data_dir() / "catalog.sqlite3")
    app.state.repo = repo
    app.state.opt_cancel = None
    registry = RegistryService(repo, RegistryStore(paths.data_dir() / "catalog.sqlite3"))
    app.state.registry = registry

    @app.exception_handler(NotFoundError)
    async def missing_record(request: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": "Запись не найдена"})

    auth = AuthStore(paths.data_dir() / "auth.sqlite3")
    auth.init()
    app.state.auth = auth
    api = APIRouter(prefix="/api")
    admin = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

    # ------------------------------------------------------------------ #
    #  Служебное
    # ------------------------------------------------------------------ #
    @api.get("/health", tags=["service"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @api.post("/shutdown", tags=["service"])
    def shutdown() -> dict:
        """Завершить работу программы."""
        if on_shutdown is None:
            raise HTTPException(status_code=501, detail="Недоступно в этом режиме запуска")
        on_shutdown()
        return {"status": "stopping"}

    # ------------------------------------------------------------------ #
    #  Вход / роли
    # ------------------------------------------------------------------ #
    @api.post("/auth/register", status_code=201, tags=["auth"])
    def register(body: RegisterRequest) -> AuthUser:
        login = body.login.strip()
        if len(login) < 3:
            raise HTTPException(status_code=422, detail="Логин должен содержать от 3 символов")
        user = auth.register(login, body.password)
        if user is None:
            raise HTTPException(status_code=409, detail="Этот логин уже занят")
        return AuthUser(id=user.id, login=user.login, role=user.role)

    @api.get("/users/{user_id}/draft", tags=["scenario"])
    def read_draft(user_id: int, user: User = Depends(require_login)) -> UserDraft | None:
        if user_id != user.id:
            raise HTTPException(status_code=403, detail="Черновик принадлежит другому аккаунту")
        data = auth.read_draft(user.id)
        return UserDraft.model_validate_json(data) if data is not None else None

    @api.put("/users/{user_id}/draft", status_code=204, tags=["scenario"])
    def save_draft(user_id: int, draft: UserDraft, user: User = Depends(require_login)) -> None:
        if user_id != user.id:
            raise HTTPException(status_code=403, detail="Черновик принадлежит другому аккаунту")
        auth.save_draft(user.id, draft.model_dump_json())

    @api.post("/auth/login", tags=["auth"])
    def login(body: LoginRequest, response: Response) -> AuthUser:
        user = app.state.auth.authenticate(body.login, body.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Неверный логин или пароль")
        token = app.state.auth.create_session(user)
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="lax",
            max_age=int(12 * 60 * 60),
            path="/",
        )
        return AuthUser(id=user.id, login=user.login, role=user.role)

    @api.post("/auth/logout", tags=["auth"])
    def logout(request: Request, response: Response) -> dict:
        app.state.auth.delete_session(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"status": "ok"}

    @api.get("/auth/me", tags=["auth"])
    def me(user: User | None = Depends(current_user)) -> AuthUser:
        if user is None:
            raise HTTPException(status_code=401, detail="Нужна авторизация")
        return AuthUser(id=user.id, login=user.login, role=user.role)

    # ------------------------------------------------------------------ #
    #  Справочники
    # ------------------------------------------------------------------ #
    @api.get("/requirements", tags=["catalog"])
    def list_requirements() -> list[Requirement]:
        return repo.list_requirements()

    @api.get("/items", tags=["catalog"])
    def list_items(kind: ItemKind | None = None) -> list[Item]:
        return repo.list_items(kind)

    @api.get("/profiles", tags=["catalog"])
    def list_profiles() -> list[Profile]:
        return repo.list_profiles()

    # ------------------------------------------------------------------ #
    #  Принятие решений
    # ------------------------------------------------------------------ #
    @api.post("/evaluate", tags=["decision"])
    def evaluate(scenario: Scenario) -> EvaluationResult:
        """Оценка набора: закрыты ли обязательные требования, стоимость."""
        raise not_implemented()

    def problem_from(req: OptimizeRequest):
        try:
            return build_problem(req.scenario, repo)
        except ScenarioError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def optimizer_from(name: str):
        try:
            return get_optimizer(name)
        except UnknownOptimizer as exc:
            raise HTTPException(status_code=404, detail="Алгоритм не найден") from exc

    @api.get("/optimizers", tags=["decision"])
    def list_optimizers() -> list[OptimizerInfo]:
        return optimizer_catalog()

    def run_cancellable(fn):
        event = threading.Event()
        app.state.opt_cancel = event

        def wrapped():
            token = bind(event)
            try:
                return fn()
            finally:
                reset(token)

        return event, wrapped

    @api.post("/optimize/cancel", tags=["decision"])
    def cancel_optimization() -> dict:
        event = app.state.opt_cancel
        if event is not None:
            event.set()
        return {"status": "stopping"}

    @api.post("/optimize", tags=["decision"])
    async def optimize(req: OptimizeRequest) -> Solution:
        """Подбор оптимального набора выбранным алгоритмом."""
        if req.mode == "max_coverage" and req.budget is None:
            raise HTTPException(
                status_code=422, detail="Для режима максимального покрытия нужен бюджет"
            )
        problem = problem_from(req)
        optimizer = optimizer_from(req.algorithm)
        event, wrapped = run_cancellable(lambda: optimizer.solve(problem, req.mode, req.budget))
        try:
            return await asyncio.to_thread(wrapped)
        except OptimizationCancelled as exc:
            raise HTTPException(status_code=499, detail="Расчёт остановлен") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            if app.state.opt_cancel is event:
                app.state.opt_cancel = None

    @api.post("/pareto", tags=["decision"])
    async def pareto(req: OptimizeRequest) -> list[Solution]:
        """Парето-фронт «стоимость / число закрытых требований»."""
        problem = problem_from(req)
        optimizer = optimizer_from(req.algorithm)
        event, wrapped = run_cancellable(lambda: optimizer.pareto(problem))
        try:
            return await asyncio.to_thread(wrapped)
        except OptimizationCancelled as exc:
            raise HTTPException(status_code=499, detail="Расчёт остановлен") from exc
        except NotImplementedError as exc:
            raise HTTPException(status_code=400, detail="Алгоритм не строит Парето-фронт") from exc
        finally:
            if app.state.opt_cancel is event:
                app.state.opt_cancel = None

    # ------------------------------------------------------------------ #
    #  Администрирование
    # ------------------------------------------------------------------ #
    @admin.get("/requirements/{req_id}")
    def get_requirement(req_id: str) -> Requirement:
        return repo.get_requirement(req_id)

    @admin.put("/requirements/{req_id}")
    def put_requirement(req_id: str, body: Requirement) -> Requirement:
        if req_id != body.id:
            raise HTTPException(status_code=422, detail="Код в URL не совпадает с кодом записи")
        repo.upsert_requirement(body)
        return body

    @admin.delete("/requirements/{req_id}")
    def delete_requirement(req_id: str) -> dict:
        repo.delete_requirement(req_id)
        return {"status": "ok"}

    @admin.get("/items/{item_id}")
    def get_item(item_id: str) -> Item:
        return repo.get_item(item_id)

    @admin.put("/items/{item_id}")
    def put_item(item_id: str, body: Item) -> Item:
        if item_id != body.id:
            raise HTTPException(status_code=422, detail="Код в URL не совпадает с кодом записи")
        repo.upsert_item(body)
        return body

    @admin.delete("/items/{item_id}")
    def delete_item(item_id: str) -> dict:
        repo.delete_item(item_id)
        return {"status": "ok"}

    @admin.get("/profiles/{profile_id}")
    def get_profile(profile_id: str) -> Profile:
        return repo.get_profile(profile_id)

    @admin.put("/profiles/{profile_id}")
    def put_profile(profile_id: str, body: Profile) -> Profile:
        if profile_id != body.id:
            raise HTTPException(status_code=422, detail="Код в URL не совпадает с кодом записи")
        repo.upsert_profile(body)
        return body

    @admin.delete("/profiles/{profile_id}")
    def delete_profile(profile_id: str) -> dict:
        repo.delete_profile(profile_id)
        return {"status": "ok"}

    @admin.get("/gaps")
    def gaps() -> list[Requirement]:
        """Требования, которые не закрывает ни одно средство или мера."""
        return repo.uncovered_requirements()

    @admin.post("/import/{importer_name}")
    def import_file(importer_name: str, file: UploadFile) -> ImportReport:
        if importer_name not in {"ru-software", "ru-software-sqlite", "bundle"}:
            raise HTTPException(status_code=404, detail="Неизвестный импортёр")
        suffix = Path(file.filename or "").suffix.lower()
        extensions = {
            "ru-software": {".xlsx", ".xls", ".xml", ".json"},
            "ru-software-sqlite": {".db", ".sqlite", ".sqlite3"},
            "bundle": {".json"},
        }
        if suffix not in extensions[importer_name]:
            raise HTTPException(status_code=422, detail="Неподдерживаемый формат файла")
        try:
            with TemporaryDirectory() as directory:
                target = Path(directory) / ("upload" + suffix)
                total = 0
                with target.open("wb") as output:
                    while chunk := file.file.read(65536):
                        total += len(chunk)
                        if total > (
                            250_000_000
                            if suffix == ".xml"
                            else 100_000_000
                            if importer_name == "ru-software-sqlite"
                            else 50_000_000
                        ):
                            raise HTTPException(
                                status_code=413,
                                detail="Файл превышает лимит размера выгрузки",
                            )
                        output.write(chunk)
                if importer_name in {"ru-software", "ru-software-sqlite"}:
                    return registry.import_file(target)
                bundle = DataBundle.model_validate_json(target.read_bytes())
                return ImportReport(importer="bundle", imported=repo.import_bundle(bundle))
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)[:500]) from exc
        except (OSError, KeyError, BadZipFile, ParseError, sqlite3.DatabaseError) as exc:
            raise HTTPException(status_code=422, detail="Не удалось прочитать выгрузку") from exc
        finally:
            file.file.close()

    @admin.get("/registry")
    def list_registry(
        q: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        state: Literal["active", "excluded", "all"] = "active",
        sort: Literal["reg_number", "name", "owner", "status", "value", "source"] = "reg_number",
        direction: Literal["asc", "desc"] = "asc",
    ) -> dict:
        records = registry.store.query(q, state, sort, direction == "desc")
        return {"total": len(records), "items": records[offset : offset + limit]}

    @admin.get("/registry/export.xlsx")
    def registry_excel(
        q: str = "",
        state: Literal["active", "excluded", "all"] = "active",
        sort: Literal["reg_number", "name", "owner", "status", "value", "source"] = "reg_number",
        direction: Literal["asc", "desc"] = "asc",
    ) -> Response:
        content = export_registry_xlsx(registry.store.query(q, state, sort, direction == "desc"))
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="registry.xlsx"'},
        )

    def save_registry_export(format: str) -> tuple[Path, bool]:
        cache = paths.data_dir() / "registry-cache" / f"registry.{format}"
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=cache.parent) as directory:
                target = Path(directory) / cache.name
                if format == "xml":
                    download_registry_xml(target)
                else:
                    download_registry_export(target, format)
                target.replace(cache)
            return cache, False
        except (httpx.HTTPError, ValueError, OSError) as exc:
            if cache.is_file():
                return cache, True
            message = "Не удалось сохранить выгрузку реестра."
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                message += " Сертификат сайта не доверен этой системе."
            raise HTTPException(status_code=502, detail=message) from exc

    @admin.post("/registry/download/{format}")
    def save_official(format: Literal["xml", "xls"]) -> dict:
        path, cached = save_registry_export(format)
        return {"path": str(path.resolve()), "cached": cached}

    @admin.get("/registry/download/{format}")
    def download_official(format: Literal["xml", "html", "xls"]):
        path, cached = save_registry_export(format)
        return FileResponse(
            path, filename=path.name, headers={"X-Registry-Source": "cache"} if cached else {}
        )

    @admin.put("/registry/{number}/price", status_code=204)
    def update_registry_price(number: int, body: ManualRegistryPrice) -> None:
        if not registry.store.set_manual_price(number, body.value):
            raise HTTPException(status_code=404, detail="Запись не найдена")

    @admin.post("/registry/prices/stop")
    def stop_prices() -> dict:
        return registry.stop()

    @admin.post("/registry/prices", status_code=202)
    def start_prices(
        tasks: BackgroundTasks,
        retry: bool = False,
        refresh: bool = False,
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict:
        """Параметр limit задаёт размер порции, а не общий объём задачи."""
        try:
            result = registry.start(retry, limit, refresh)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        tasks.add_task(registry.run)
        return result

    @admin.get("/registry/prices/status")
    def price_status() -> dict:
        return registry.status()

    @admin.get("/export")
    def export() -> DataBundle:
        return repo.export_bundle()

    app.include_router(api)
    app.include_router(admin)

    # ------------------------------------------------------------------ #
    #  Фронтенд: статические файлы из frontend/, если они есть
    # ------------------------------------------------------------------ #
    front = paths.frontend_dir()
    if front.is_dir():
        app.mount("/static", StaticFiles(directory=front), name="static")

        if (front / "index.html").is_file():

            @app.get("/", include_in_schema=False)
            def index() -> FileResponse:
                return FileResponse(front / "index.html")

        @app.get("/admin", include_in_schema=False)
        def admin_page(user: User | None = Depends(current_user)):
            if user is None:
                return RedirectResponse("/", status_code=303)
            if user.role != "admin":
                return RedirectResponse("/denied", status_code=303)
            return FileResponse(front / "admin.html")

        @app.get("/denied", include_in_schema=False)
        def denied_page() -> FileResponse:
            return FileResponse(front / "denied.html")

        @app.get("/admin/", include_in_schema=False)
        def admin_slash() -> RedirectResponse:
            return RedirectResponse("/admin")

    return app
