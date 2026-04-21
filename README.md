# Portfolio Review App

A股资产复盘工具，本地运行的周度资产记录、配置复盘与历史分析系统。

## 功能范围

- Weekly snapshot entry
- Holdings persistence in SQLite
- Allocation summary by category
- Local dashboard for review
- Docker Compose deployment

## 本地运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

如需在首次运行时自动生成演示数据：

```bash
$env:SEED_DEMO_DATA="true"
uvicorn app.main:app --reload
```

## Docker Compose 运行

```bash
docker compose up --build
```

如需启用演示数据初始化，在 `.env` 中设置：

```env
SEED_DEMO_DATA=true
```

然后启动：

```bash
docker compose up --build
```

## 演示数据初始化

应用支持通过环境变量 `SEED_DEMO_DATA=true` 自动生成演示数据。

**特性：**
- 仅当数据库中**没有**周快照时才会生成
- 生成最近约 20 周的伪造持仓快照
- 覆盖以下资产类别：
  - 权益 (equity)：中证全指、科创50、创业板指数等
  - 固收 (fixed_income)：全球稳健配置组合、纯债基金等
  - 现金 (cash)：现金账户
  - 黄金 (gold)：黄金ETF
- 已有快照时**不会**重复生成，保护真实数据

**使用场景：**
- 初次体验系统功能
- 演示配置分析功能
- 开发测试

**注意：** 一旦数据库中存在真实数据，即使设置 `SEED_DEMO_DATA=true` 也不会生成演示数据。

## 服务器部署

### 1. 拉取代码

```bash
git clone https://github.com/zp1103/portfolio-review-app.git
cd portfolio-review-app
```

### 2. 准备环境变量

复制一份部署配置：

```bash
cp .env.example .env
```

默认配置如下：

```env
APP_PORT=8000
DATA_DIR=./data
TZ=Asia/Shanghai
IMAGE_NAME=portfolio-review-app:latest
PIP_INDEX_URL=
PIP_EXTRA_INDEX_URL=
SEED_DEMO_DATA=false
```

说明：

- `APP_PORT`：宿主机对外暴露端口
- `DATA_DIR`：SQLite 数据库存放目录，建议在服务器上使用持久化路径
- `TZ`：容器时区
- `IMAGE_NAME`：构建后的镜像名称
- `PIP_INDEX_URL`：可选的 Python 包镜像源
- `PIP_EXTRA_INDEX_URL`：可选的额外 Python 包索引
- `SEED_DEMO_DATA`：是否启用演示数据初始化（仅在空库时生效）

如果你希望数据库落在固定目录，例如 `/opt/portfolio-review/data`，可以改成：

```env
DATA_DIR=/opt/portfolio-review/data
```

如果服务器访问 PyPI 较慢，可以把 Python 包源改成你内网可访问的镜像，例如：

```env
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

当前 Dockerfile 已做两项弱网优化：

- 先显式安装 `pip/setuptools/wheel`
- 安装项目时关闭 `build isolation`，避免重复下载构建依赖

### 3. 启动服务

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f
```

停止服务：

```bash
docker compose down
```

### 4. 升级发布

服务器上更新代码后执行：

```bash
git pull
docker compose up -d --build
```

### 5. 反向代理建议

如果你准备绑定域名，建议在服务器前面加一层 Nginx 或 Caddy：

- 外部只开放 `80/443`
- 应用容器继续监听内部 `8000`
- 由反向代理负责 HTTPS 和域名转发

## Compose 配置说明

当前 `docker-compose.yml` 已包含：

- `restart: unless-stopped`
- 数据目录挂载到 `/app/data`
- 健康检查 `/health`
- 可配置端口与数据目录

## 数据说明

- SQLite 数据库默认保存在容器内的 `/app/data/portfolio.db`
- 只要 `DATA_DIR` 对应的宿主机目录还在，重建容器不会丢数据

## 测试

```bash
python -m unittest discover -s tests -v
```
