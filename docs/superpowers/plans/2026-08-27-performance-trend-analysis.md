# 组合绩效与趋势观察 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有周度复盘系统中增加轻量外部净资金流确认、稳定产品身份、可解释的组合/产品绩效指标，以及独立的“趋势观察”页面。

**Architecture:** 保留现有 `PortfolioService` 的录入与复盘职责，新增无数据库依赖的 `app.analytics` 纯计算模块、产品档案服务和按需计算的 `PerformanceService`。SQLite 只持久化原始快照、资金流确认和产品元数据，净值、回撤、窗口收益、排名及状态在请求 `/analysis` 时由历史数据确定性重算。

**Tech Stack:** Python 3.12、FastAPI、Jinja2、Pydantic 2、SQLite、原生 HTML/CSS/JavaScript、`unittest`、Docker Compose。

**Spec:** `docs/superpowers/specs/2026-08-27-performance-trend-analysis-design.md`

## Global Constraints

- 时间窗口统一称为 4、8、12“期”，不称为严格自然周。
- 组合收益使用 `pnl / (prior_assets + 0.5 * external_net_flow)`；产品收益使用 `pnl / (prior_amount + 0.5 * transaction_amount)`。
- 净值基点固定为 1000；任何无效分母或不连续数据都不能用 0% 代替。
- 单期收益绝对值不超过 `0.05%` 视为持平，并中断连续上涨或下跌计数。
- 状态规则版本固定为 `trend-v1`；只对 `active_watch` 产品计算，且同一候选状态连续两期后才确认。
- 快照间隔 5 至 9 天视为标准周频；其他间隔仍算一期，但证据强度最高为“中”。
- `long_term`、`stable` 和 `liquidity` 产品不产生上行、下行、震荡或转折状态。
- 中证全指组合包不作为系统基准；`planned_exit` 期间仍观察，`exited` 后保留历史但退出当前排名。
- 第一阶段不引入行情接口、图表依赖、分析缓存表、逐笔资金流水或自动交易建议。
- 不硬编码具体产品名称到分析算法；现有产品角色通过账户类型/资产类别默认值和产品设置页面确认。
- 保持现有 JSON API 字段向后兼容；新增字段必须有可用默认值。
- 每个任务严格执行 RED → GREEN → 回归测试 → 独立提交。
- 3.57 属于本地调试环境；最终验证地址只能使用 `http://192.168.3.57:1103/`，不能使用带域名环境替代。

---

## File Structure

### 新增运行时代码

- `app/analytics/__init__.py`：分析包边界，不包含业务逻辑。
- `app/analytics/returns.py`：资金流推导、组合/产品单期收益、复合收益和净值链。
- `app/analytics/metrics.py`：高点、回撤、动量、连续涨跌和分周期排名。
- `app/analytics/classifier.py`：`trend-v1` 候选状态、两期确认和证据强度。
- `app/product_service.py`：产品档案查询、创建、默认角色推导和更新。
- `app/performance_service.py`：从历史快照构建连续序列并输出趋势页视图模型。
- `app/templates/analysis.html`：独立趋势观察页面。
- `app/templates/products.html`：产品角色、比较分组和生命周期维护页面。

### 修改运行时代码

- `app/db.py`：创建/迁移产品档案、持仓产品 ID 和快照资金流字段。
- `app/schemas.py`：新增产品类型与记录，扩展快照和持仓输入/输出。
- `app/service.py`：持久化资金流，写入产品 ID，提供上一期资产口径。
- `app/main.py`：初始化新服务，解析新增表单字段，注册 `/analysis` 与产品设置路由。
- `app/templates/index.html`：增加导航、外部净资金流确认和新产品元数据字段。
- `app/static/styles.css`：导航、产品设置、趋势卡片、SVG 净值图和响应式样式。
- `README.md`：更新功能、测试命令和 3.57 本地验证说明。

### 新增测试

- `tests/test_product_migration.py`
- `tests/test_product_service.py`
- `tests/test_returns.py`
- `tests/test_metrics.py`
- `tests/test_classifier.py`
- `tests/test_performance_service.py`

### 修改测试

- `tests/test_api.py`
- `tests/test_service.py`
- `tests/test_data_quality.py`
- `tests/test_demo_seeder.py`

---

### Task 1: 建立可重复执行的数据迁移

**Files:**
- Create: `tests/test_product_migration.py`
- Modify: `app/db.py:13-150`

**Interfaces:**
- Consumes: 现有 `Database.initialize() -> None` 和旧版三张 SQLite 表。
- Produces: `portfolio_products`、`holdings.product_id`、`weekly_snapshots.external_net_flow_amount`、`weekly_snapshots.external_flow_confirmed`；重复初始化保持数据不变。

- [ ] **Step 1: 写旧数据库迁移失败测试**

创建 `tests/test_product_migration.py`，先手工创建旧版最小表和两条持仓，再调用初始化：

```python
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db import Database


class ProductMigrationTests(unittest.TestCase):
    def test_initialize_backfills_products_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE weekly_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL UNIQUE,
                    total_assets REAL NOT NULL,
                    cash_balance REAL NOT NULL,
                    weekly_return_amount REAL NOT NULL DEFAULT 0,
                    ytd_return_amount REAL NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    product_name TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    allocation_percent REAL NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'hold',
                    notes TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO weekly_snapshots
                    (snapshot_date, total_assets, cash_balance)
                VALUES ('2026-08-21', 120000, 20000);
                INSERT INTO holdings
                    (snapshot_id, product_name, account_type, amount, allocation_percent, category)
                VALUES
                    (1, '养老金中证500增强', '养老金账户', 100000, 83.33, 'equity'),
                    (1, '现金', '货币/现金账户', 20000, 16.67, 'cash');
                """
            )
            connection.commit()
            connection.close()

            database = Database(path)
            database.initialize()
            database.initialize()

            with database.session() as migrated:
                products = migrated.execute(
                    "SELECT canonical_name, management_role FROM portfolio_products ORDER BY id"
                ).fetchall()
                missing = migrated.execute(
                    "SELECT COUNT(*) AS count FROM holdings WHERE product_id IS NULL"
                ).fetchone()["count"]
                snapshot_columns = {
                    row["name"] for row in migrated.execute(
                        "PRAGMA table_info(weekly_snapshots)"
                    ).fetchall()
                }

            self.assertEqual(len(products), 2)
            self.assertEqual(products[0]["management_role"], "long_term")
            self.assertEqual(products[1]["management_role"], "liquidity")
            self.assertEqual(missing, 0)
            self.assertIn("external_net_flow_amount", snapshot_columns)
            self.assertIn("external_flow_confirmed", snapshot_columns)
```

- [ ] **Step 2: 运行测试确认 RED**

```bash
python -m unittest tests.test_product_migration -v
```

Expected: FAIL，缺少 `portfolio_products` 或新增列。

- [ ] **Step 3: 实现表结构、列迁移和幂等回填**

在 `Database.connect()` 启用外键：

```python
connection.execute("PRAGMA foreign_keys = ON")
```

在 `initialize()` 的建表脚本中、`holdings` 之前增加：

```sql
CREATE TABLE IF NOT EXISTS portfolio_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    management_role TEXT NOT NULL,
    comparison_group TEXT NOT NULL DEFAULT 'other',
    lifecycle_status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(canonical_name, account_type)
);
```

同时把新安装场景的 `weekly_snapshots` CREATE TABLE 直接加入两个资金流字段，把 `holdings` CREATE TABLE 直接加入 `product_id INTEGER REFERENCES portfolio_products(id)`；下面的 ALTER 分支只服务旧数据库升级。

沿用现有 `PRAGMA table_info` 模式增加列：

```python
snapshot_columns = {
    row["name"]
    for row in connection.execute("PRAGMA table_info(weekly_snapshots)").fetchall()
}
if "external_net_flow_amount" not in snapshot_columns:
    connection.execute(
        "ALTER TABLE weekly_snapshots ADD COLUMN external_net_flow_amount REAL NULL"
    )
if "external_flow_confirmed" not in snapshot_columns:
    connection.execute(
        "ALTER TABLE weekly_snapshots "
        "ADD COLUMN external_flow_confirmed INTEGER NOT NULL DEFAULT 0"
    )

holding_columns = {
    row["name"]
    for row in connection.execute("PRAGMA table_info(holdings)").fetchall()
}
if "product_id" not in holding_columns:
    connection.execute(
        "ALTER TABLE holdings ADD COLUMN product_id INTEGER "
        "REFERENCES portfolio_products(id)"
    )
```

在所有旧持仓列补齐后执行幂等回填，默认角色不依赖产品名称：

```python
connection.execute(
    """
    INSERT OR IGNORE INTO portfolio_products (
        canonical_name, account_type, management_role, comparison_group, lifecycle_status
    )
    SELECT DISTINCT
        product_name,
        account_type,
        CASE
            WHEN account_type = '养老金账户' THEN 'long_term'
            WHEN category = 'cash' THEN 'liquidity'
            WHEN category = 'fixed_income' THEN 'stable'
            ELSE 'active_watch'
        END,
        'other',
        'active'
    FROM holdings
    """
)
connection.execute(
    """
    UPDATE holdings
    SET product_id = (
        SELECT p.id
        FROM portfolio_products AS p
        WHERE p.canonical_name = holdings.product_name
          AND p.account_type = holdings.account_type
    )
    WHERE product_id IS NULL
    """
)
```

- [ ] **Step 4: 运行迁移测试和现有数据库测试**

```bash
python -m unittest tests.test_product_migration tests.test_service tests.test_api -v
```

Expected: 全部 PASS；现有 API 仍可创建和读取快照。

- [ ] **Step 5: 提交迁移**

```bash
git add app/db.py tests/test_product_migration.py
git commit -m "feat: add product and cash-flow schema migration"
```

### Task 2: 增加产品档案模型与服务

**Files:**
- Create: `app/product_service.py`
- Create: `tests/test_product_service.py`
- Modify: `app/schemas.py:1-115`
- Modify: `app/service.py:1-430`

**Interfaces:**
- Consumes: Task 1 的 `portfolio_products` 和 `holdings.product_id`。
- Produces: `ProductService.list_products() -> list[ProductRecord]`、`ProductService.resolve_product(HoldingInput) -> int`、`ProductService.update_product(int, ProductUpdateInput) -> ProductRecord`；所有新持仓都有产品 ID。

- [ ] **Step 1: 写产品解析和更新失败测试**

创建 `tests/test_product_service.py`：

```python
import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.product_service import ProductService
from app.schemas import HoldingInput, ProductUpdateInput


class ProductServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "portfolio.db")
        self.database.initialize()
        self.service = ProductService(self.database)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_resolve_reuses_same_name_and_account(self) -> None:
        holding = HoldingInput(
            product_name="新宽基",
            account_type="普通账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
            management_role="active_watch",
            comparison_group="broad",
        )
        first_id = self.service.resolve_product(holding)
        second_id = self.service.resolve_product(holding)
        self.assertEqual(first_id, second_id)
        self.assertEqual(len(self.service.list_products()), 1)

    def test_default_role_uses_account_and_category(self) -> None:
        product_id = self.service.resolve_product(HoldingInput(
            product_name="养老金产品",
            account_type="养老金账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
        ))
        product = self.service.get_product(product_id)
        self.assertEqual(product.management_role, "long_term")

    def test_update_changes_metadata_without_changing_identity(self) -> None:
        product_id = self.service.resolve_product(HoldingInput(
            product_name="中证全指组合包",
            account_type="普通账户",
            amount=10000,
            allocation_percent=100,
            category="equity",
        ))
        updated = self.service.update_product(product_id, ProductUpdateInput(
            management_role="active_watch",
            comparison_group="broad",
            lifecycle_status="planned_exit",
        ))
        self.assertEqual(updated.id, product_id)
        self.assertEqual(updated.lifecycle_status, "planned_exit")
```

- [ ] **Step 2: 运行测试确认 RED**

```bash
python -m unittest tests.test_product_service -v
```

Expected: FAIL，产品类型和服务尚不存在。

- [ ] **Step 3: 定义产品与扩展持仓类型**

在 `app/schemas.py` 增加：

```python
ManagementRole = Literal["active_watch", "long_term", "stable", "liquidity"]
ComparisonGroup = Literal["broad", "star50", "hang_seng", "other"]
LifecycleStatus = Literal["active", "planned_exit", "exited"]


class ProductUpdateInput(BaseModel):
    management_role: ManagementRole
    comparison_group: ComparisonGroup = "other"
    lifecycle_status: LifecycleStatus = "active"


class ProductRecord(ProductUpdateInput):
    id: int
    canonical_name: str
    account_type: str
```

扩展 `HoldingInput` 和 `HoldingRecord`：

```python
class HoldingInput(BaseModel):
    product_id: int | None = None
    product_name: str = Field(min_length=1, max_length=100)
    account_type: str = Field(min_length=1, max_length=50)
    management_role: ManagementRole | None = None
    comparison_group: ComparisonGroup | None = None
    lifecycle_status: LifecycleStatus | None = None
    # 保留现有其余字段


class HoldingRecord(HoldingInput):
    id: int
    snapshot_id: int
```

更新 `holding_from_row()`，数据库旧行不存在页面元数据时只映射 `product_id`：

```python
product_id=int(row["product_id"]) if row["product_id"] is not None else None,
```

- [ ] **Step 4: 实现 ProductService**

创建 `app/product_service.py`，使用以下公开方法和默认规则：

```python
from app.db import Database
from app.schemas import HoldingInput, ProductRecord, ProductUpdateInput


class ProductService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_products(self) -> list[ProductRecord]:
        with self.database.session() as connection:
            rows = connection.execute(
                "SELECT * FROM portfolio_products ORDER BY account_type, canonical_name"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_product(self, product_id: int) -> ProductRecord:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_products WHERE id = ?", (product_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"Product {product_id} not found")
        return self._from_row(row)

    def resolve_product(self, holding: HoldingInput) -> int:
        if holding.product_id is not None:
            self.get_product(holding.product_id)
            return holding.product_id
        default_role = (
            "long_term" if holding.account_type == "养老金账户"
            else "liquidity" if holding.category == "cash"
            else "stable" if holding.category == "fixed_income"
            else "active_watch"
        )
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO portfolio_products (
                    canonical_name, account_type, management_role,
                    comparison_group, lifecycle_status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    holding.product_name,
                    holding.account_type,
                    holding.management_role or default_role,
                    holding.comparison_group or "other",
                    holding.lifecycle_status or "active",
                ),
            )
            row = connection.execute(
                """
                SELECT id FROM portfolio_products
                WHERE canonical_name = ? AND account_type = ?
                """,
                (holding.product_name, holding.account_type),
            ).fetchone()
        return int(row["id"])

    def update_product(
        self, product_id: int, payload: ProductUpdateInput
    ) -> ProductRecord:
        with self.database.session() as connection:
            cursor = connection.execute(
                """
                UPDATE portfolio_products
                SET management_role = ?, comparison_group = ?,
                    lifecycle_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    payload.management_role,
                    payload.comparison_group,
                    payload.lifecycle_status,
                    product_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Product {product_id} not found")
        return self.get_product(product_id)

    @staticmethod
    def _from_row(row) -> ProductRecord:
        return ProductRecord(
            id=int(row["id"]),
            canonical_name=str(row["canonical_name"]),
            account_type=str(row["account_type"]),
            management_role=str(row["management_role"]),
            comparison_group=str(row["comparison_group"]),
            lifecycle_status=str(row["lifecycle_status"]),
        )
```

- [ ] **Step 5: 在快照写事务开始前解析产品 ID**

在 `PortfolioService.__init__()` 创建 `ProductService`。`ProductService.resolve_product()` 会打开自己的数据库会话，因此必须在快照 INSERT/UPDATE 写事务开始前解析全部 ID，避免 SQLite 嵌套写连接锁库：

```python
self.product_service = ProductService(database)

resolved_holdings = [
    (holding, self.product_service.resolve_product(holding))
    for holding in payload.holdings
]
```

`create_snapshot()` 先构造 `resolved_holdings`，再进入 `with self.database.session()`。`update_snapshot()` 先调用 `self.get_snapshot(snapshot_id)` 完成存在性校验，再解析产品 ID，最后才进入更新写事务。循环调用改为：

```python
for holding, product_id in resolved_holdings:
    self._insert_holding(connection, snapshot_id, holding, product_id)
```

修改私有方法签名：

```python
def _insert_holding(
    self,
    connection,
    snapshot_id: int,
    holding: HoldingInput,
    product_id: int,
) -> None:
```

最后把 `product_id` 同时加入 holdings INSERT 的列清单、占位符和值元组。解析失败时尚未进入快照写事务，因此不能删除原持仓。

- [ ] **Step 6: 运行产品与 API 回归测试**

```bash
python -m unittest tests.test_product_service tests.test_product_migration tests.test_api -v
```

Expected: 全部 PASS，旧 JSON payload 仍可自动建立产品档案。

- [ ] **Step 7: 提交产品服务**

```bash
git add app/schemas.py app/product_service.py app/service.py tests/test_product_service.py
git commit -m "feat: add stable portfolio product profiles"
```

### Task 3: 持久化并确认外部净资金流

**Files:**
- Modify: `app/schemas.py`
- Modify: `app/service.py`
- Modify: `app/main.py`
- Modify: `app/templates/index.html`
- Modify: `app/static/styles.css`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 的快照资金流字段。
- Produces: `SnapshotCreateInput.external_net_flow_amount: float | None`、`SnapshotRecord.external_flow_confirmed: bool`、`PortfolioService.get_previous_total_assets(snapshot_id: int | None) -> float | None`；表单可接受系统估算并确认或修正。

- [ ] **Step 1: 写资金流持久化和表单失败测试**

在 `tests/test_service.py` 增加：

```python
def test_snapshot_uses_confirmed_external_flow(self) -> None:
    snapshot = self.service.create_snapshot(SnapshotCreateInput(
        snapshot_date="2026-08-21",
        total_assets=110000,
        cash_balance=10000,
        weekly_return_amount=2000,
        external_net_flow_amount=8000,
        external_flow_confirmed=True,
        holdings=[],
    ))
    self.assertEqual(snapshot.external_net_flow_amount, 8000)
    self.assertTrue(snapshot.external_flow_confirmed)
```

在 `tests/test_api.py` 增加一个两期表单测试：

```python
def test_snapshot_form_persists_confirmed_external_flow(self) -> None:
    response = self.client.post("/snapshots", data={
        "snapshot_date": "2026-08-21",
        "external_net_flow_amount": "8000",
        "external_flow_confirmed": "1",
        "product_name_0": "现金",
        "account_type_0": "货币/现金账户",
        "amount_0": "110000",
        "allocation_percent_0": "100",
        "category_0": "cash",
        "action_0": "hold",
    }, follow_redirects=False)
    self.assertEqual(response.status_code, 303)
    snapshot = self.client.get("/api/weekly-snapshots").json()[0]
    self.assertEqual(snapshot["external_net_flow_amount"], 8000)
    self.assertTrue(snapshot["external_flow_confirmed"])

    copied = self.client.get(f"/?copy_id={snapshot['id']}")
    self.assertIn('name="external_net_flow_amount" value=""', copied.text)
    self.assertNotIn('name="external_flow_confirmed" value="1" checked', copied.text)
```

- [ ] **Step 2: 运行目标测试确认 RED**

```bash
python -m unittest \
  tests.test_service.PortfolioServiceTests.test_snapshot_uses_confirmed_external_flow \
  tests.test_api.ApiTests.test_snapshot_form_persists_confirmed_external_flow -v
```

Expected: FAIL，Pydantic 类型和页面字段尚不存在。

- [ ] **Step 3: 扩展快照 schema、SQL 和现金流读取**

在 `SnapshotCreateInput` 和 `SnapshotRecord` 增加：

```python
external_net_flow_amount: float | None = None
external_flow_confirmed: bool = False
```

在 `snapshot_from_row()` 映射：

```python
external_net_flow_amount=(
    float(row["external_net_flow_amount"])
    if row["external_net_flow_amount"] is not None
    else None
),
external_flow_confirmed=bool(row["external_flow_confirmed"]),
```

在 `create_snapshot()`、`update_snapshot()` 的 SQL 和参数中写入两个字段。更新 `get_cashflow_analysis()`，优先使用已存值，否则推导：

```python
inferred = round(
    latest.total_assets - previous.total_assets - latest.weekly_return_amount, 2
)
net_flow = (
    latest.external_net_flow_amount
    if latest.external_net_flow_amount is not None
    else inferred
)
source = (
    "confirmed"
    if latest.external_flow_confirmed and latest.external_net_flow_amount is not None
    else "estimated"
)
```

新增上一期资产查询：

```python
def get_previous_total_assets(self, snapshot_id: int | None = None) -> float | None:
    with self.database.session() as connection:
        if snapshot_id is None:
            row = connection.execute(
                "SELECT total_assets FROM weekly_snapshots ORDER BY snapshot_date DESC LIMIT 1"
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT total_assets FROM weekly_snapshots
                WHERE snapshot_date < (
                    SELECT snapshot_date FROM weekly_snapshots WHERE id = ?
                )
                ORDER BY snapshot_date DESC LIMIT 1
                """,
                (snapshot_id,),
            ).fetchone()
    return float(row["total_assets"]) if row is not None else None
```

- [ ] **Step 4: 解析表单并保证复制时重置**

在创建 payload 时加入：

```python
external_net_flow_amount=_parse_optional_float(
    form.get("external_net_flow_amount", "")
),
external_flow_confirmed=form.get("external_flow_confirmed") == "1",
```

扩展 `_build_form_values()`：

```python
"external_net_flow_amount": (
    "" if copy_as_new else snapshot.external_net_flow_amount
),
"external_flow_confirmed": (
    False if copy_as_new else snapshot.external_flow_confirmed
),
```

对空白新表单使用 `""` 和 `False`。Dashboard context 传入 `previous_total_assets`；复制时使用源快照总资产，编辑时使用 `get_previous_total_assets(edit_id)`，普通新建使用最新快照总资产。

- [ ] **Step 5: 增加资金流确认控件和自动估算**

在“本周总览”中加入：

```html
<label>
  <span>外部净资金流</span>
  <input type="number" step="0.01" name="external_net_flow_amount"
         id="external-net-flow-input"
         value="{{ form_values.external_net_flow_amount }}" />
</label>
<label class="flow-confirmation">
  <span>资金流口径</span>
  <span class="checkbox-row">
    <input type="checkbox" name="external_flow_confirmed" value="1"
           id="external-flow-confirmed"
           {% if form_values.external_flow_confirmed %}checked{% endif %} />
    已核对本期净转入/转出
  </span>
</label>
<input type="hidden" id="previous-total-assets"
       value="{{ previous_total_assets if previous_total_assets is not none else '' }}" />
```

在现有重算脚本中加入：

```javascript
const externalFlowInput = document.getElementById("external-net-flow-input");
const externalFlowConfirmed = document.getElementById("external-flow-confirmed");
const previousTotalAssetsInput = document.getElementById("previous-total-assets");

function recalculateExternalFlow() {
  if (!externalFlowInput || externalFlowConfirmed?.checked) return;
  const previous = Number(previousTotalAssetsInput?.value || NaN);
  const total = Number(totalAssetsInput?.value || 0);
  const pnl = Number(weeklyReturnInput?.value || 0);
  externalFlowInput.value = Number.isFinite(previous)
    ? (total - previous - pnl).toFixed(2)
    : "";
}
```

每次 `recalculateSnapshotTotals()` 和 `recalculateWeeklyReturn()` 后调用该函数；复制草稿不能带入上期资金流或确认状态。

- [ ] **Step 6: 运行资金流测试与完整 API 测试**

```bash
python -m unittest tests.test_service tests.test_api -v
```

Expected: 全部 PASS；页面包含估算输入和确认状态，JSON API 返回新增字段。

- [ ] **Step 7: 提交资金流功能**

```bash
git add app/schemas.py app/service.py app/main.py app/templates/index.html app/static/styles.css tests/test_service.py tests/test_api.py
git commit -m "feat: confirm external cash flow per snapshot"
```

### Task 4: 实现收益与净值纯计算模块

**Files:**
- Create: `app/analytics/__init__.py`
- Create: `app/analytics/returns.py`
- Create: `tests/test_returns.py`

**Interfaces:**
- Produces: `infer_external_flow()`、`modified_dietz_return()`、`product_period_return()`、`compound_return()`、`chain_nav()`；函数不访问数据库且不做展示层四舍五入。

- [ ] **Step 1: 写公式和边界失败测试**

创建 `tests/test_returns.py`：

```python
import unittest

from app.analytics.returns import (
    chain_nav,
    compound_return,
    infer_external_flow,
    modified_dietz_return,
    product_period_return,
)


class ReturnTests(unittest.TestCase):
    def test_infers_external_flow(self) -> None:
        self.assertEqual(infer_external_flow(110000, 100000, 2000), 8000)

    def test_modified_dietz_uses_half_flow_weight(self) -> None:
        self.assertAlmostEqual(modified_dietz_return(2000, 100000, 8000), 2000 / 104000)

    def test_invalid_denominator_returns_none(self) -> None:
        self.assertIsNone(modified_dietz_return(100, 0, 0))
        self.assertIsNone(product_period_return(100, 0, 1000, True))

    def test_product_return_requires_contiguous_observation(self) -> None:
        self.assertIsNone(product_period_return(100, 10000, 0, False))
        self.assertAlmostEqual(product_period_return(100, 10000, 2000, True), 100 / 11000)

    def test_compound_return_requires_exact_window(self) -> None:
        self.assertAlmostEqual(compound_return([0.1, -0.05], 2), 0.045)
        self.assertIsNone(compound_return([0.1], 2))
        self.assertIsNone(compound_return([0.1, None], 2))

    def test_nav_chain_stops_after_invalid_period(self) -> None:
        self.assertEqual(chain_nav([0.1, -0.05], 1000), [1000, 1100, 1045])
        self.assertEqual(chain_nav([0.1, None, 0.2], 1000), [1000, 1100, None, None])
```

- [ ] **Step 2: 运行测试确认 RED**

```bash
python -m unittest tests.test_returns -v
```

Expected: FAIL，分析包尚不存在。

- [ ] **Step 3: 实现最小纯函数**

创建空的 `app/analytics/__init__.py`，并在 `returns.py` 写入：

```python
from __future__ import annotations

from math import prod


def infer_external_flow(current_assets: float, prior_assets: float, pnl: float) -> float:
    return current_assets - prior_assets - pnl


def modified_dietz_return(
    pnl: float, prior_assets: float, external_net_flow: float
) -> float | None:
    denominator = prior_assets + 0.5 * external_net_flow
    return pnl / denominator if denominator > 0 else None


def product_period_return(
    pnl: float,
    prior_amount: float,
    transaction_amount: float,
    contiguous: bool,
) -> float | None:
    if not contiguous or prior_amount <= 0:
        return None
    denominator = prior_amount + 0.5 * transaction_amount
    return pnl / denominator if denominator > 0 else None


def compound_return(values: list[float | None], periods: int) -> float | None:
    window = values[-periods:]
    if len(window) != periods or any(value is None for value in window):
        return None
    return prod(1 + float(value) for value in window) - 1


def chain_nav(values: list[float | None], base: float = 1000) -> list[float | None]:
    result: list[float | None] = [base]
    current: float | None = base
    for value in values:
        current = None if current is None or value is None else current * (1 + value)
        result.append(current)
    return result
```

- [ ] **Step 4: 运行纯计算测试**

```bash
python -m unittest tests.test_returns -v
```

Expected: 6 tests PASS。

- [ ] **Step 5: 提交收益模块**

```bash
git add app/analytics/__init__.py app/analytics/returns.py tests/test_returns.py
git commit -m "feat: add return and nav calculations"
```

### Task 5: 实现回撤、动量、连续期数和排名

**Files:**
- Create: `app/analytics/metrics.py`
- Create: `tests/test_metrics.py`

**Interfaces:**
- Consumes: Task 4 输出的未舍入收益和净值。
- Produces: `drawdown_stats()`、`momentum_delta()`、`streak()`、`rank_horizon()`。

- [ ] **Step 1: 写指标失败测试**

创建 `tests/test_metrics.py`：

```python
import unittest

from app.analytics.metrics import drawdown_stats, momentum_delta, rank_horizon, streak


class MetricTests(unittest.TestCase):
    def test_drawdown_reports_high_current_and_maximum(self) -> None:
        stats = drawdown_stats([1000, 1100, 990, 1050], ["d0", "d1", "d2", "d3"])
        self.assertEqual(stats["high_date"], "d1")
        self.assertAlmostEqual(stats["current_drawdown"], 1050 / 1100 - 1)
        self.assertAlmostEqual(stats["max_drawdown"], 990 / 1100 - 1)

    def test_momentum_compares_recent_and_previous_four(self) -> None:
        result = momentum_delta([0.01] * 4 + [0.02] * 4)
        self.assertGreater(result["delta"], 0)
        self.assertEqual(result["direction"], "strengthening")

    def test_flat_period_breaks_streak(self) -> None:
        self.assertEqual(streak([0.01, 0.02, 0.0005]), ("flat", 0))
        self.assertEqual(streak([-0.01, -0.02]), ("down", 2))

    def test_rank_requires_two_available_products(self) -> None:
        rows = rank_horizon([("A", 0.04), ("B", 0.02), ("C", None)])
        self.assertEqual(rows, [("A", 0.04, 1), ("B", 0.02, 2)])
        self.assertEqual(rank_horizon([("A", 0.04)]), [])
```

- [ ] **Step 2: 运行测试确认 RED**

```bash
python -m unittest tests.test_metrics -v
```

Expected: FAIL，`metrics.py` 不存在。

- [ ] **Step 3: 实现指标函数**

在 `app/analytics/metrics.py` 写入：

```python
from __future__ import annotations

from app.analytics.returns import compound_return


def drawdown_stats(nav_values: list[float], dates: list[str]) -> dict[str, float | str]:
    peak = nav_values[0]
    peak_date = dates[0]
    max_drawdown = 0.0
    for nav, date in zip(nav_values, dates, strict=True):
        if nav > peak:
            peak, peak_date = nav, date
        max_drawdown = min(max_drawdown, nav / peak - 1)
    return {
        "high_nav": peak,
        "high_date": peak_date,
        "current_drawdown": nav_values[-1] / peak - 1,
        "max_drawdown": max_drawdown,
    }


def momentum_delta(values: list[float | None]) -> dict[str, float | str] | None:
    if len(values) < 8:
        return None
    previous = compound_return(values[-8:-4], 4)
    recent = compound_return(values[-4:], 4)
    if previous is None or recent is None:
        return None
    delta = recent - previous
    return {
        "previous_4": previous,
        "recent_4": recent,
        "delta": delta,
        "direction": "strengthening" if delta > 0 else "weakening" if delta < 0 else "flat",
    }


def streak(values: list[float | None], threshold: float = 0.0005) -> tuple[str, int]:
    count = 0
    direction = "flat"
    for value in reversed(values):
        current = "up" if value is not None and value > threshold else (
            "down" if value is not None and value < -threshold else "flat"
        )
        if current == "flat" or (direction != "flat" and current != direction):
            break
        direction = current
        count += 1
    return direction, count


def rank_horizon(
    values: list[tuple[str, float | None]],
) -> list[tuple[str, float, int]]:
    available = [(name, value) for name, value in values if value is not None]
    if len(available) < 2:
        return []
    ordered = sorted(available, key=lambda item: float(item[1]), reverse=True)
    return [(name, float(value), index + 1) for index, (name, value) in enumerate(ordered)]
```

- [ ] **Step 4: 运行指标测试**

```bash
python -m unittest tests.test_metrics -v
```

Expected: 4 tests PASS。

- [ ] **Step 5: 提交指标模块**

```bash
git add app/analytics/metrics.py tests/test_metrics.py
git commit -m "feat: add performance metric calculations"
```

### Task 6: 实现 trend-v1 状态分类器

**Files:**
- Create: `app/analytics/classifier.py`
- Create: `tests/test_classifier.py`

**Interfaces:**
- Consumes: 最近 4/8/12 期收益、候选状态历史、间隔质量和相对/动量支持。
- Produces: `candidate_state(r4, r8) -> CandidateState`、`confirm_candidate_history(list[CandidateState]) -> Confirmation`、`evidence_strength(...) -> str`。

- [ ] **Step 1: 写状态边界和确认失败测试**

创建 `tests/test_classifier.py`：

```python
import unittest

from app.analytics.classifier import (
    CandidateState,
    candidate_state,
    confirm_candidate_history,
    evidence_strength,
)


class ClassifierTests(unittest.TestCase):
    def test_candidate_rule_priority(self) -> None:
        self.assertEqual(candidate_state(0.02, -0.005).code, "turning")
        self.assertEqual(candidate_state(0.02, 0.01).code, "up")
        self.assertEqual(candidate_state(-0.02, -0.01).code, "down")
        self.assertEqual(candidate_state(0.005, 0.002).code, "sideways")

    def test_exact_one_percent_does_not_cross_strict_up_threshold(self) -> None:
        self.assertEqual(candidate_state(0.01, 0.005).code, "sideways")

    def test_confirmation_requires_two_equal_candidates(self) -> None:
        history = [CandidateState("up", ""), CandidateState("up", "")]
        result = confirm_candidate_history(history)
        self.assertEqual(result.confirmed, "up")
        self.assertFalse(result.pending)

        pending = confirm_candidate_history(history + [CandidateState("down", "")])
        self.assertEqual(pending.confirmed, "up")
        self.assertTrue(pending.pending)

        opposite_turns = confirm_candidate_history([
            CandidateState("turning", "weak_to_strong"),
            CandidateState("turning", "strong_to_weak"),
        ])
        self.assertIsNone(opposite_turns.confirmed)
        self.assertTrue(opposite_turns.pending)

    def test_irregular_interval_caps_evidence_at_medium(self) -> None:
        self.assertEqual(evidence_strength(
            confirmed=True,
            periods=12,
            directional_agreement=True,
            supporting_signal=True,
            has_quality_issue=False,
            has_irregular_interval=True,
        ), "medium")
```

- [ ] **Step 2: 运行测试确认 RED**

```bash
python -m unittest tests.test_classifier -v
```

Expected: FAIL，分类器尚不存在。

- [ ] **Step 3: 实现分类器和证据规则**

在 `app/analytics/classifier.py` 写入：

```python
from __future__ import annotations

from dataclasses import dataclass

RULE_VERSION = "trend-v1"


@dataclass(frozen=True)
class CandidateState:
    code: str
    detail: str


@dataclass(frozen=True)
class Confirmation:
    confirmed: str | None
    confirmed_detail: str
    candidate: str
    candidate_detail: str
    pending: bool


def candidate_state(r4: float, r8: float) -> CandidateState:
    if r4 * r8 < 0 and abs(r4 - r8) >= 0.01:
        detail = "weak_to_strong" if r4 > 0 else "strong_to_weak"
        return CandidateState("turning", detail)
    if r4 > 0.01 and r8 > 0:
        return CandidateState("up", "")
    if r4 < -0.01 and r8 < 0:
        return CandidateState("down", "")
    return CandidateState("sideways", "")


def confirm_candidate_history(history: list[CandidateState]) -> Confirmation:
    confirmed: CandidateState | None = None
    for index in range(1, len(history)):
        if history[index] == history[index - 1]:
            confirmed = history[index]
    current = history[-1]
    pending = len(history) < 2 or history[-2] != current
    return Confirmation(
        confirmed.code if confirmed else None,
        confirmed.detail if confirmed else "",
        current.code,
        current.detail,
        pending,
    )


def evidence_strength(
    *,
    confirmed: bool,
    periods: int,
    directional_agreement: bool,
    supporting_signal: bool,
    has_quality_issue: bool,
    has_irregular_interval: bool,
) -> str:
    if not confirmed or has_quality_issue:
        return "low"
    strength = "medium"
    if periods >= 12 and directional_agreement and supporting_signal:
        strength = "high"
    return "medium" if has_irregular_interval and strength == "high" else strength
```

- [ ] **Step 4: 运行分类器测试**

```bash
python -m unittest tests.test_classifier -v
```

Expected: 4 tests PASS。

- [ ] **Step 5: 提交分类器**

```bash
git add app/analytics/classifier.py tests/test_classifier.py
git commit -m "feat: add explainable trend classifier"
```

### Task 7: 组织历史序列并生成趋势视图模型

**Files:**
- Create: `app/performance_service.py`
- Create: `tests/test_performance_service.py`
- Modify: `app/service.py`

**Interfaces:**
- Consumes: `PortfolioService.list_snapshots()`、`ProductService.list_products()`、Tasks 4–6 的纯函数。
- Produces: `PerformanceService.get_analysis() -> dict`，固定包含 `rule_version`、`portfolio`、`active_products`、`comparison`、`objective_products`、`exited_products`。

- [ ] **Step 1: 写组合、角色和退出产品失败测试**

创建 `tests/test_performance_service.py`，辅助方法按连续日期生成 12 期数据：

```python
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app.db import Database
from app.performance_service import PerformanceService
from app.product_service import ProductService
from app.schemas import HoldingInput, ProductUpdateInput, SnapshotCreateInput
from app.service import PortfolioService


class PerformanceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "portfolio.db")
        self.database.initialize()
        self.portfolios = PortfolioService(self.database)
        self.products = ProductService(self.database)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def add_snapshot(self, index: int, amount: float, pnl: float = 1000) -> None:
        self.portfolios.create_snapshot(SnapshotCreateInput(
            snapshot_date=str(date(2026, 5, 1) + timedelta(days=7 * index)),
            total_assets=amount,
            cash_balance=0,
            weekly_return_amount=pnl,
            external_net_flow_amount=0,
            external_flow_confirmed=True,
            holdings=[HoldingInput(
                product_name="观察宽基",
                account_type="普通账户",
                amount=amount,
                allocation_percent=100,
                category="equity",
                transaction_amount=0,
                weekly_pnl_amount=pnl,
                management_role="active_watch",
                comparison_group="broad",
            )],
        ))

    def test_builds_portfolio_and_active_product_metrics(self) -> None:
        for index in range(13):
            self.add_snapshot(index, 100000 + index * 1000)
        result = PerformanceService(self.database).get_analysis()
        self.assertEqual(result["rule_version"], "trend-v1")
        self.assertTrue(result["portfolio"]["available"])
        self.assertEqual(result["portfolio"]["nav_points"][0]["nav"], 1000)
        self.assertEqual(len(result["active_products"]), 1)
        self.assertIsNotNone(result["active_products"][0]["returns"][12])
        self.assertIn(result["active_products"][0]["confirmed_state"], {"up", "sideways"})

    def test_long_term_has_metrics_but_no_state(self) -> None:
        for index in range(9):
            self.add_snapshot(index, 100000 + index * 1000)
        product = self.products.list_products()[0]
        self.products.update_product(product.id, ProductUpdateInput(
            management_role="long_term",
            comparison_group="broad",
            lifecycle_status="active",
        ))
        result = PerformanceService(self.database).get_analysis()
        self.assertEqual(result["active_products"], [])
        self.assertEqual(len(result["objective_products"]), 1)
        self.assertNotIn("confirmed_state", result["objective_products"][0])

    def test_exited_product_keeps_history_and_leaves_ranking(self) -> None:
        for index in range(9):
            self.add_snapshot(index, 100000 + index * 1000)
        product = self.products.list_products()[0]
        self.products.update_product(product.id, ProductUpdateInput(
            management_role="active_watch",
            comparison_group="broad",
            lifecycle_status="exited",
        ))
        result = PerformanceService(self.database).get_analysis()
        self.assertEqual(result["active_products"], [])
        self.assertEqual(len(result["exited_products"]), 1)
```

- [ ] **Step 2: 运行服务测试确认 RED**

```bash
python -m unittest tests.test_performance_service -v
```

Expected: FAIL，`PerformanceService` 尚不存在。

- [ ] **Step 3: 增加时间升序读取接口**

在 `PortfolioService` 增加一个不改变现有倒序列表行为的方法：

```python
def list_snapshots_chronologically(self) -> list[SnapshotRecord]:
    return list(reversed(self.list_snapshots()))
```

- [ ] **Step 4: 实现 PerformanceService 的固定输出契约**

创建 `app/performance_service.py`。公开入口和空状态必须精确如下：

```python
from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.analytics.classifier import (
    RULE_VERSION,
    candidate_state,
    confirm_candidate_history,
    evidence_strength,
)
from app.analytics.metrics import drawdown_stats, momentum_delta, rank_horizon, streak
from app.analytics.returns import (
    chain_nav,
    compound_return,
    infer_external_flow,
    modified_dietz_return,
    product_period_return,
)
from app.db import Database
from app.product_service import ProductService
from app.service import PortfolioService


class PerformanceService:
    def __init__(self, database: Database) -> None:
        self.portfolios = PortfolioService(database)
        self.products = ProductService(database)

    def get_analysis(self) -> dict:
        snapshots = self.portfolios.list_snapshots_chronologically()
        if not snapshots:
            return {
                "rule_version": RULE_VERSION,
                "portfolio": {"available": False, "nav_points": [], "quality": []},
                "active_products": [],
                "comparison": {4: [], 8: [], 12: []},
                "objective_products": [],
                "exited_products": [],
            }
        portfolio = self._portfolio_view(snapshots)
        product_views = self._product_views(snapshots)
        active = [item for item in product_views if item["role"] == "active_watch" and item["lifecycle"] != "exited"]
        objective = [item for item in product_views if item["role"] in {"long_term", "stable"} and item["lifecycle"] != "exited"]
        exited = [item for item in product_views if item["lifecycle"] == "exited"]
        return {
            "rule_version": RULE_VERSION,
            "portfolio": portfolio,
            "active_products": active,
            "comparison": {
                period: rank_horizon([
                    (item["name"], item["returns"][period]) for item in active
                ])
                for period in (4, 8, 12)
            },
            "objective_products": objective,
            "exited_products": exited,
        }
```

`_portfolio_view()` 必须：按相邻快照动态采用已存资金流或 `infer_external_flow()`；生成 Modified Dietz 收益；从 1000 链接净值；遇到首个 `None` 后不恢复净值链，也不跨越无效期计算回撤；把未确认资金流、无效分母和非标准间隔写入 `quality`；返回 `chart_points` 供 SVG 使用。

返回结构使用以下键：

```python
return {
    "available": len(valid_nav) >= 2,
    "nav_points": nav_points,
    "chart_points": " ".join(f"{point['x']},{point['y']}" for point in nav_points if point["nav"] is not None),
    "cumulative_return": valid_nav[-1] / valid_nav[0] - 1 if len(valid_nav) >= 2 else None,
    "current_drawdown": drawdowns.get("current_drawdown"),
    "max_drawdown": drawdowns.get("max_drawdown"),
    "high_date": drawdowns.get("high_date"),
    "latest_flow": latest_flow,
    "latest_flow_source": latest_flow_source,
    "quality": quality,
}
```

SVG 坐标只使用从基点开始的连续有效净值。横轴均匀分布在 20–980，纵轴把最低/最高净值映射到 230–30；只有一个有效点时放在 `(20, 130)`：

```python
def _chart_coordinates(nav_values: list[float]) -> list[tuple[float, float]]:
    if len(nav_values) == 1:
        return [(20.0, 130.0)]
    low, high = min(nav_values), max(nav_values)
    span = high - low
    return [
        (
            20 + index * 960 / (len(nav_values) - 1),
            130.0 if span == 0 else 230 - (nav - low) * 200 / span,
        )
        for index, nav in enumerate(nav_values)
    ]
```

`_portfolio_view()` 的实现体使用以下顺序，保证无效期之后不会重新接链：

```python
def _portfolio_view(self, snapshots) -> dict:
    period_returns: list[float | None] = []
    flow_rows: list[tuple[float, str]] = []
    quality: list[str] = []
    for index in range(1, len(snapshots)):
        previous, current = snapshots[index - 1], snapshots[index]
        interval = (
            date.fromisoformat(current.snapshot_date)
            - date.fromisoformat(previous.snapshot_date)
        ).days
        if not 5 <= interval <= 9:
            quality.append(f"{current.snapshot_date} 与上期相隔 {interval} 天")
        inferred = infer_external_flow(
            current.total_assets,
            previous.total_assets,
            current.weekly_return_amount,
        )
        flow = (
            current.external_net_flow_amount
            if current.external_net_flow_amount is not None
            else inferred
        )
        source = (
            "confirmed"
            if current.external_flow_confirmed and current.external_net_flow_amount is not None
            else "estimated"
        )
        if source == "estimated":
            quality.append(f"{current.snapshot_date} 外部净资金流尚未确认")
        value = modified_dietz_return(
            current.weekly_return_amount,
            previous.total_assets,
            flow,
        )
        if value is None:
            quality.append(f"{current.snapshot_date} 组合收益分母无效")
        period_returns.append(value)
        flow_rows.append((flow, source))

    nav_values = chain_nav(period_returns, 1000)
    valid_nav = [value for value in nav_values if value is not None]
    coordinates = _chart_coordinates(valid_nav)
    nav_points = []
    coordinate_index = 0
    for snapshot, nav in zip(snapshots, nav_values, strict=True):
        point = {"date": snapshot.snapshot_date, "nav": nav}
        if nav is not None:
            point["x"], point["y"] = coordinates[coordinate_index]
            coordinate_index += 1
        nav_points.append(point)

    stats = (
        drawdown_stats(
            valid_nav,
            [point["date"] for point in nav_points if point["nav"] is not None],
        )
        if len(valid_nav) >= 2
        else {}
    )
    latest_flow, latest_source = flow_rows[-1] if flow_rows else (None, "unavailable")
    return {
        "available": len(valid_nav) >= 2,
        "nav_points": nav_points,
        "chart_points": " ".join(
            f"{point['x']:.2f},{point['y']:.2f}"
            for point in nav_points if point["nav"] is not None
        ),
        "cumulative_return": valid_nav[-1] / valid_nav[0] - 1 if len(valid_nav) >= 2 else None,
        "current_drawdown": stats.get("current_drawdown"),
        "max_drawdown": stats.get("max_drawdown"),
        "high_date": stats.get("high_date"),
        "latest_flow": latest_flow,
        "latest_flow_source": latest_source,
        "quality": quality,
    }
```

`_product_views()` 必须按 `product_id` 分组，并且只有产品同时出现在相邻组合快照且上期金额大于 0 时才调用 `product_period_return(..., contiguous=True)`。缺期和零金额后的重新建仓产生 `None`，从而中断 4/8/12 窗口。每个产品视图返回：

```python
{
    "id": product.id,
    "name": product.canonical_name,
    "account_type": product.account_type,
    "role": product.management_role,
    "group": product.comparison_group,
    "lifecycle": product.lifecycle_status,
    "returns": {period: compound_return(period_returns, period) for period in (4, 8, 12)},
    "current_drawdown": product_drawdown,
    "high_date": product_high_date,
    "momentum": momentum_delta(period_returns),
    "streak": streak(period_returns),
    "data_status": data_status,
}
```

仅当角色为 `active_watch` 且有至少 8 个连续有效收益时，再加入：

```python
view.update({
    "candidate_state": confirmation.candidate,
    "confirmed_state": confirmation.confirmed,
    "pending": confirmation.pending,
    "evidence": strength,
})
```

候选历史要从该产品所有达到 8 期条件的历史窗口逐期计算，而不是只计算最新两期。第一阶段用动量方向作为 `supporting_signal`：上行或由弱转强且动量增强、下行或由强转弱且动量减弱时为真；震荡不因排名获得“高”证据。排名只负责页面相对比较，避免在产品视图与排名之间形成循环依赖。

`_product_views()` 使用下列完整连续段算法；`None` 之前的历史仍保留，但最新窗口只从最后一个 `None` 之后重新积累：

```python
def _product_views(self, snapshots) -> list[dict]:
    profiles = {product.id: product for product in self.products.list_products()}
    observations: dict[int, dict[int, object]] = defaultdict(dict)
    for snapshot_index, snapshot in enumerate(snapshots):
        for holding in snapshot.holdings:
            if holding.product_id is not None:
                observations[holding.product_id][snapshot_index] = holding

    views: list[dict] = []
    for product_id, rows in observations.items():
        product = profiles.get(product_id)
        if product is None or product.management_role == "liquidity":
            continue
        first_index = min(rows)
        end_index = max(rows) if product.lifecycle_status == "exited" else len(snapshots) - 1
        returns: list[float | None] = []
        return_dates: list[str] = []
        standard_intervals: list[bool] = []
        for index in range(first_index + 1, end_index + 1):
            previous = rows.get(index - 1)
            current = rows.get(index)
            contiguous = previous is not None and current is not None
            value = product_period_return(
                current.weekly_pnl_amount if current is not None else 0,
                previous.amount if previous is not None else 0,
                current.transaction_amount if current is not None else 0,
                contiguous,
            )
            interval = (
                date.fromisoformat(snapshots[index].snapshot_date)
                - date.fromisoformat(snapshots[index - 1].snapshot_date)
            ).days
            returns.append(value)
            return_dates.append(snapshots[index].snapshot_date)
            standard_intervals.append(5 <= interval <= 9)

        last_gap = max(
            (index for index, value in enumerate(returns) if value is None),
            default=-1,
        )
        continuous_returns = returns[last_gap + 1:]
        continuous_dates = return_dates[last_gap + 1:]
        continuous_intervals = standard_intervals[last_gap + 1:]
        base_date_index = first_index + last_gap + 1
        nav_values = chain_nav(continuous_returns, 1000)
        nav_dates = [snapshots[base_date_index].snapshot_date, *continuous_dates]
        stats = drawdown_stats(nav_values, nav_dates) if len(nav_values) >= 2 else {}
        windows = {
            period: compound_return(continuous_returns, period)
            for period in (4, 8, 12)
        }
        momentum = momentum_delta(continuous_returns)
        latest_pair_exists = end_index in rows and end_index - 1 in rows
        data_status = (
            "discontinuous" if end_index not in rows
            else "unavailable" if returns and returns[-1] is None and latest_pair_exists
            else "accumulating" if len(continuous_returns) < 4
            else "available"
        )
        view = {
            "id": product.id,
            "name": product.canonical_name,
            "account_type": product.account_type,
            "role": product.management_role,
            "group": product.comparison_group,
            "lifecycle": product.lifecycle_status,
            "returns": windows,
            "current_drawdown": stats.get("current_drawdown"),
            "high_date": stats.get("high_date"),
            "momentum": momentum,
            "streak": streak(continuous_returns),
            "data_status": data_status,
        }

        if product.management_role == "active_watch" and len(continuous_returns) >= 8:
            candidates = []
            for end in range(8, len(continuous_returns) + 1):
                history = continuous_returns[:end]
                r4 = compound_return(history, 4)
                r8 = compound_return(history, 8)
                if r4 is not None and r8 is not None:
                    candidates.append(candidate_state(r4, r8))
            confirmation = confirm_candidate_history(candidates)
            current_candidate = candidates[-1]
            r4, r8 = windows[4], windows[8]
            directional_agreement = (
                r4 is not None and r8 is not None and r4 * r8 > 0
            )
            supporting_signal = bool(momentum) and (
                current_candidate.code == "up" and momentum["direction"] == "strengthening"
                or current_candidate.code == "down" and momentum["direction"] == "weakening"
                or current_candidate.detail == "weak_to_strong" and momentum["direction"] == "strengthening"
                or current_candidate.detail == "strong_to_weak" and momentum["direction"] == "weakening"
            )
            view.update({
                "candidate_state": confirmation.candidate,
                "candidate_detail": confirmation.candidate_detail,
                "confirmed_state": confirmation.confirmed,
                "confirmed_detail": confirmation.confirmed_detail,
                "pending": confirmation.pending,
                "evidence": evidence_strength(
                    confirmed=confirmation.confirmed is not None,
                    periods=len(continuous_returns),
                    directional_agreement=directional_agreement,
                    supporting_signal=supporting_signal,
                    has_quality_issue=False,
                    has_irregular_interval=not all(continuous_intervals),
                ),
            })
        views.append(view)
    return views
```

在 `get_analysis()` 生成 `exited` 时排除流动性角色，并用产品名加账户作为排名标签以区分同名不同账户：

```python
exited = [
    item for item in product_views
    if item["lifecycle"] == "exited" and item["role"] != "liquidity"
]
comparison = {
    period: rank_horizon([
        (f"{item['name']} · {item['account_type']}", item["returns"][period])
        for item in active
    ])
    for period in (4, 8, 12)
}
```

- [ ] **Step 5: 增加缺期、非标准间隔和清仓测试**

在 `tests/test_performance_service.py` 增加：

```python
def test_missing_product_period_breaks_window(self) -> None:
    for index in range(8):
        self.add_snapshot(index, 100000 + index * 1000)
    self.portfolios.create_snapshot(SnapshotCreateInput(
        snapshot_date="2026-07-03",
        total_assets=10000,
        cash_balance=10000,
        weekly_return_amount=0,
        holdings=[HoldingInput(
            product_name="现金", account_type="货币/现金账户",
            amount=10000, allocation_percent=100, category="cash"
        )],
    ))
    result = PerformanceService(self.database).get_analysis()
    product = next(item for item in result["active_products"] if item["name"] == "观察宽基")
    self.assertIsNone(product["returns"][8])
    self.assertEqual(product["data_status"], "discontinuous")
```

增加非标准间隔测试：

```python
def test_irregular_interval_caps_evidence(self) -> None:
    for index in range(13):
        self.add_snapshot(index, 100000 + index * 1000)
    with self.database.session() as connection:
        connection.execute(
            "UPDATE weekly_snapshots SET snapshot_date = '2026-06-17' "
            "WHERE snapshot_date = '2026-06-12'"
        )
    product = PerformanceService(self.database).get_analysis()["active_products"][0]
    self.assertNotEqual(product["evidence"], "high")
```

增加清仓和重新建仓测试；清仓期产品连续存在且分母有效，缺席一期后的重新出现则重新积累：

```python
def test_exit_period_is_calculated_but_reentry_starts_new_segment(self) -> None:
    for index in range(9):
        self.add_snapshot(index, 100000 + index * 1000)
    self.portfolios.create_snapshot(SnapshotCreateInput(
        snapshot_date="2026-07-03",
        total_assets=10000,
        cash_balance=10000,
        weekly_return_amount=500,
        external_net_flow_amount=-98500,
        external_flow_confirmed=True,
        holdings=[
            HoldingInput(
                product_name="观察宽基", account_type="普通账户",
                amount=0, allocation_percent=0, category="equity",
                transaction_amount=-108000, weekly_pnl_amount=500,
            ),
            HoldingInput(
                product_name="现金", account_type="货币/现金账户",
                amount=10000, allocation_percent=100, category="cash",
            ),
        ],
    ))
    before_gap = PerformanceService(self.database).get_analysis()["active_products"][0]
    self.assertIsNotNone(before_gap["returns"][8])

    for snapshot_date, include_product in (("2026-07-10", False), ("2026-07-17", True)):
        holdings = [HoldingInput(
            product_name="现金", account_type="货币/现金账户",
            amount=10000, allocation_percent=50 if include_product else 100, category="cash",
        )]
        if include_product:
            holdings.append(HoldingInput(
                product_name="观察宽基", account_type="普通账户",
                amount=10000, allocation_percent=50, category="equity",
                transaction_amount=10000, weekly_pnl_amount=0,
            ))
        self.portfolios.create_snapshot(SnapshotCreateInput(
            snapshot_date=snapshot_date,
            total_assets=sum(item.amount for item in holdings),
            cash_balance=10000,
            weekly_return_amount=0,
            external_net_flow_amount=0,
            external_flow_confirmed=True,
            holdings=holdings,
        ))
    after_reentry = PerformanceService(self.database).get_analysis()["active_products"][0]
    self.assertIsNone(after_reentry["returns"][4])
    self.assertEqual(after_reentry["data_status"], "accumulating")
```

- [ ] **Step 6: 运行分析服务和纯函数测试**

```bash
python -m unittest tests.test_returns tests.test_metrics tests.test_classifier tests.test_performance_service -v
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交分析服务**

```bash
git add app/service.py app/performance_service.py tests/test_performance_service.py
git commit -m "feat: assemble portfolio performance analysis"
```

### Task 8: 增加产品设置页面并接入每周录入

**Files:**
- Create: `app/templates/products.html`
- Modify: `app/main.py`
- Modify: `app/templates/index.html`
- Modify: `app/static/styles.css`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 2 的 `ProductService`。
- Produces: `GET /products` 和 `POST /products/{product_id}`；首次录入可传递产品角色与分组，已有产品通过稳定 ID 继承。

- [ ] **Step 1: 写产品页面失败测试**

在 `tests/test_api.py` 增加：

```python
def test_product_settings_updates_role_group_and_lifecycle(self) -> None:
    created = self.client.post("/api/weekly-snapshots", json={
        "snapshot_date": "2026-08-21",
        "total_assets": 10000,
        "cash_balance": 0,
        "holdings": [{
            "product_name": "中证全指组合包",
            "account_type": "普通账户",
            "amount": 10000,
            "allocation_percent": 100,
            "category": "equity",
        }],
    }).json()
    product_id = created["holdings"][0]["product_id"]
    page = self.client.get("/products")
    self.assertEqual(page.status_code, 200)
    self.assertIn("中证全指组合包", page.text)

    response = self.client.post(f"/products/{product_id}", data={
        "management_role": "active_watch",
        "comparison_group": "broad",
        "lifecycle_status": "planned_exit",
    }, follow_redirects=False)
    self.assertEqual(response.status_code, 303)
    updated = self.client.get("/products")
    self.assertIn('value="planned_exit" selected', updated.text)
```

- [ ] **Step 2: 运行测试确认 RED**

```bash
python -m unittest tests.test_api.ApiTests.test_product_settings_updates_role_group_and_lifecycle -v
```

Expected: FAIL，`/products` 返回 404。

- [ ] **Step 3: 注册产品设置路由**

在 `create_app()` 中创建 `ProductService`，增加：

```python
@app.get("/products", response_class=HTMLResponse)
def product_settings(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="products.html",
        context={"products": product_service.list_products()},
    )


@app.post("/products/{product_id}")
async def update_product_settings(product_id: int, request: Request):
    body = (await request.body()).decode("utf-8")
    form = {key: values[-1] for key, values in parse_qs(body).items()}
    product_service.update_product(product_id, ProductUpdateInput(
        management_role=str(form["management_role"]),
        comparison_group=str(form["comparison_group"]),
        lifecycle_status=str(form["lifecycle_status"]),
    ))
    return RedirectResponse(url="/products", status_code=status.HTTP_303_SEE_OTHER)
```

- [ ] **Step 4: 创建产品设置模板**

`products.html` 使用现有页面壳和样式变量，每个产品一个独立表单：

```html
<nav class="top-nav">
  <a href="/">录入复盘</a>
  <a href="/analysis">趋势观察</a>
  <a href="/products" class="active">产品设置</a>
</nav>
{% for product in products %}
<form method="post" action="/products/{{ product.id }}" class="product-setting-row">
  <div>
    <strong>{{ product.canonical_name }}</strong>
    <span>{{ product.account_type }}</span>
  </div>
  <select name="management_role">
    {% for value, label in [('active_watch','主动观察'),('long_term','长期持有'),('stable','稳定资产'),('liquidity','流动性')] %}
      <option value="{{ value }}" {% if product.management_role == value %}selected{% endif %}>{{ label }}</option>
    {% endfor %}
  </select>
  <select name="comparison_group">
    {% for value, label in [('broad','宽基'),('star50','科创'),('hang_seng','恒生'),('other','其他')] %}
      <option value="{{ value }}" {% if product.comparison_group == value %}selected{% endif %}>{{ label }}</option>
    {% endfor %}
  </select>
  <select name="lifecycle_status">
    {% for value, label in [('active','正常'),('planned_exit','计划退出'),('exited','已退出')] %}
      <option value="{{ value }}" {% if product.lifecycle_status == value %}selected{% endif %}>{{ label }}</option>
    {% endfor %}
  </select>
  <button type="submit" class="ghost-button">保存</button>
</form>
{% endfor %}
```

- [ ] **Step 5: 在录入表单携带产品 ID 和新产品默认元数据**

已有行增加隐藏 `product_id_N`；只有尚未绑定 ID 的新行显示角色、分组选择，已绑定行显示“角色请在产品设置中维护”：

```html
<input type="hidden" name="product_id_{{ row }}" value="{{ holding.product_id or '' }}" />
{% if not holding.product_id %}
<select name="management_role_{{ row }}">
  <option value="active_watch">主动观察</option>
  <option value="long_term">长期持有</option>
  <option value="stable">稳定资产</option>
  <option value="liquidity">流动性</option>
</select>
<select name="comparison_group_{{ row }}">
  <option value="other">其他</option>
  <option value="broad">宽基</option>
  <option value="star50">科创</option>
  <option value="hang_seng">恒生</option>
</select>
{% else %}
<a href="/products" class="inline-link">已绑定产品档案 · 前往产品设置</a>
{% endif %}
```

在 `_extract_holdings_from_form()` 传入：

```python
product_id=(
    int(form[f"product_id_{index}"])
    if str(form.get(f"product_id_{index}", "")).strip()
    else None
),
management_role=str(form.get(f"management_role_{index}", "")) or None,
comparison_group=str(form.get(f"comparison_group_{index}", "")) or None,
```

复制和编辑必须保留 `product_id`；动态新增行没有 ID，保存时由 ProductService 解析。

- [ ] **Step 6: 增加三页导航与响应式样式**

在 `index.html` 顶部加入同一 `top-nav`，在 `styles.css` 增加：

```css
.top-nav { display: flex; gap: 10px; flex-wrap: wrap; }
.top-nav a { padding: 10px 14px; border-radius: 999px; color: var(--ink); text-decoration: none; }
.top-nav a.active { background: var(--ink); color: white; }
.product-setting-row { display: grid; grid-template-columns: minmax(220px, 1fr) repeat(3, minmax(130px, .5fr)) auto; gap: 12px; align-items: center; }
@media (max-width: 820px) { .product-setting-row { grid-template-columns: 1fr; } }
```

- [ ] **Step 7: 运行产品设置和复制回归测试**

```bash
python -m unittest \
  tests.test_api.ApiTests.test_product_settings_updates_role_group_and_lifecycle \
  tests.test_api.ApiTests.test_dashboard_can_copy_existing_snapshot_as_new_draft \
  tests.test_product_service -v
```

Expected: 全部 PASS；复制仍将动作和交易金额归零，但保留产品 ID。

- [ ] **Step 8: 提交产品设置页面**

```bash
git add app/main.py app/templates/index.html app/templates/products.html app/static/styles.css tests/test_api.py
git commit -m "feat: add product profile settings"
```

### Task 9: 构建独立趋势观察页面

**Files:**
- Create: `app/templates/analysis.html`
- Modify: `app/main.py`
- Modify: `app/static/styles.css`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 7 的 `PerformanceService.get_analysis()`。
- Produces: `GET /analysis`，展示组合估算净值、主动观察卡片、分周期排名、长期/稳定指标、退出历史、质量提示、规则版本和固定声明。

- [ ] **Step 1: 写空数据和完整数据页面失败测试**

在 `tests/test_api.py` 增加：

```python
def test_analysis_page_renders_empty_state_and_disclaimer(self) -> None:
    response = self.client.get("/analysis")
    self.assertEqual(response.status_code, 200)
    self.assertIn("趋势观察", response.text)
    self.assertIn("数据积累中", response.text)
    self.assertIn("trend-v1", response.text)
    self.assertIn("不构成涨跌预测、交易建议或调仓指令", response.text)

def test_analysis_page_separates_active_and_objective_products(self) -> None:
    self._seed_performance_history()
    response = self.client.get("/analysis")
    self.assertEqual(response.status_code, 200)
    self.assertIn("主动观察", response.text)
    self.assertIn("4期收益", response.text)
    self.assertIn("资金流调整净值", response.text)
    self.assertIn("长期与稳定资产", response.text)
    self.assertNotIn("自动调仓", response.text)
```

在测试类内加入实际 helper，通过 JSON API 连续写入 9 个快照：

```python
def _seed_performance_history(self) -> None:
    from datetime import date, timedelta

    for index in range(9):
        active_amount = 50000 + index * 500
        long_term_amount = 50000 + index * 200
        response = self.client.post("/api/weekly-snapshots", json={
            "snapshot_date": str(date(2026, 6, 26) + timedelta(days=7 * index)),
            "total_assets": active_amount + long_term_amount,
            "cash_balance": 0,
            "weekly_return_amount": 700,
            "external_net_flow_amount": 0,
            "external_flow_confirmed": True,
            "holdings": [
                {
                    "product_name": "科创50",
                    "account_type": "普通账户",
                    "amount": active_amount,
                    "allocation_percent": 50,
                    "category": "equity",
                    "weekly_pnl_amount": 500,
                    "management_role": "active_watch",
                    "comparison_group": "star50",
                },
                {
                    "product_name": "养老金中证500增强",
                    "account_type": "养老金账户",
                    "amount": long_term_amount,
                    "allocation_percent": 50,
                    "category": "equity",
                    "weekly_pnl_amount": 200,
                    "management_role": "long_term",
                    "comparison_group": "broad",
                },
            ],
        })
        self.assertEqual(response.status_code, 201)
```

- [ ] **Step 2: 运行页面测试确认 RED**

```bash
python -m unittest \
  tests.test_api.ApiTests.test_analysis_page_renders_empty_state_and_disclaimer \
  tests.test_api.ApiTests.test_analysis_page_separates_active_and_objective_products -v
```

Expected: FAIL，`/analysis` 返回 404。

- [ ] **Step 3: 注册分析路由**

在 `create_app()` 创建 `PerformanceService(database)` 并增加：

```python
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
        },
    )
```

- [ ] **Step 4: 实现组合表现和质量区**

`analysis.html` 的组合区必须对不可用值使用状态文案：

```html
<section class="card performance-card">
  <header class="section-head">
    <div><p class="mini-label">Portfolio</p><h2>组合表现</h2></div>
    <span class="rule-badge">{{ analysis.rule_version }}</span>
  </header>
  {% if analysis.portfolio.available %}
    <div class="metric-grid">
      <article><span>累计收益</span><strong>{{ '%.2f'|format(analysis.portfolio.cumulative_return * 100) }}%</strong></article>
      <article><span>当前回撤</span><strong>{{ '%.2f'|format(analysis.portfolio.current_drawdown * 100) }}%</strong></article>
      <article><span>最大回撤</span><strong>{{ '%.2f'|format(analysis.portfolio.max_drawdown * 100) }}%</strong></article>
      <article><span>阶段高点</span><strong>{{ analysis.portfolio.high_date }}</strong></article>
    </div>
    <svg class="nav-chart" viewBox="0 0 1000 260" role="img" aria-label="估算资金流调整净值">
      <polyline points="{{ analysis.portfolio.chart_points }}" fill="none" stroke="currentColor" stroke-width="4" />
    </svg>
  {% else %}
    <div class="empty-history"><p>数据积累中</p><span>至少录入两期快照后计算资金流调整收益。</span></div>
  {% endif %}
</section>
```

最新资金流旁显示 `已确认` 或 `系统估算`。`quality` 非空时逐条展示，不能隐藏无效分母、非标准间隔或未确认资金流。

- [ ] **Step 5: 实现产品卡片、比较表和客观指标区**

主动卡片循环必须只使用 `analysis.active_products`：

```html
{% for product in analysis.active_products %}
<article class="trend-card">
  <header><div><strong>{{ product.name }}</strong><span>{{ product.account_type }}</span></div><em>{{ lifecycle_labels[product.lifecycle] }}</em></header>
  <div class="horizon-grid">
    {% for period in [4, 8, 12] %}
      <div><span>{{ period }}期收益</span>
      {% if product.returns[period] is not none %}<strong>{{ '%.2f'|format(product.returns[period] * 100) }}%</strong>{% else %}<strong>数据积累中</strong>{% endif %}</div>
    {% endfor %}
  </div>
  {% if product.confirmed_state is defined %}
    <p>确认状态：{{ state_labels.get(product.confirmed_state, '尚未确认') }}{% if product.confirmed_state == 'turning' and product.confirmed_detail %}（{{ turning_detail_labels[product.confirmed_detail] }}）{% endif %}</p>
    {% if product.pending %}<p>候选状态：{{ state_labels[product.candidate_state] }}{% if product.candidate_detail %}（{{ turning_detail_labels[product.candidate_detail] }}）{% endif %}，待确认 1/2</p>{% endif %}
    <p>证据强度：{{ evidence_labels[product.evidence] }}</p>
  {% endif %}
</article>
{% endfor %}
```

比较区分别循环 `[4, 8, 12]`；空列表显示“可比较产品不足”。长期与稳定区只输出收益、回撤、高点和数据状态，模板内不得引用 `confirmed_state`。退出产品单独放在折叠历史区。

- [ ] **Step 6: 增加固定声明和分析页面样式**

页面底部写死：

```html
<footer class="analysis-disclaimer">
  本页面仅基于已录入的历史数据进行状态识别，不构成涨跌预测、交易建议或调仓指令。
</footer>
```

在 `styles.css` 增加：

```css
.metric-grid, .horizon-grid, .trend-grid { display: grid; gap: 14px; }
.metric-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.horizon-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.trend-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.trend-card { padding: 20px; border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface-strong); }
.nav-chart { width: 100%; min-height: 220px; color: var(--accent); background: var(--surface-muted); border-radius: var(--radius-lg); }
.analysis-disclaimer { color: var(--muted); line-height: 1.7; text-align: center; }
@media (max-width: 760px) {
  .metric-grid, .horizon-grid, .trend-grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 7: 运行分析页面和完整 API 测试**

```bash
python -m unittest tests.test_api tests.test_performance_service -v
```

Expected: 全部 PASS；长期产品 HTML 不包含状态控件，空数据页面不输出伪造 0%。

- [ ] **Step 8: 提交趋势页面**

```bash
git add app/main.py app/templates/analysis.html app/static/styles.css tests/test_api.py
git commit -m "feat: add performance trend analysis page"
```

### Task 10: 完成质量检查、文档和全量回归

**Files:**
- Modify: `app/service.py`
- Modify: `tests/test_data_quality.py`
- Modify: `tests/test_demo_seeder.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–9 的全部功能。
- Produces: 未映射产品和资金流状态质量提示、演示数据兼容、项目文档和全量测试证据。

- [ ] **Step 1: 写新增数据质量失败测试**

在 `tests/test_data_quality.py` 增加：

```python
def test_reports_unmapped_product_and_unconfirmed_flow(self) -> None:
    for snapshot_date, amount, pnl in (
        ("2026-08-14", 100000, 0),
        ("2026-08-21", 101000, 1000),
    ):
        self.service.create_snapshot(SnapshotCreateInput(
            snapshot_date=snapshot_date,
            total_assets=amount,
            cash_balance=0,
            weekly_return_amount=pnl,
            external_net_flow_amount=0,
            external_flow_confirmed=False,
            holdings=[HoldingInput(
                product_name="科创50",
                account_type="普通账户",
                amount=amount,
                allocation_percent=100,
                category="equity",
                weekly_pnl_amount=pnl,
            )],
        ))
    with self.database.session() as connection:
        connection.execute(
            "UPDATE holdings SET product_id = NULL WHERE snapshot_id = "
            "(SELECT id FROM weekly_snapshots ORDER BY snapshot_date DESC LIMIT 1)"
        )
        connection.execute(
            "UPDATE weekly_snapshots SET external_flow_confirmed = 0 "
            "WHERE snapshot_date = '2026-08-21'"
        )
    issues = self.service.get_data_quality_checks()["issues"]
    issue_types = {issue["type"] for issue in issues}
    self.assertIn("product_unmapped", issue_types)
    self.assertIn("external_flow_unconfirmed", issue_types)
```

该测试需要直接访问数据库，因此把现有 `setUp()` 中的局部变量改为实例属性：

```python
self.database = Database(self.temp_dir / "portfolio.db")
self.database.initialize()
self.service = PortfolioService(self.database)
```

- [ ] **Step 2: 运行质量测试确认 RED**

```bash
python -m unittest tests.test_data_quality -v
```

Expected: FAIL，缺少两个问题类型。

- [ ] **Step 3: 增加质量提示并保持非阻断保存**

在 `get_data_quality_checks()` 中加入：

```python
for holding in latest.holdings:
    if holding.product_id is None:
        issues.append({
            "type": "product_unmapped",
            "severity": "warning",
            "message": f"持仓 '{holding.product_name}' 尚未绑定产品档案",
            "details": {"product_name": holding.product_name},
        })

if len(snapshots) >= 2 and not latest.external_flow_confirmed:
    issues.append({
        "type": "external_flow_unconfirmed",
        "severity": "info",
        "message": "本期外部净资金流仍为系统估算",
        "details": {"snapshot_date": latest.snapshot_date},
    })
```

更新首页质量提示模板，为这两类显示通用详情，不改变保存逻辑。

- [ ] **Step 4: 更新演示数据兼容测试**

在 `tests/test_demo_seeder.py` 增加断言：

```python
with self.database.session() as connection:
    missing = connection.execute(
        "SELECT COUNT(*) AS count FROM holdings WHERE product_id IS NULL"
    ).fetchone()["count"]
self.assertEqual(missing, 0)
```

现有演示 seeder 已通过 `PortfolioService.create_snapshot()` 写入，因此 Task 2 会自动绑定产品，无需修改 `app/demo_seeder.py`。若该断言失败，应修复 `PortfolioService` 集成，不能在 seeder 中复制一套产品解析规则。

- [ ] **Step 5: 更新 README**

将功能范围增加：

```markdown
- 每期外部净资金流估算、确认和修正
- 组合资金流调整净值、高点与回撤
- 产品 4/8/12 期收益、动量和连续涨跌
- 主动观察产品的 trend-v1 历史状态识别
- 产品角色、比较分组和生命周期管理
```

把测试命令修正为项目实际使用的：

```bash
python -m unittest discover -s tests -v
```

注明趋势页 `/analysis`、产品设置 `/products`，以及所有状态只描述历史、不构成预测。

- [ ] **Step 6: 运行全量测试和静态检查**

```bash
python -m unittest discover -s tests -v
python -m compileall -q app tests
git diff --check
```

Expected: 所有测试 PASS，`compileall` 和 `git diff --check` 无输出、退出码 0。

- [ ] **Step 7: 本地启动并做只读 HTTP 冒烟**

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8113
```

另一个终端执行：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8113/health
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8113/
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8113/analysis
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8113/products
```

Expected: 四个请求均返回 200。结束本次前台 uvicorn 进程。

- [ ] **Step 8: 提交质量和文档收尾**

```bash
git add app/service.py app/templates/index.html tests/test_data_quality.py tests/test_demo_seeder.py README.md
git commit -m "test: complete trend analysis regression coverage"
```

### Task 11: 发布并验证 3.57 本地调试环境

**Files:**
- No source-file changes.
- Remote directory: `/data/work/project/portfolio-review-app`
- Runtime URL: `http://192.168.3.57:1103/`

**Interfaces:**
- Consumes: 已完整测试并提交的 `main`。
- Produces: 3.57 上运行新版本，SQLite 原数据保留，健康检查、趋势页和产品设置页可访问。

- [ ] **Step 1: 检查本地分支和待推送提交**

```bash
git status --short --branch
git log -12 --oneline --decorate
git remote -v
```

Expected: 业务文件干净；仅允许本地可视化临时目录 `.superpowers/` 保持未跟踪且不得提交；`origin` 指向 `https://github.com/zp1103/portfolio-review-app.git`。

- [ ] **Step 2: 推送 GitHub main**

```bash
git push origin main
```

Expected: `origin/main` 快进到本地最终提交。

- [ ] **Step 3: 只读检查 3.57 远端状态和持久化目录**

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "cd /data/work/project/portfolio-review-app && git status --short --branch && docker compose ps"
```

Expected: 远端源码无未说明改动，Compose 项目对应 `portfolio-review-app`，端口为 1103。若远端有改动或失效 worktree 指针，停止，不覆盖 `.env`、`data/` 或部署覆盖文件。

- [ ] **Step 4: 备份 SQLite 并快进重建**

先从远端 `.env` 和 Compose 挂载确认实际 `DATA_DIR`，只复制数据库文件到同目录带时间戳备份，不输出环境变量内容。确认路径后执行：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "cd /data/work/project/portfolio-review-app && cp data/portfolio.db data/portfolio.db.pre-trend-analysis && git pull --ff-only && docker compose up -d --build"
```

Expected: 备份成功、Git 快进、容器重建完成。若实际数据目录不是仓库内 `data/`，把命令中的两个数据库路径替换为检查得到的明确绝对路径后再执行。

- [ ] **Step 5: 验证容器和四个 HTTP 入口**

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "cd /data/work/project/portfolio-review-app && docker compose ps --format json"

curl -sS -o /dev/null -w '%{http_code}\n' http://192.168.3.57:1103/health
curl -sS -o /dev/null -w '%{http_code}\n' http://192.168.3.57:1103/
curl -sS -o /dev/null -w '%{http_code}\n' http://192.168.3.57:1103/analysis
curl -sS -o /dev/null -w '%{http_code}\n' http://192.168.3.57:1103/products
```

Expected: 容器为 `running/healthy`，四个请求均为 HTTP 200。

- [ ] **Step 6: 只读验证迁移数量和历史数据保留**

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "docker exec portfolio-review-app python -c \"import sqlite3; c=sqlite3.connect('/app/data/portfolio.db'); print({'snapshots':c.execute('select count(*) from weekly_snapshots').fetchone()[0], 'holdings':c.execute('select count(*) from holdings').fetchone()[0], 'products':c.execute('select count(*) from portfolio_products').fetchone()[0], 'unmapped':c.execute('select count(*) from holdings where product_id is null').fetchone()[0]})\""
```

Expected: 快照和持仓数量不少于部署前；产品数量大于 0；`unmapped` 为 0。当前已知基线约为 19 个快照、145 条持仓、8 个产品档案，实际值只能增加，不能因部署减少。

- [ ] **Step 7: 浏览器人工验收**

打开 `http://192.168.3.57:1103/products`，确认并保存当前产品角色：养老金产品为长期持有，现金为流动性，科创/恒生/中证全指为主动观察，中证全指生命周期为计划退出。然后打开 `http://192.168.3.57:1103/analysis`，核对：

```text
组合区明确标注估算资金流调整净值；
中证全指不是基准；
长期产品没有状态标签；
不足 12 期的指标显示数据积累中；
页面底部显示历史识别免责声明。
```

这一步会修改产品元数据，执行前必须得到用户对 3.57 部署和角色配置的明确授权；不得把既有对其他功能部署的授权自动沿用到本任务。

- [ ] **Step 8: 汇报部署证据**

汇报最终提交 SHA、GitHub `main` 推送结果、远端提交 SHA、数据库备份路径、容器健康状态、四个 URL 状态码、迁移后计数，以及人工验收结果。
