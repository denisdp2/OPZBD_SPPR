"""Safely connect the evaluation service to the current FastAPI app."""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_FILE = ROOT / "app" / "api" / "app.py"
IMPORT_ANCHOR = "from app.core.problem import ScenarioError, build_problem\n"
IMPORT_LINE = "from app.evaluation import evaluate as evaluate_problem\n"
ROUTE_START = '    @api.post("/evaluate", tags=["decision"])\n'
NEXT_ROUTE = "    def problem_from(req: OptimizeRequest):\n"
NEW_ROUTE = '''    @api.post("/evaluate", tags=["decision"])
    def evaluate(scenario: Scenario) -> EvaluationResult:
        """Оценить покрытие и стоимость выбранного пользователем набора."""
        try:
            problem = build_problem(scenario, repo)
        except ScenarioError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return evaluate_problem(problem)

'''


def main() -> int:
    if not API_FILE.is_file():
        print(f"Не найден файл: {API_FILE}", file=sys.stderr)
        return 1

    original = API_FILE.read_text(encoding="utf-8")
    updated = original

    if IMPORT_LINE not in updated:
        if IMPORT_ANCHOR not in updated:
            print(
                "Не найден ожидаемый импорт build_problem. Файл не изменён; "
                "вероятно, версия ветки отличается.",
                file=sys.stderr,
            )
            return 2
        updated = updated.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE, 1)

    start = updated.find(ROUTE_START)
    if start < 0:
        print("Не найден маршрут POST /api/evaluate. Файл не изменён.", file=sys.stderr)
        return 3

    end = updated.find(NEXT_ROUTE, start)
    if end < 0:
        print("Не найден следующий обработчик problem_from. Файл не изменён.", file=sys.stderr)
        return 4

    current_route = updated[start:end]
    if "return evaluate_problem(problem)" in current_route:
        print("Маршрут /api/evaluate уже подключён. Ничего менять не нужно.")
        return 0
    if "raise not_implemented()" not in current_route:
        print(
            "Тело маршрута отличается от ожидаемого. Файл не изменён, "
            "чтобы не затереть чужие изменения.",
            file=sys.stderr,
        )
        return 5

    updated = updated[:start] + NEW_ROUTE + updated[end:]
    backup = Path("/tmp") / f"app.py.before-evaluation-{datetime.now():%Y%m%d-%H%M%S}.bak"
    shutil.copy2(API_FILE, backup)
    API_FILE.write_text(updated, encoding="utf-8")
    print("Маршрут POST /api/evaluate подключён.")
    print(f"Резервная копия исходного файла: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
