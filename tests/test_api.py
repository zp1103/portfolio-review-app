import re
import shutil
import subprocess
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(__file__).resolve().parent / "_tmp_api"
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.client = TestClient(create_app(self.temp_dir / "portfolio.db"))

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def _seed_performance_history(self) -> None:
        from datetime import date, timedelta

        for index in range(9):
            active_amount = 50000 + index * 500
            long_term_amount = 50000 + index * 200
            response = self.client.post(
                "/api/weekly-snapshots",
                json={
                    "snapshot_date": str(
                        date(2026, 6, 26) + timedelta(days=7 * index)
                    ),
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
                },
            )
            self.assertEqual(response.status_code, 201)

    def test_analysis_page_renders_empty_state_and_disclaimer(self) -> None:
        response = self.client.get("/analysis")

        self.assertEqual(response.status_code, 200)
        self.assertIn("趋势观察", response.text)
        self.assertIn("数据积累中", response.text)
        self.assertIn("trend-v1", response.text)
        self.assertIn("不构成涨跌预测、交易建议或调仓指令", response.text)
        self.assertIn("最新外部净资金流", response.text)
        self.assertIn("<strong>计算不可用</strong>", response.text)
        self.assertIn("<em>暂不可用</em>", response.text)
        self.assertNotIn("0.00%", response.text)

    def test_analysis_page_separates_active_and_objective_products(self) -> None:
        self._seed_performance_history()

        response = self.client.get("/analysis")

        self.assertEqual(response.status_code, 200)
        self.assertIn("主动观察", response.text)
        self.assertIn("科创50", response.text)
        self.assertIn("4期收益", response.text)
        self.assertIn("资金流调整净值", response.text)
        self.assertIn("长期与稳定资产", response.text)
        self.assertIn("养老金中证500增强", response.text)
        self.assertEqual(response.text.count("确认状态："), 1)
        self.assertNotIn("自动调仓", response.text)

        active_card = response.text.split(
            "<strong>科创50</strong>", 1
        )[1].split("</article>", 1)[0]
        self.assertIn("比较分组", active_card)
        self.assertIn("<dd>科创</dd>", active_card)
        self.assertIn("当前回撤", active_card)
        self.assertIn("0.00%", active_card)
        self.assertIn("阶段高点", active_card)
        self.assertIn("2026-08-21", active_card)
        self.assertIn("连续表现", active_card)
        self.assertIn("连续上行 8 期", active_card)
        self.assertIn("动能变化", active_card)
        self.assertIn("减弱", active_card)
        self.assertNotIn("star50", active_card)
        self.assertNotIn("weakening", active_card)

        objective_card = response.text.split(
            "<strong>养老金中证500增强</strong>", 1
        )[1].split("</article>", 1)[0]
        self.assertNotIn("<em>正常</em>", objective_card)
        self.assertNotIn("比较分组", objective_card)
        self.assertNotIn("连续表现", objective_card)
        self.assertNotIn("动能变化", objective_card)
        self.assertNotIn("确认状态", objective_card)
        self.assertNotIn("证据强度", objective_card)

    def test_analysis_page_distinguishes_unavailable_states(self) -> None:
        first = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-07-03",
                "total_assets": 20000,
                "cash_balance": 0,
                "holdings": [
                    {
                        "product_name": "无效计算产品",
                        "account_type": "普通账户",
                        "amount": 10000,
                        "allocation_percent": 50,
                        "category": "equity",
                    },
                    {
                        "product_name": "中断产品",
                        "account_type": "普通账户",
                        "amount": 10000,
                        "allocation_percent": 50,
                        "category": "equity",
                    },
                ],
            },
        )
        second = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-07-10",
                "total_assets": 2000,
                "cash_balance": 0,
                "holdings": [
                    {
                        "product_name": "无效计算产品",
                        "account_type": "普通账户",
                        "amount": 1000,
                        "allocation_percent": 50,
                        "category": "equity",
                        "transaction_amount": -30000,
                    },
                    {
                        "product_name": "新进入产品",
                        "account_type": "普通账户",
                        "amount": 1000,
                        "allocation_percent": 50,
                        "category": "equity",
                    },
                ],
            },
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)

        response = self.client.get("/analysis")

        self.assertEqual(response.status_code, 200)
        self.assertIn("数据积累中", response.text)
        self.assertIn("数据不连续", response.text)
        self.assertIn("计算不可用", response.text)
        self.assertIn("可比较产品不足", response.text)
        self.assertIn("系统估算", response.text)

        invalid_card = response.text.split(
            "<strong>无效计算产品</strong>", 1
        )[1].split("</article>", 1)[0]
        self.assertIn("比较分组", invalid_card)
        self.assertIn("<dd>其他</dd>", invalid_card)
        self.assertIn("当前回撤", invalid_card)
        self.assertIn("阶段高点", invalid_card)
        self.assertIn("连续表现", invalid_card)
        self.assertIn("暂无连续方向", invalid_card)
        self.assertIn("动能变化", invalid_card)
        self.assertIn("计算不可用", invalid_card)
        self.assertNotIn("0.00%", invalid_card)

    def test_analysis_page_keeps_exited_products_in_collapsed_history(self) -> None:
        self._seed_performance_history()
        latest = self.client.get("/api/weekly-snapshots").json()[0]
        active_product = next(
            holding
            for holding in latest["holdings"]
            if holding["product_name"] == "科创50"
        )
        updated = self.client.post(
            f"/products/{active_product['product_id']}",
            data={
                "management_role": "active_watch",
                "comparison_group": "star50",
                "lifecycle_status": "exited",
            },
            follow_redirects=False,
        )
        self.assertEqual(updated.status_code, 303)

        response = self.client.get("/analysis")

        self.assertEqual(response.status_code, 200)
        self.assertIn('<details class="exit-history">', response.text)
        self.assertIn("退出历史", response.text)
        self.assertIn("已退出", response.text)
        self.assertIn("科创50", response.text)

    def test_healthcheck_returns_ok(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_product_settings_updates_role_group_and_lifecycle(self) -> None:
        created = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-08-21",
                "total_assets": 10000,
                "cash_balance": 0,
                "holdings": [
                    {
                        "product_name": "中证全指组合包",
                        "account_type": "普通账户",
                        "amount": 10000,
                        "allocation_percent": 100,
                        "category": "equity",
                    }
                ],
            },
        ).json()
        product_id = created["holdings"][0]["product_id"]

        page = self.client.get("/products")

        self.assertEqual(page.status_code, 200)
        self.assertIn("中证全指组合包", page.text)
        self.assertIn('value="active_watch" selected', page.text)
        self.assertIn('value="other" selected', page.text)
        historical_holding = self.client.get(
            "/api/weekly-snapshots"
        ).json()[0]["holdings"][0]

        response = self.client.post(
            f"/products/{product_id}",
            data={
                "management_role": "long_term",
                "comparison_group": "broad",
                "lifecycle_status": "planned_exit",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        updated = self.client.get("/products")
        self.assertIn('value="long_term" selected', updated.text)
        self.assertIn('value="broad" selected', updated.text)
        self.assertIn('value="planned_exit" selected', updated.text)
        updated_holding = self.client.get(
            "/api/weekly-snapshots"
        ).json()[0]["holdings"][0]
        self.assertEqual(updated_holding, historical_holding)

    def test_dashboard_page_contains_snapshot_form(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/snapshots"', response.text)
        self.assertIn('name="snapshot_date"', response.text)
        self.assertIn('name="product_name_0"', response.text)
        self.assertIn('name="account_type_0"', response.text)
        self.assertIn('<option value="普通账户">普通账户</option>', response.text)
        self.assertIn('name="allocation_percent_0"', response.text)
        self.assertIn('readonly', response.text)
        self.assertIn('id="weekly-return-input"', response.text)
        self.assertIn('id="weekly-return-rate-input"', response.text)
        self.assertIn('id="total-assets-input"', response.text)
        self.assertIn('id="cash-balance-input"', response.text)
        self.assertIn('name="transaction_amount_0"', response.text)
        self.assertIn('name="cumulative_pnl_amount_0"', response.text)
        self.assertIn('name="exposure_equity_percent_0"', response.text)
        self.assertIn("底层穿透比例", response.text)

    def test_dynamic_holding_row_template_contains_product_metadata_fields(self) -> None:
        response = self.client.get("/")

        template = response.text.split(
            '<template id="holding-row-template">', 1
        )[1].split("</template>", 1)[0]

        self.assertIn('name="product_id___INDEX__"', template)
        self.assertIn('name="management_role___INDEX__"', template)
        self.assertIn('name="comparison_group___INDEX__"', template)

    def test_new_weekly_form_sets_product_role_and_group(self) -> None:
        page = self.client.get("/")

        self.assertIn('name="product_id_0" value=""', page.text)
        self.assertIn('name="management_role_0"', page.text)
        self.assertIn('name="comparison_group_0"', page.text)

        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-08-21",
                "product_id_0": "",
                "product_name_0": "养老长期组合",
                "account_type_0": "养老金账户",
                "management_role_0": "long_term",
                "comparison_group_0": "broad",
                "amount_0": "10000",
                "allocation_percent_0": "100",
                "category_0": "equity",
                "action_0": "hold",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        product_page = self.client.get("/products")
        self.assertIn("养老长期组合", product_page.text)
        self.assertIn('value="long_term" selected', product_page.text)
        self.assertIn('value="broad" selected', product_page.text)

    def test_edit_and_copy_forms_inherit_product_identity(self) -> None:
        created = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-08-21",
                "total_assets": 10000,
                "cash_balance": 0,
                "holdings": [
                    {
                        "product_name": "稳定身份产品",
                        "account_type": "普通账户",
                        "amount": 10000,
                        "allocation_percent": 100,
                        "category": "equity",
                        "action": "buy",
                        "transaction_amount": 2500,
                    }
                ],
            },
        ).json()
        product_id = created["holdings"][0]["product_id"]

        for query in ("edit_id", "copy_id"):
            page = self.client.get(f"/?{query}={created['id']}")
            self.assertIn(
                f'name="product_id_0" value="{product_id}"',
                page.text,
            )
            self.assertNotIn('name="management_role_0"', page.text)
            self.assertNotIn('name="comparison_group_0"', page.text)
            self.assertIn("已绑定产品档案 · 前往产品设置", page.text)

        copied = self.client.get(f"/?copy_id={created['id']}")
        self.assertIn('name="transaction_amount_0" value="0"', copied.text)
        self.assertRegex(
            copied.text,
            r'(?s)<select name="action_0">.*?'
            r'<option value="hold" selected>持有</option>.*?</select>',
        )

    def test_create_snapshot_endpoint_persists_payload(self) -> None:
        payload = {
            "snapshot_date": "2026-04-18",
            "total_assets": 421000,
            "cash_balance": 80000,
            "weekly_return_amount": -3200,
            "ytd_return_amount": 8600,
            "data_cutoff_notes": "统一按周三口径",
            "notes": "Geo risk rebalance",
            "holdings": [
                {
                    "product_name": "中证全指指数组合",
                    "account_type": "普通账户",
                    "amount": 45000,
                    "allocation_percent": 10.69,
                    "category": "equity",
                    "action": "hold",
                    "weekly_pnl_amount": 1200,
                    "transaction_amount": 5000,
                    "cumulative_pnl_amount": 8200,
                    "valuation_cutoff_date": "2026-04-18",
                    "notes": "维持核心仓",
                }
            ],
        }

        create_response = self.client.post("/api/weekly-snapshots", json=payload)
        list_response = self.client.get("/api/weekly-snapshots")

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.json()["snapshot_date"], "2026-04-18")
        self.assertEqual(create_response.json()["holdings"][0]["weekly_pnl_amount"], 1200)
        self.assertEqual(create_response.json()["holdings"][0]["transaction_amount"], 5000)
        self.assertEqual(create_response.json()["holdings"][0]["cumulative_pnl_amount"], 8200)
        self.assertEqual(create_response.json()["holdings"][0]["valuation_cutoff_date"], "2026-04-18")
        self.assertEqual(list_response.status_code, 200)
        data = list_response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["holdings"][0]["product_name"], "中证全指指数组合")

    def test_dashboard_page_renders_existing_snapshot(self) -> None:
        self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-18",
                "total_assets": 421000,
                "cash_balance": 80000,
                "weekly_return_amount": -3200,
                "ytd_return_amount": 8600,
                "data_cutoff_notes": "统一按周三口径",
                "notes": "Geo risk rebalance",
                "holdings": [
                    {
                        "product_name": "科创50",
                        "account_type": "普通账户",
                        "amount": 10000,
                        "allocation_percent": 2.38,
                        "category": "equity",
                        "action": "buy",
                        "weekly_pnl_amount": -260,
                        "valuation_cutoff_date": "2026-04-18",
                        "notes": "新增试探仓",
                    }
                ],
            },
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("2026-04-18", response.text)
        self.assertIn("科创50", response.text)
        self.assertIn("-260.00", response.text)
        self.assertIn("周收益率 -2.60%", response.text)
        self.assertIn("估值截止 2026-04-18", response.text)

    def test_form_submission_creates_snapshot_and_redirects(self) -> None:
        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-04-25",
                "total_assets": "1",
                "cash_balance": "1",
                "weekly_return_amount": "2500",
                "ytd_return_amount": "11100",
                "data_cutoff_notes": "统一按周三口径",
                "notes": "表单录入测试",
                "product_name_0": "中证全指指数组合",
                "account_type_0": "普通账户",
                "amount_0": "50000",
                "allocation_percent_0": "11.63",
                "category_0": "equity",
                "action_0": "buy",
                "weekly_pnl_amount_0": "860",
                "valuation_cutoff_date_0": "2026-04-18",
                "holding_notes_0": "继续加仓",
                "product_name_1": "现金账户",
                "account_type_1": "货币/现金账户",
                "amount_1": "12000",
                "allocation_percent_1": "0",
                "category_1": "cash",
                "action_1": "hold",
                "weekly_pnl_amount_1": "0",
                "valuation_cutoff_date_1": "2026-04-18",
                "exposure_equity_percent_1": "0",
                "exposure_fixed_income_percent_1": "0",
                "exposure_cash_percent_1": "100",
                "exposure_gold_percent_1": "0",
                "exposure_other_percent_1": "0",
                "holding_notes_1": "",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")

        dashboard = self.client.get("/")
        self.assertIn("2026-04-25", dashboard.text)
        self.assertIn("中证全指指数组合", dashboard.text)
        snapshots = self.client.get("/api/weekly-snapshots").json()
        self.assertEqual(snapshots[0]["weekly_return_amount"], 860)
        self.assertEqual(snapshots[0]["total_assets"], 62000)
        self.assertEqual(snapshots[0]["cash_balance"], 12000)
        self.assertEqual(snapshots[0]["holdings"][1]["exposure_cash_percent"], 100)

    def test_dashboard_can_prefill_existing_snapshot_for_editing(self) -> None:
        create_response = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-18",
                "total_assets": 421000,
                "cash_balance": 80000,
                "weekly_return_amount": -3200,
                "ytd_return_amount": 8600,
                "data_cutoff_notes": "普通账户到周五",
                "notes": "Geo risk rebalance",
                "holdings": [
                    {
                        "product_name": "科创50",
                        "account_type": "普通账户",
                        "amount": 10000,
                        "allocation_percent": 2.38,
                        "category": "equity",
                        "action": "buy",
                        "weekly_pnl_amount": -260,
                        "valuation_cutoff_date": "2026-04-18",
                        "notes": "新增试探仓",
                    }
                ],
            },
        )
        snapshot_id = create_response.json()["id"]

        response = self.client.get(f"/?edit_id={snapshot_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn('value="2026-04-18"', response.text)
        self.assertIn('value="科创50"', response.text)
        self.assertIn('name="snapshot_id"', response.text)
        self.assertIn('value="-260.0"', response.text)
        self.assertIn('value="2026-04-18"', response.text)
        self.assertIn("普通账户到周五", response.text)
        self.assertRegex(
            response.text,
            r'(?s)<select name="action_0">.*?'
            r'<option value="buy" selected>买入</option>.*?</select>',
        )

    def test_dashboard_can_copy_existing_snapshot_as_new_draft(self) -> None:
        create_response = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-18",
                "total_assets": 130000,
                "cash_balance": 0,
                "weekly_return_amount": -3200,
                "ytd_return_amount": 8600,
                "data_cutoff_notes": "普通账户到周五",
                "notes": "上周备注",
                "holdings": [
                    {
                        "product_name": "全球稳健配置组合",
                        "account_type": "第三方平台账户",
                        "amount": 100000,
                        "allocation_percent": 76.92,
                        "category": "fixed_income",
                        "action": "buy",
                        "transaction_amount": 5000,
                        "weekly_pnl_amount": 660,
                        "cumulative_pnl_amount": 11800,
                        "valuation_cutoff_date": "2026-04-18",
                        "exposure_equity_percent": 30,
                        "exposure_fixed_income_percent": 60,
                        "exposure_cash_percent": 10,
                        "notes": "固收60%，权益30%",
                    },
                    {
                        "product_name": "科创50",
                        "account_type": "普通账户",
                        "amount": 10000,
                        "allocation_percent": 7.69,
                        "category": "equity",
                        "action": "sell",
                        "transaction_amount": -2000,
                    },
                    {
                        "product_name": "黄金ETF",
                        "account_type": "普通账户",
                        "amount": 20000,
                        "allocation_percent": 15.39,
                        "category": "gold",
                        "action": "rebalance",
                        "transaction_amount": 3000,
                    },
                ],
            },
        )
        snapshot_id = create_response.json()["id"]

        response = self.client.get(f"/?copy_id={snapshot_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("复制 2026-04-18 的快照", response.text)
        self.assertIn('name="snapshot_id" value=""', response.text)
        self.assertIn('name="snapshot_date" value=""', response.text)
        self.assertIn('value="全球稳健配置组合"', response.text)
        self.assertIn('name="amount_0" value="100000.0"', response.text)
        self.assertIn('name="previous_amount_0" value="100000.0"', response.text)
        self.assertIn('name="previous_cumulative_pnl_amount_0" value="11800.0"', response.text)
        self.assertIn('name="transaction_amount_0" value="0"', response.text)
        self.assertIn('name="weekly_pnl_amount_0" value="0"', response.text)
        self.assertIn('name="cumulative_pnl_amount_0" value="11800.0"', response.text)
        self.assertIn('name="valuation_cutoff_date_0" value=""', response.text)
        self.assertIn('name="exposure_fixed_income_percent_0" value="60.0"', response.text)
        for index in range(3):
            self.assertRegex(
                response.text,
                rf'(?s)<select name="action_{index}">.*?'
                rf'<option value="hold" selected>持有</option>.*?</select>',
            )
            self.assertIn(
                f'name="transaction_amount_{index}" value="0"',
                response.text,
            )

        source_snapshot = self.client.get("/api/weekly-snapshots").json()[0]
        self.assertEqual(
            [holding["action"] for holding in source_snapshot["holdings"]],
            ["buy", "sell", "rebalance"],
        )

    def test_snapshot_form_persists_confirmed_external_flow(self) -> None:
        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-08-21",
                "external_net_flow_amount": "8000",
                "external_flow_confirmed": "1",
                "product_name_0": "现金",
                "account_type_0": "货币/现金账户",
                "amount_0": "110000",
                "allocation_percent_0": "100",
                "category_0": "cash",
                "action_0": "hold",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        snapshot = self.client.get("/api/weekly-snapshots").json()[0]
        self.assertEqual(snapshot["external_net_flow_amount"], 8000)
        self.assertTrue(snapshot["external_flow_confirmed"])

        copied = self.client.get(f"/?copy_id={snapshot['id']}")
        self.assertIn('name="external_net_flow_amount" value=""', copied.text)
        self.assertNotIn(
            'name="external_flow_confirmed" value="1" checked',
            copied.text,
        )

    def test_external_flow_script_preserves_persisted_and_manual_values(self) -> None:
        created = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-08-21",
                "total_assets": 110000,
                "cash_balance": 10000,
                "weekly_return_amount": 2000,
                "external_net_flow_amount": 8000,
                "external_flow_confirmed": False,
                "holdings": [
                    {
                        "product_name": "现金",
                        "account_type": "货币/现金账户",
                        "amount": 110000,
                        "allocation_percent": 100,
                        "category": "cash",
                    }
                ],
            },
        ).json()
        response = self.client.get(f"/?edit_id={created['id']}")
        flow_value_match = re.search(
            r'id="external-net-flow-input"\s+'
            r'name="external_net_flow_amount" value="([^"]*)"',
            response.text,
        )
        self.assertIsNotNone(flow_value_match)
        self.assertEqual(flow_value_match.group(1), "8000.0")
        script_matches = re.findall(r"<script>(.*?)</script>", response.text, re.DOTALL)
        self.assertEqual(len(script_matches), 1)

        harness = """
function makeInput(value = "", checked = false) {
  const listeners = {};
  return {
    value,
    checked,
    addEventListener(type, listener) { listeners[type] = listener; },
    dispatch(type) { listeners[type]?.({ target: this }); },
  };
}

const elements = {
  "holdings-container": {
    querySelectorAll() { return []; },
    insertAdjacentHTML() {},
    lastElementChild: null,
  },
  "add-holding-button-bottom": null,
  "holding-row-template": { innerHTML: "" },
  "total-assets-input": makeInput("110000"),
  "cash-balance-input": makeInput("10000"),
  "weekly-return-input": makeInput("2000"),
  "weekly-return-rate-input": makeInput(""),
  "ytd-return-input": makeInput(""),
  "external-net-flow-input": makeInput("8000.0"),
  "external-flow-confirmed": makeInput("", false),
  "previous-total-assets": makeInput("100000"),
};

globalThis.document = {
  getElementById(id) { return elements[id] ?? null; },
};
"""
        assertions = """
if (externalFlowInput.value !== "8000.0") {
  throw new Error(`initial persisted value overwritten: ${externalFlowInput.value}`);
}

externalFlowInput.value = "7500";
externalFlowInput.dispatch("input");
totalAssetsInput.value = "120000";
weeklyReturnInput.value = "3000";
recalculateExternalFlow();

if (externalFlowInput.value !== "7500") {
  throw new Error(`manual value overwritten after recalculation: ${externalFlowInput.value}`);
}
"""
        node_binary = shutil.which("node")
        if node_binary is None:
            bundled_node = (
                Path.home()
                / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
            )
            self.assertTrue(bundled_node.is_file(), "Node.js runtime is required")
            node_binary = str(bundled_node)
        result = subprocess.run(
            [node_binary, "-e", harness + script_matches[0] + assertions],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_form_submission_derives_pnl_from_previous_snapshot_and_transaction(self) -> None:
        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-06-29",
                "ytd_return_amount": "0",
                "product_name_0": "科创50",
                "account_type_0": "普通账户",
                "amount_0": "112000",
                "previous_amount_0": "100000",
                "previous_cumulative_pnl_amount_0": "8000",
                "transaction_amount_0": "5000",
                "allocation_percent_0": "0",
                "category_0": "equity",
                "action_0": "buy",
                "weekly_pnl_amount_0": "",
                "cumulative_pnl_amount_0": "",
                "valuation_cutoff_date_0": "2026-06-27",
                "holding_notes_0": "本周追加后自动推导盈亏",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

        snapshots = self.client.get("/api/weekly-snapshots").json()
        holding = snapshots[0]["holdings"][0]
        self.assertEqual(snapshots[0]["weekly_return_amount"], 7000)
        self.assertEqual(snapshots[0]["ytd_return_amount"], 15000)
        self.assertEqual(holding["weekly_pnl_amount"], 7000)
        self.assertEqual(holding["cumulative_pnl_amount"], 15000)
        self.assertEqual(holding["transaction_amount"], 5000)

    def test_form_submission_keeps_cash_pnl_zero_when_cash_balance_changes(self) -> None:
        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-06-29",
                "product_name_0": "现金账户",
                "account_type_0": "普通账户",
                "amount_0": "43191.46",
                "previous_amount_0": "43317.15",
                "previous_cumulative_pnl_amount_0": "0",
                "transaction_amount_0": "0",
                "allocation_percent_0": "0",
                "category_0": "cash",
                "action_0": "hold",
                "weekly_pnl_amount_0": "",
                "cumulative_pnl_amount_0": "",
                "valuation_cutoff_date_0": "2026-06-29",
                "holding_notes_0": "",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

        snapshots = self.client.get("/api/weekly-snapshots").json()
        holding = snapshots[0]["holdings"][0]
        self.assertEqual(snapshots[0]["weekly_return_amount"], 0)
        self.assertEqual(snapshots[0]["cash_balance"], 43191.46)
        self.assertEqual(holding["weekly_pnl_amount"], 0)
        self.assertEqual(holding["cumulative_pnl_amount"], 0)
        self.assertEqual(holding["transaction_amount"], 0)

    def test_form_submission_keeps_platform_return_rate_separate_from_strategy_pnl(self) -> None:
        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-07-03",
                "product_name_0": "易方达上证科创50联接A",
                "account_type_0": "普通账户",
                "amount_0": "50999.71",
                "previous_amount_0": "54685.02",
                "previous_cumulative_pnl_amount_0": "20296.67",
                "transaction_amount_0": "-2509.84",
                "allocation_percent_0": "0",
                "category_0": "equity",
                "action_0": "hold",
                "weekly_pnl_amount_0": "",
                "cumulative_pnl_amount_0": "",
                "platform_return_rate_percent_0": "49.94",
                "holding_cost_amount_0": "",
                "valuation_cutoff_date_0": "2026-07-03",
                "holding_notes_0": "",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

        snapshots = self.client.get("/api/weekly-snapshots").json()
        holding = snapshots[0]["holdings"][0]
        self.assertEqual(holding["weekly_pnl_amount"], -1175.47)
        self.assertAlmostEqual(holding["cumulative_pnl_amount"], 19121.20, places=2)
        self.assertEqual(holding["platform_return_rate_percent"], 49.94)
        self.assertAlmostEqual(holding["holding_return_rate_percent"], 49.94, places=2)

    def test_form_submission_initializes_cost_from_platform_return_rate(self) -> None:
        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-07-03",
                "product_name_0": "易方达上证科创50联接A",
                "account_type_0": "普通账户",
                "amount_0": "50999.71",
                "allocation_percent_0": "0",
                "category_0": "equity",
                "action_0": "hold",
                "weekly_pnl_amount_0": "-1175.47",
                "cumulative_pnl_amount_0": "19121.20",
                "platform_return_rate_percent_0": "49.94",
                "holding_cost_amount_0": "",
                "valuation_cutoff_date_0": "2026-07-03",
                "holding_notes_0": "",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

        holding = self.client.get("/api/weekly-snapshots").json()[0]["holdings"][0]
        self.assertEqual(holding["platform_return_rate_percent"], 49.94)
        self.assertAlmostEqual(holding["holding_cost_amount"], 34013.41, places=2)
        self.assertAlmostEqual(holding["holding_return_rate_percent"], 49.94, places=2)

    def test_form_submission_rolls_cost_basis_from_previous_snapshot_and_redemption(self) -> None:
        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-07-10",
                "product_name_0": "易方达上证科创50联接A",
                "account_type_0": "普通账户",
                "amount_0": "47000",
                "previous_amount_0": "50999.71",
                "previous_cumulative_pnl_amount_0": "19121.20",
                "previous_holding_cost_amount_0": "34013.48",
                "transaction_amount_0": "-3000",
                "allocation_percent_0": "0",
                "category_0": "equity",
                "action_0": "sell",
                "weekly_pnl_amount_0": "",
                "cumulative_pnl_amount_0": "",
                "platform_return_rate_percent_0": "",
                "holding_cost_amount_0": "",
                "valuation_cutoff_date_0": "2026-07-10",
                "holding_notes_0": "",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

        holding = self.client.get("/api/weekly-snapshots").json()[0]["holdings"][0]
        self.assertEqual(holding["weekly_pnl_amount"], -999.71)
        self.assertAlmostEqual(holding["holding_cost_amount"], 32012.68, places=2)
        self.assertAlmostEqual(holding["holding_return_rate_percent"], 46.82, places=2)

    def test_form_submission_updates_existing_snapshot(self) -> None:
        create_response = self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-18",
                "total_assets": 421000,
                "cash_balance": 80000,
                "weekly_return_amount": -3200,
                "ytd_return_amount": 8600,
                "notes": "First save",
                "holdings": [
                    {
                        "product_name": "中证全指指数组合",
                        "account_type": "普通账户",
                        "amount": 45000,
                        "allocation_percent": 10.69,
                        "category": "equity",
                        "action": "hold",
                        "weekly_pnl_amount": 900,
                        "valuation_cutoff_date": "2026-04-18",
                        "notes": "维持核心仓",
                    }
                ],
            },
        )
        snapshot_id = create_response.json()["id"]

        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_id": str(snapshot_id),
                "snapshot_date": "2026-04-18",
                "total_assets": "430000",
                "cash_balance": "70000",
                "weekly_return_amount": "2500",
                "ytd_return_amount": "11100",
                "data_cutoff_notes": "统一按周三口径",
                "notes": "补充保存",
                "product_name_0": "中证全指指数组合",
                "account_type_0": "普通账户",
                "amount_0": "50000",
                "allocation_percent_0": "11.63",
                "category_0": "equity",
                "action_0": "buy",
                "weekly_pnl_amount_0": "1250",
                "valuation_cutoff_date_0": "2026-04-18",
                "holding_notes_0": "继续加仓",
                "product_name_1": "全球稳健配置组合",
                "account_type_1": "第三方平台账户",
                "amount_1": "106174.32",
                "allocation_percent_1": "24.69",
                "category_1": "fixed_income",
                "action_1": "hold",
                "weekly_pnl_amount_1": "-180",
                "valuation_cutoff_date_1": "2026-04-17",
                "holding_notes_1": "固收60%，权益30%",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

        list_response = self.client.get("/api/weekly-snapshots")
        data = list_response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["total_assets"], 156174.32)
        self.assertEqual(data[0]["cash_balance"], 0)
        self.assertEqual(data[0]["weekly_return_amount"], 1070)
        self.assertEqual(len(data[0]["holdings"]), 2)
        self.assertEqual(data[0]["holdings"][1]["weekly_pnl_amount"], -180)
        self.assertEqual(data[0]["holdings"][1]["valuation_cutoff_date"], "2026-04-17")

    def test_dashboard_renders_analysis_sections(self) -> None:
        self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-11",
                "total_assets": 400000,
                "cash_balance": 30000,
                "weekly_return_amount": 2000,
                "ytd_return_amount": 3888,
                "holdings": [
                    {
                        "product_name": "现金账户",
                        "account_type": "货币/现金账户",
                        "amount": 30000,
                        "allocation_percent": 7.5,
                        "category": "cash",
                        "action": "hold",
                        "weekly_pnl_amount": 0,
                        "valuation_cutoff_date": "2026-04-11",
                        "notes": "",
                    }
                ],
            },
        )
        self.client.post(
            "/api/weekly-snapshots",
            json={
                "snapshot_date": "2026-04-18",
                "total_assets": 419896.25,
                "cash_balance": 33931.45,
                "weekly_return_amount": 7177.68,
                "ytd_return_amount": 11066.50,
                "data_cutoff_notes": "按照各个持仓的估值截止日进行统计",
                "notes": "本周A股行情较好",
                "holdings": [
                    {
                        "product_name": "全球稳健配置组合",
                        "account_type": "第三方平台账户",
                        "amount": 106174.32,
                        "allocation_percent": 25.29,
                        "category": "fixed_income",
                        "action": "hold",
                        "weekly_pnl_amount": 660.20,
                        "valuation_cutoff_date": "2026-04-16",
                        "notes": "",
                    },
                    {
                        "product_name": "中证全指指数组合",
                        "account_type": "第三方平台账户",
                        "amount": 87357.68,
                        "allocation_percent": 20.80,
                        "category": "equity",
                        "action": "hold",
                        "weekly_pnl_amount": 3130.62,
                        "valuation_cutoff_date": "2026-04-16",
                        "notes": "",
                    },
                    {
                        "product_name": "现金账户",
                        "account_type": "货币/现金账户",
                        "amount": 33931.45,
                        "allocation_percent": 8.08,
                        "category": "cash",
                        "action": "hold",
                        "weekly_pnl_amount": 0,
                        "valuation_cutoff_date": "2026-04-18",
                        "notes": "",
                    },
                ],
            },
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("目标配置", response.text)
        self.assertIn("穿透配置诊断", response.text)
        self.assertIn("主分类口径诊断", response.text)
        self.assertIn("推荐参考", response.text)
        self.assertIn("辅助口径", response.text)
        self.assertIn("本周收益归因", response.text)
        self.assertIn("净资金流", response.text)
        self.assertIn("较上一期推算净流入", response.text)
        self.assertIn("固收", response.text)
        self.assertIn("现金", response.text)


if __name__ == "__main__":
    unittest.main()
