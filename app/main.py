from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import Database
from app.schemas import HoldingInput, SnapshotCreateInput
from app.service import PortfolioService


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR.parent / "data" / "portfolio.db"
ACCOUNT_TYPE_OPTIONS = [
    "普通账户",
    "养老金账户",
    "第三方平台账户",
    "券商账户",
    "货币/现金账户",
    "银行理财账户",
]
CATEGORY_LABELS = {
    "equity": "权益",
    "fixed_income": "固收",
    "cash": "现金",
    "gold": "黄金",
    "other": "其他",
}


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    database = Database(db_path)
    database.initialize()
    service = PortfolioService(database)
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    app = FastAPI(title="Portfolio Review App")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, edit_id: int | None = None):
        snapshots = service.list_snapshots()
        summary = service.get_allocation_summary()
        targets = service.get_target_allocation()
        analysis = service.get_portfolio_analysis()
        weekly_attribution = service.get_weekly_attribution()
        editing_snapshot = None
        if edit_id is not None:
            editing_snapshot = service.get_snapshot(edit_id)
        form_values = _build_form_values(editing_snapshot)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "snapshots": snapshots,
                "summary": summary,
                "targets": targets,
                "analysis": analysis,
                "weekly_attribution": weekly_attribution,
                "category_labels": CATEGORY_LABELS,
                "default_rows": list(range(max(1, len(form_values["holdings"])))),
                "account_type_options": ACCOUNT_TYPE_OPTIONS,
                "form_values": form_values,
                "editing_snapshot": editing_snapshot,
            },
        )

    @app.get("/api/weekly-snapshots")
    def list_weekly_snapshots():
        return service.list_snapshots()

    @app.post("/api/weekly-snapshots", status_code=status.HTTP_201_CREATED)
    def create_weekly_snapshot(payload: SnapshotCreateInput):
        return service.create_snapshot(payload)

    @app.post("/snapshots")
    async def create_snapshot_from_form(request: Request):
        body = (await request.body()).decode("utf-8")
        form = {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}
        holdings = _extract_holdings_from_form(form)
        payload = SnapshotCreateInput(
            snapshot_date=str(form.get("snapshot_date", "")),
            total_assets=_sum_total_assets(holdings),
            cash_balance=_sum_cash_balance(holdings),
            weekly_return_amount=_sum_weekly_pnl(holdings),
            ytd_return_amount=float(form.get("ytd_return_amount", 0) or 0),
            data_cutoff_notes=str(form.get("data_cutoff_notes", "")),
            notes=str(form.get("notes", "")),
            holdings=holdings,
        )
        snapshot_id_raw = str(form.get("snapshot_id", "")).strip()
        if snapshot_id_raw:
            service.update_snapshot(int(snapshot_id_raw), payload)
        else:
            service.create_snapshot(payload)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/targets")
    async def update_targets_from_form(request: Request):
        body = (await request.body()).decode("utf-8")
        form = {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}
        service.update_target_allocation(
            {
                "equity": {
                    "min": float(form.get("target_equity_min", 0) or 0),
                    "max": float(form.get("target_equity_max", 0) or 0),
                },
                "fixed_income": {
                    "min": float(form.get("target_fixed_income_min", 0) or 0),
                    "max": float(form.get("target_fixed_income_max", 0) or 0),
                },
                "cash": {
                    "min": float(form.get("target_cash_min", 0) or 0),
                    "max": float(form.get("target_cash_max", 0) or 0),
                },
                "gold": {
                    "min": float(form.get("target_gold_min", 0) or 0),
                    "max": float(form.get("target_gold_max", 0) or 0),
                },
            }
        )
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    return app


app = create_app()


def _extract_holdings_from_form(form) -> list[HoldingInput]:
    holdings: list[HoldingInput] = []
    indexes = sorted(
        {
            key.rsplit("_", 1)[1]
            for key in form.keys()
            if key.startswith("product_name_") and key.rsplit("_", 1)[1].isdigit()
        },
        key=int,
    )
    for index in indexes:
        product_name = str(form.get(f"product_name_{index}", "")).strip()
        if not product_name:
            continue
        holdings.append(
            HoldingInput(
                product_name=product_name,
                account_type=str(form.get(f"account_type_{index}", "")).strip() or "普通账户",
                amount=float(form.get(f"amount_{index}", 0) or 0),
                allocation_percent=float(form.get(f"allocation_percent_{index}", 0) or 0),
                category=str(form.get(f"category_{index}", "other")),
                action=str(form.get(f"action_{index}", "hold")),
                weekly_pnl_amount=float(form.get(f"weekly_pnl_amount_{index}", 0) or 0),
                valuation_cutoff_date=str(form.get(f"valuation_cutoff_date_{index}", "")),
                notes=str(form.get(f"holding_notes_{index}", "")),
            )
        )
    return holdings


def _build_form_values(snapshot) -> dict:
    if snapshot is None:
        return {
            "snapshot_id": "",
            "snapshot_date": "",
            "total_assets": "",
            "cash_balance": "",
            "weekly_return_amount": 0,
            "ytd_return_amount": 0,
            "data_cutoff_notes": "",
            "notes": "",
            "holdings": [
                {
                    "product_name": "",
                    "account_type": "普通账户",
                    "amount": "",
                    "allocation_percent": "",
                    "category": "equity",
                    "action": "hold",
                    "weekly_pnl_amount": 0,
                    "valuation_cutoff_date": "",
                    "notes": "",
                }
            ],
        }

    return {
        "snapshot_id": snapshot.id,
        "snapshot_date": snapshot.snapshot_date,
        "total_assets": snapshot.total_assets,
        "cash_balance": snapshot.cash_balance,
        "weekly_return_amount": snapshot.weekly_return_amount,
        "ytd_return_amount": snapshot.ytd_return_amount,
        "data_cutoff_notes": snapshot.data_cutoff_notes,
        "notes": snapshot.notes,
        "holdings": [
            {
                "product_name": holding.product_name,
                "account_type": holding.account_type,
                "amount": holding.amount,
                "allocation_percent": holding.allocation_percent,
                "category": holding.category,
                "action": holding.action,
                "weekly_pnl_amount": holding.weekly_pnl_amount,
                "valuation_cutoff_date": holding.valuation_cutoff_date,
                "notes": holding.notes,
            }
            for holding in snapshot.holdings
        ],
    }


def _sum_weekly_pnl(holdings: list[HoldingInput]) -> float:
    return round(sum(holding.weekly_pnl_amount for holding in holdings), 2)


def _sum_total_assets(holdings: list[HoldingInput]) -> float:
    return round(sum(holding.amount for holding in holdings), 2)


def _sum_cash_balance(holdings: list[HoldingInput]) -> float:
    return round(sum(holding.amount for holding in holdings if holding.category == "cash"), 2)
