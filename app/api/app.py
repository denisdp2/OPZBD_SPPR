"""HTTP API — каркас.

Здесь зафиксирован список запросов и их форматы. Пока модули не готовы,
запросы отвечают 501 Not Implemented. Описание API после запуска: /docs
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, paths
from app.auth.deps import COOKIE_NAME, current_user, require_admin
from app.auth.schemas import AuthUser, LoginRequest
from app.auth.store import AuthStore, User
from app.core.interfaces import Repository
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


def not_implemented() -> HTTPException:
    return HTTPException(status_code=501, detail="Ещё не реализовано")


def create_app(
    repo: Repository | None = None,
    on_shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    app = FastAPI(title="СППР: подбор средств и мер защиты", version=__version__)
    app.state.repo = repo
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
        raise not_implemented()

    @api.get("/items", tags=["catalog"])
    def list_items(kind: ItemKind | None = None) -> list[Item]:
        raise not_implemented()

    @api.get("/profiles", tags=["catalog"])
    def list_profiles() -> list[Profile]:
        raise not_implemented()

    # ------------------------------------------------------------------ #
    #  Принятие решений
    # ------------------------------------------------------------------ #
    @api.post("/evaluate", tags=["decision"])
    def evaluate(scenario: Scenario) -> EvaluationResult:
        """Оценка набора: закрыты ли обязательные требования, стоимость."""
        raise not_implemented()

    @api.get("/optimizers", tags=["decision"])
    def list_optimizers() -> list[OptimizerInfo]:
        raise not_implemented()

    @api.post("/optimize", tags=["decision"])
    def optimize(req: OptimizeRequest) -> Solution:
        """Подбор оптимального набора выбранным алгоритмом."""
        raise not_implemented()

    @api.post("/pareto", tags=["decision"])
    def pareto(req: OptimizeRequest) -> list[Solution]:
        """Парето-фронт «стоимость / число закрытых требований»."""
        raise not_implemented()

    # ------------------------------------------------------------------ #
    #  Администрирование
    # ------------------------------------------------------------------ #
    @admin.get("/requirements/{req_id}")
    def get_requirement(req_id: str) -> Requirement:
        raise not_implemented()

    @admin.put("/requirements/{req_id}")
    def put_requirement(req_id: str, body: Requirement) -> Requirement:
        raise not_implemented()

    @admin.delete("/requirements/{req_id}")
    def delete_requirement(req_id: str) -> dict:
        raise not_implemented()

    @admin.get("/items/{item_id}")
    def get_item(item_id: str) -> Item:
        raise not_implemented()

    @admin.put("/items/{item_id}")
    def put_item(item_id: str, body: Item) -> Item:
        raise not_implemented()

    @admin.delete("/items/{item_id}")
    def delete_item(item_id: str) -> dict:
        raise not_implemented()

    @admin.get("/profiles/{profile_id}")
    def get_profile(profile_id: str) -> Profile:
        raise not_implemented()

    @admin.put("/profiles/{profile_id}")
    def put_profile(profile_id: str, body: Profile) -> Profile:
        raise not_implemented()

    @admin.delete("/profiles/{profile_id}")
    def delete_profile(profile_id: str) -> dict:
        raise not_implemented()

    @admin.get("/gaps")
    def gaps() -> list[Requirement]:
        """Требования, которые не закрывает ни одно средство или мера."""
        raise not_implemented()

    @admin.post("/import/{importer_name}")
    def import_file(importer_name: str, file: UploadFile) -> ImportReport:
        raise not_implemented()

    @admin.get("/export")
    def export() -> DataBundle:
        raise not_implemented()

    app.include_router(api)
    app.include_router(admin)

    # ------------------------------------------------------------------ #
    #  Фронтенд: статические файлы из frontend/, если они есть
    # ------------------------------------------------------------------ #
    front = paths.frontend_dir()
    if (front / "index.html").is_file():
        app.mount("/static", StaticFiles(directory=front), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(front / "index.html")

        @app.get("/admin", include_in_schema=False)
        def admin_page() -> FileResponse:
            return FileResponse(front / "admin.html")

        @app.get("/denied", include_in_schema=False)
        def denied_page() -> FileResponse:
            return FileResponse(front / "denied.html")

        @app.get("/admin/", include_in_schema=False)
        def admin_slash() -> RedirectResponse:
            return RedirectResponse("/admin")

    return app
