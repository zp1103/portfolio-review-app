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

## Docker Compose 运行

```bash
docker compose up --build
```

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
```

说明：

- `APP_PORT`：宿主机对外暴露端口
- `DATA_DIR`：SQLite 数据库存放目录，建议在服务器上使用持久化路径
- `TZ`：容器时区
- `IMAGE_NAME`：构建后的镜像名称
- `PIP_INDEX_URL`：可选的 Python 包镜像源
- `PIP_EXTRA_INDEX_URL`：可选的额外 Python 包索引

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
