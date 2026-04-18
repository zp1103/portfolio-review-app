import shutil
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

    def test_healthcheck_returns_ok(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

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
        self.assertIn("估值截止 2026-04-18", response.text)

    def test_form_submission_creates_snapshot_and_redirects(self) -> None:
        response = self.client.post(
            "/snapshots",
            data={
                "snapshot_date": "2026-04-25",
                "total_assets": "430000",
                "cash_balance": "70000",
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
        self.assertEqual(data[0]["total_assets"], 430000)
        self.assertEqual(data[0]["weekly_return_amount"], 1070)
        self.assertEqual(len(data[0]["holdings"]), 2)
        self.assertEqual(data[0]["holdings"][1]["weekly_pnl_amount"], -180)
        self.assertEqual(data[0]["holdings"][1]["valuation_cutoff_date"], "2026-04-17")

    def test_dashboard_renders_analysis_sections(self) -> None:
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
        self.assertIn("当前配置诊断", response.text)
        self.assertIn("本周收益归因", response.text)


if __name__ == "__main__":
    unittest.main()
