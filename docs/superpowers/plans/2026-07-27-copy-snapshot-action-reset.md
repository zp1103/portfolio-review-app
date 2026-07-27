# Copy Snapshot Action Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every holding in a “copy as new snapshot” draft starts with action `hold`, while preserving all existing edit, create, API, and historical-record behavior.

**Architecture:** Keep the change at the existing copy-view-model boundary in `app.main._build_form_values()`. Extend the existing API/page regression tests to prove copied `buy`, `sell`, and `rebalance` actions become `hold`, while editing and source data remain unchanged.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Pydantic, `unittest`, SQLite, Docker Compose.

## Global Constraints

- Only `/?copy_id=<snapshot_id>` copy drafts may change behavior.
- Every copied holding action becomes `hold`, including original `buy`, `sell`, and `rebalance` actions.
- Copied `transaction_amount` and `weekly_pnl_amount` remain `0`.
- Original snapshots, edit drafts, normal create submissions, JSON API behavior, and historical database records remain unchanged.
- No new dependency, database migration, template normalization, or service-layer normalization is allowed.
- Deployment target is `root@192.168.3.57:/data/work/project/portfolio-review-app`, exposed on host port `1103`.

---

## File Structure

- Modify `tests/test_api.py`: extend copy and edit page regression coverage.
- Modify `app/main.py`: reset the copied holding action in `_build_form_values()`.
- No new runtime modules or database changes.

### Task 1: Reset Actions in Copy Drafts

**Files:**
- Modify: `tests/test_api.py:174-259`
- Modify: `app/main.py:255-287`

**Interfaces:**
- Consumes: `_build_form_values(snapshot, copy_as_new: bool = False) -> dict`
- Produces: when `copy_as_new=True`, every item in returned `holdings` has `action == "hold"`; when false, the source action is preserved.

- [ ] **Step 1: Write the failing regression test**

In `test_dashboard_can_copy_existing_snapshot_as_new_draft`, replace the single `hold` fixture with three holdings whose actions are `buy`, `sell`, and `rebalance`. Keep valid amounts, categories, allocations, and transaction amounts:

```python
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
```

After fetching `/?copy_id=<id>`, assert each indexed action select has `hold` selected and each transaction amount is zero:

```python
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
```

Add an assertion to `test_dashboard_can_prefill_existing_snapshot_for_editing` proving edit mode preserves `buy`:

```python
self.assertRegex(
    response.text,
    r'(?s)<select name="action_0">.*?'
    r'<option value="buy" selected>买入</option>.*?</select>',
)
```

- [ ] **Step 2: Run the targeted test and verify RED**

Run:

```bash
python -m unittest \
  tests.test_api.ApiTests.test_dashboard_can_copy_existing_snapshot_as_new_draft \
  tests.test_api.ApiTests.test_dashboard_can_prefill_existing_snapshot_for_editing \
  -v
```

Expected: the copy test fails because the copied actions remain `buy`, `sell`, and `rebalance`; the edit test passes.

- [ ] **Step 3: Implement the minimal production change**

In `app/main.py`, change only the `action` field inside `_build_form_values()`:

```python
"action": "hold" if copy_as_new else holding.action,
```

Do not modify form extraction, schemas, service methods, templates, or database code.

- [ ] **Step 4: Run the targeted test and verify GREEN**

Run:

```bash
python -m unittest \
  tests.test_api.ApiTests.test_dashboard_can_copy_existing_snapshot_as_new_draft \
  tests.test_api.ApiTests.test_dashboard_can_prefill_existing_snapshot_for_editing \
  -v
```

Expected: both tests pass.

- [ ] **Step 5: Run the full test suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass with no errors or failures.

- [ ] **Step 6: Review the diff**

Run:

```bash
git diff --check
git diff -- app/main.py tests/test_api.py
```

Expected: one production-line change plus focused test-fixture and assertion changes; no whitespace errors.

- [ ] **Step 7: Commit the implementation**

```bash
git add app/main.py tests/test_api.py
git commit -m "fix: reset actions when copying snapshots"
```

### Task 2: Publish and Deploy to 3.57

**Files:**
- No source-file changes.
- Remote deployment directory: `/data/work/project/portfolio-review-app`
- Runtime service: Docker Compose service `portfolio-review`, container `portfolio-review-app`

**Interfaces:**
- Consumes: committed and locally verified `main` branch.
- Produces: updated healthy container on `192.168.3.57:1103`.

- [ ] **Step 1: Verify the local branch is ready to publish**

Run:

```bash
git status --short --branch
git log -3 --oneline --decorate
```

Expected: clean `main` branch containing the design, plan, and implementation commits.

- [ ] **Step 2: Push the verified commits**

Run:

```bash
git push origin main
```

Expected: `origin/main` advances to the local implementation commit.

- [ ] **Step 3: Verify the remote checkout before deployment**

Run:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "cd /data/work/project/portfolio-review-app && git status --short --branch"
```

Expected: the remote checkout is clean and behind `origin/main`. If it has unrelated changes, stop without overwriting them.

- [ ] **Step 4: Fast-forward and rebuild the service**

Run:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "cd /data/work/project/portfolio-review-app && git pull --ff-only && docker compose up -d --build"
```

Expected: Git fast-forwards successfully and Compose recreates or restarts `portfolio-review-app` without errors.

- [ ] **Step 5: Verify container and HTTP health**

Run:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "cd /data/work/project/portfolio-review-app && docker compose ps --format json"

ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "curl -sS --connect-timeout 5 -w '\nhttp_status=%{http_code}\n' http://127.0.0.1:1103/health"
```

Expected: container state is `running`, health is `healthy`, and `/health` returns `{"status":"ok"}` with HTTP 200.

- [ ] **Step 6: Run a read-only production behavior smoke test**

Run:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.3.57 \
  "docker exec portfolio-review-app python -c \"import json,re,urllib.request; snapshots=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/weekly-snapshots')); assert snapshots, 'no snapshots available'; sid=snapshots[0]['id']; html=urllib.request.urlopen(f'http://127.0.0.1:8000/?copy_id={sid}').read().decode(); actions=re.findall(r'<select name=\\\"action_\\d+\\\">.*?<option value=\\\"([^\\\"]+)\\\" selected>', html, re.S); assert actions and set(actions)=={'hold'}, actions; print({'snapshot_id': sid, 'copied_actions': actions})\""
```

Expected: the command prints the selected snapshot ID and a non-empty list containing only `hold`. The test performs no writes.

- [ ] **Step 7: Report deployment evidence**

Report:

- local full-test result;
- implementation commit SHA;
- pushed branch;
- remote deployed commit SHA;
- container health;
- `/health` HTTP status;
- read-only copy-draft smoke-test result.
