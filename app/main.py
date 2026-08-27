from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import Database
from app.demo_seeder import seed_demo_data_if_needed
from app.performance_service import PerformanceService
from app.product_service import ProductService
from app.schemas import HoldingInput, ProductUpdateInput, SnapshotCreateInput
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
STATE_LABELS = {
    "up": "上行",
    "down": "下行",
    "sideways": "震荡",
    "turning": "转折观察",
}
EVIDENCE_LABELS = {"low": "低", "medium": "中", "high": "高"}
TURNING_DETAIL_LABELS = {
    "weak_to_strong": "由弱转强",
    "strong_to_weak": "由强转弱",
    "": "",
}
LIFECYCLE_LABELS = {
    "active": "正常",
    "planned_exit": "计划退出",
    "exited": "已退出",
}
DATA_STATUS_LABELS = {
    "available": "数据可用",
    "accumulating": "数据积累中",
    "discontinuous": "数据不连续",
    "unavailable": "计算不可用",
}
FLOW_SOURCE_LABELS = {
    "confirmed": "已确认",
    "estimated": "系统估算",
    "unavailable": "计算不可用",
}


def create_app(db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    database = Database(db_path)
    database.initialize()
    seed_demo_data_if_needed(database)
    service = PortfolioService(database)
    product_service = ProductService(database)
    performance_service = PerformanceService(database)
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    app = FastAPI(title="Portfolio Review App")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/health")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        edit_id: int | None = None,
        copy_id: int | None = None,
    ):
        snapshots = service.list_snapshots()
        summary = service.get_allocation_summary()
        targets = service.get_target_allocation()
        analysis = service.get_portfolio_analysis()
        lookthrough_analysis = service.get_lookthrough_analysis()
        weekly_attribution = service.get_weekly_attribution()
        cashflow_analysis = service.get_cashflow_analysis()
        data_quality = service.get_data_quality_checks()
        editing_snapshot = None
        copying_snapshot = None
        if edit_id is not None:
            editing_snapshot = service.get_snapshot(edit_id)
        elif copy_id is not None:
            copying_snapshot = service.get_snapshot(copy_id)
        if copying_snapshot is not None:
            previous_total_assets = copying_snapshot.total_assets
        elif editing_snapshot is not None:
            previous_total_assets = service.get_previous_total_assets(edit_id)
        else:
            previous_total_assets = service.get_previous_total_assets()
        form_values = _build_form_values(
            editing_snapshot or copying_snapshot,
            copy_as_new=copying_snapshot is not None,
        )
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "snapshots": snapshots,
                "summary": summary,
                "targets": targets,
                "analysis": analysis,
                "lookthrough_analysis": lookthrough_analysis,
                "weekly_attribution": weekly_attribution,
                "cashflow_analysis": cashflow_analysis,
                "data_quality": data_quality,
                "category_labels": CATEGORY_LABELS,
                "default_rows": list(range(max(1, len(form_values["holdings"])))),
                "account_type_options": ACCOUNT_TYPE_OPTIONS,
                "form_values": form_values,
                "editing_snapshot": editing_snapshot,
                "copying_snapshot": copying_snapshot,
                "previous_total_assets": previous_total_assets,
            },
        )

    @app.get("/api/weekly-snapshots")
    def list_weekly_snapshots():
        return service.list_snapshots()

    @app.get("/products", response_class=HTMLResponse)
    def product_settings(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="products.html",
            context={"products": product_service.list_products()},
        )

    @app.get("/analysis", response_class=HTMLResponse)
    def performance_analysis(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="analysis.html",
            context={
                "analysis": performance_service.get_analysis(),
                "state_labels": STATE_LABELS,
                "evidence_labels": EVIDENCE_LABELS,
                "turning_detail_labels": TURNING_DETAIL_LABELS,
                "lifecycle_labels": LIFECYCLE_LABELS,
                "data_status_labels": DATA_STATUS_LABELS,
                "flow_source_labels": FLOW_SOURCE_LABELS,
            },
        )

    @app.post("/products/{product_id}")
    async def update_product_settings(product_id: int, request: Request):
        body = (await request.body()).decode("utf-8")
        form = {key: values[-1] for key, values in parse_qs(body).items()}
        product_service.update_product(
            product_id,
            ProductUpdateInput(
                management_role=str(form["management_role"]),
                comparison_group=str(form["comparison_group"]),
                lifecycle_status=str(form["lifecycle_status"]),
            ),
        )
        return RedirectResponse(url="/products", status_code=status.HTTP_303_SEE_OTHER)

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
            ytd_return_amount=_sum_cumulative_pnl(holdings),
            external_net_flow_amount=_parse_optional_float(
                form.get("external_net_flow_amount", "")
            ),
            external_flow_confirmed=form.get("external_flow_confirmed") == "1",
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
        amount = _parse_float(form.get(f"amount_{index}", 0))
        transaction_amount = _parse_float(form.get(f"transaction_amount_{index}", 0))
        previous_amount = _parse_optional_float(form.get(f"previous_amount_{index}", ""))
        previous_cumulative_pnl = _parse_optional_float(
            form.get(f"previous_cumulative_pnl_amount_{index}", "")
        )
        previous_holding_cost = _parse_optional_float(
            form.get(f"previous_holding_cost_amount_{index}", "")
        )
        weekly_pnl_amount = _parse_float(form.get(f"weekly_pnl_amount_{index}", 0))
        if previous_amount is not None:
            weekly_pnl_amount = round(amount - previous_amount - transaction_amount, 2)
        cumulative_pnl_amount = _parse_float(form.get(f"cumulative_pnl_amount_{index}", 0))
        if previous_cumulative_pnl is not None:
            cumulative_pnl_amount = round(previous_cumulative_pnl + weekly_pnl_amount, 2)
        category = str(form.get(f"category_{index}", "other"))
        if category == "cash":
            weekly_pnl_amount = 0
            cumulative_pnl_amount = 0
        platform_return_rate_percent = _parse_optional_float(
            form.get(f"platform_return_rate_percent_{index}", "")
        )
        manual_holding_cost = _parse_optional_float(form.get(f"holding_cost_amount_{index}", ""))
        holding_cost_amount = _derive_holding_cost_amount(
            amount=amount,
            category=category,
            transaction_amount=transaction_amount,
            previous_amount=previous_amount,
            previous_holding_cost=previous_holding_cost,
            cumulative_pnl_amount=cumulative_pnl_amount,
            platform_return_rate_percent=platform_return_rate_percent,
            manual_holding_cost=manual_holding_cost,
        )
        holding_return_rate_percent = _holding_return_rate(amount, holding_cost_amount)
        holdings.append(
            HoldingInput(
                product_id=(
                    int(form[f"product_id_{index}"])
                    if str(form.get(f"product_id_{index}", "")).strip()
                    else None
                ),
                product_name=product_name,
                account_type=str(form.get(f"account_type_{index}", "")).strip() or "普通账户",
                management_role=str(form.get(f"management_role_{index}", "")) or None,
                comparison_group=str(form.get(f"comparison_group_{index}", "")) or None,
                amount=amount,
                allocation_percent=_parse_float(form.get(f"allocation_percent_{index}", 0)),
                category=category,
                action=str(form.get(f"action_{index}", "hold")),
                transaction_amount=transaction_amount,
                weekly_pnl_amount=weekly_pnl_amount,
                cumulative_pnl_amount=cumulative_pnl_amount,
                platform_return_rate_percent=platform_return_rate_percent or 0,
                holding_cost_amount=holding_cost_amount,
                holding_return_rate_percent=holding_return_rate_percent,
                valuation_cutoff_date=str(form.get(f"valuation_cutoff_date_{index}", "")),
                exposure_equity_percent=_parse_float(
                    form.get(f"exposure_equity_percent_{index}", 0)
                ),
                exposure_fixed_income_percent=_parse_float(
                    form.get(f"exposure_fixed_income_percent_{index}", 0)
                ),
                exposure_cash_percent=_parse_float(form.get(f"exposure_cash_percent_{index}", 0)),
                exposure_gold_percent=_parse_float(form.get(f"exposure_gold_percent_{index}", 0)),
                exposure_other_percent=_parse_float(form.get(f"exposure_other_percent_{index}", 0)),
                notes=str(form.get(f"holding_notes_{index}", "")),
            )
        )
    return holdings


def _parse_float(value) -> float:
    return float(value or 0)


def _parse_optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _derive_holding_cost_amount(
    *,
    amount: float,
    category: str,
    transaction_amount: float,
    previous_amount: float | None,
    previous_holding_cost: float | None,
    cumulative_pnl_amount: float,
    platform_return_rate_percent: float | None,
    manual_holding_cost: float | None,
) -> float:
    if category == "cash":
        return 0
    if platform_return_rate_percent is not None:
        denominator = 1 + platform_return_rate_percent / 100
        if denominator > 0:
            return round(amount / denominator, 2)
    if previous_holding_cost is not None:
        if transaction_amount >= 0:
            return round(max(previous_holding_cost + transaction_amount, 0), 2)
        if previous_amount and previous_amount > 0:
            redemption_ratio = min(abs(transaction_amount) / previous_amount, 1)
            return round(max(previous_holding_cost * (1 - redemption_ratio), 0), 2)
        return round(max(previous_holding_cost, 0), 2)
    if manual_holding_cost is not None:
        return round(max(manual_holding_cost, 0), 2)
    implied_cost = amount - cumulative_pnl_amount
    return round(implied_cost if implied_cost > 0 else amount, 2)


def _holding_return_rate(amount: float, holding_cost_amount: float) -> float:
    if holding_cost_amount <= 0:
        return 0
    return round(((amount - holding_cost_amount) / holding_cost_amount) * 100, 2)


def _build_form_values(snapshot, copy_as_new: bool = False) -> dict:
    if snapshot is None:
        return {
            "snapshot_id": "",
            "snapshot_date": "",
            "total_assets": "",
            "cash_balance": "",
            "weekly_return_amount": 0,
            "ytd_return_amount": 0,
            "external_net_flow_amount": "",
            "external_flow_confirmed": False,
            "data_cutoff_notes": "",
            "notes": "",
            "holdings": [
                {
                    "product_id": "",
                    "product_name": "",
                    "account_type": "普通账户",
                    "amount": "",
                    "allocation_percent": "",
                    "category": "equity",
                    "action": "hold",
                    "transaction_amount": 0,
                    "weekly_pnl_amount": 0,
                    "cumulative_pnl_amount": 0,
                    "platform_return_rate_percent": "",
                    "holding_cost_amount": "",
                    "holding_return_rate_percent": "",
                    "previous_amount": "",
                    "previous_cumulative_pnl_amount": "",
                    "previous_holding_cost_amount": "",
                    "valuation_cutoff_date": "",
                    "exposure_equity_percent": "",
                    "exposure_fixed_income_percent": "",
                    "exposure_cash_percent": "",
                    "exposure_gold_percent": "",
                    "exposure_other_percent": "",
                    "notes": "",
                }
            ],
        }

    return {
        "snapshot_id": "" if copy_as_new else snapshot.id,
        "snapshot_date": "" if copy_as_new else snapshot.snapshot_date,
        "total_assets": snapshot.total_assets,
        "cash_balance": snapshot.cash_balance,
        "weekly_return_amount": 0 if copy_as_new else snapshot.weekly_return_amount,
        "ytd_return_amount": 0 if copy_as_new else snapshot.ytd_return_amount,
        "external_net_flow_amount": (
            "" if copy_as_new else snapshot.external_net_flow_amount
        ),
        "external_flow_confirmed": (
            False if copy_as_new else snapshot.external_flow_confirmed
        ),
        "data_cutoff_notes": "" if copy_as_new else snapshot.data_cutoff_notes,
        "notes": "" if copy_as_new else snapshot.notes,
        "holdings": [
            {
                "product_id": holding.product_id,
                "product_name": holding.product_name,
                "account_type": holding.account_type,
                "amount": holding.amount,
                "allocation_percent": holding.allocation_percent,
                "category": holding.category,
                "action": "hold" if copy_as_new else holding.action,
                "transaction_amount": 0 if copy_as_new else holding.transaction_amount,
                "weekly_pnl_amount": 0 if copy_as_new else holding.weekly_pnl_amount,
                "cumulative_pnl_amount": holding.cumulative_pnl_amount,
                "platform_return_rate_percent": "" if copy_as_new else holding.platform_return_rate_percent,
                "holding_cost_amount": holding.holding_cost_amount,
                "holding_return_rate_percent": holding.holding_return_rate_percent,
                "previous_amount": holding.amount if copy_as_new else "",
                "previous_cumulative_pnl_amount": holding.cumulative_pnl_amount if copy_as_new else "",
                "previous_holding_cost_amount": holding.holding_cost_amount if copy_as_new else "",
                "valuation_cutoff_date": "" if copy_as_new else holding.valuation_cutoff_date,
                "exposure_equity_percent": holding.exposure_equity_percent,
                "exposure_fixed_income_percent": holding.exposure_fixed_income_percent,
                "exposure_cash_percent": holding.exposure_cash_percent,
                "exposure_gold_percent": holding.exposure_gold_percent,
                "exposure_other_percent": holding.exposure_other_percent,
                "notes": holding.notes,
            }
            for holding in snapshot.holdings
        ],
    }


def _sum_weekly_pnl(holdings: list[HoldingInput]) -> float:
    return round(sum(holding.weekly_pnl_amount for holding in holdings), 2)


def _sum_cumulative_pnl(holdings: list[HoldingInput]) -> float:
    return round(sum(holding.cumulative_pnl_amount for holding in holdings), 2)


def _sum_total_assets(holdings: list[HoldingInput]) -> float:
    return round(sum(holding.amount for holding in holdings), 2)


def _sum_cash_balance(holdings: list[HoldingInput]) -> float:
    return round(sum(holding.amount for holding in holdings if holding.category == "cash"), 2)
