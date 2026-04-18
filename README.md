# Portfolio Review App

A股资产复盘工具，本地运行的周度资产记录、配置复盘与历史分析系统。

## MVP scope

- Weekly snapshot entry
- Holdings persistence in SQLite
- Allocation summary by category
- Local dashboard for review
- Docker Compose deployment

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

## Run with Docker Compose

```bash
docker compose up --build
```
