# 多 Agent 面试系统

这是一个前后端分离的 AI 模拟面试项目，包含候选人端、管理端、业务 API 和管理 API。候选人端用于简历分析、面试配置、电话面试、复盘报告和能力画像；管理端用于查看和管理系统数据。

## 项目结构

```text
.
├── frontend/        # 候选人端 React + Vite 应用
├── backend/         # 候选人端 FastAPI 服务，默认端口 3001
├── admin/           # 管理端 React + Vite 应用，默认端口 5174
├── admin_backend/   # 管理端 FastAPI 服务，默认端口 3002
├── data/            # 本地数据库运行数据，已忽略
├── logs/            # 本地服务日志，已忽略
├── package.json     # 根目录脚本入口
└── 项目说明书.md      # 更完整的功能和接口说明
```

## 本地启动

### 1. 安装依赖

```bash
npm install
python3 -m pip install -r backend/requirements.txt
python3 -m pip install -r admin_backend/requirements.txt
```

### 2. 准备环境变量

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
cp admin_backend/.env.example admin_backend/.env
cp admin/.env.example admin/.env
```

然后按本机数据库和模型服务配置修改 `backend/.env`。候选人端后端默认使用 MySQL；管理端本地示例默认可以读 `backend/data/dev.sqlite`，也可以切换到 MySQL。

### 3. 启动候选人端

```bash
npm run dev:backend
npm run dev:frontend
```

默认地址：

- 前端：http://127.0.0.1:5173/
- 后端：http://127.0.0.1:3001/

### 4. 启动管理端

```bash
npm run dev:admin-backend
npm run dev:admin
```

默认地址：

- 管理端前端：http://127.0.0.1:5174/
- 管理端后端：http://127.0.0.1:3002/

## 常用命令

```bash
npm run build          # 构建候选人端
npm run build:admin    # 构建管理端
npm run preview        # 预览候选人端构建产物
npm run preview:admin  # 预览管理端构建产物
```

## ngrok 调试

如果用 ngrok 暴露 Vite 开发服务，需要把当前 ngrok 域名加入 `frontend/.env` 的 `VITE_ALLOWED_HOSTS`。例如：

```env
VITE_ALLOWED_HOSTS=.ngrok-free.dev
```

`.ngrok-free.dev` 会允许 ngrok 免费域名下的临时子域名；改完后重启前端服务。

## 会议室无 HDMI 演示

推荐让演示电脑通过同一个前端入口访问，并继续由 Vite 把 `/api` 和 `/ws` 代理到本机后端。这样浏览器看到的是同源请求，登录 Cookie 最稳定。

### 局域网 IP 访问

假设开发机 IP 是 `192.168.1.23`：

```env
# frontend/.env
VITE_DEV_HOST=0.0.0.0
VITE_ALLOWED_HOSTS=192.168.1.23
VITE_API_PROXY_TARGET=http://127.0.0.1:3001
VITE_API_BASE_URL=

# backend/.env
FRONTEND_ORIGIN=http://127.0.0.1:5173,http://192.168.1.23:5173
COOKIE_SECURE=false
COOKIE_SAMESITE=lax
```

然后重启前后端，在演示电脑打开：

```text
http://192.168.1.23:5173/
```

局域网 HTTP 适合展示登录、简历、配置、报告等页面；如果要演示浏览器麦克风或实时语音，建议使用 HTTPS tunnel，因为非 localhost 的 HTTP 地址通常不是浏览器认可的安全上下文。

### HTTPS tunnel 访问

如果只映射前端，例如 `https://demo.ngrok-free.dev`，保持 `VITE_API_BASE_URL=` 为空，让 `/api` 仍然走 Vite proxy，并把域名加入：

```env
# frontend/.env
VITE_ALLOWED_HOSTS=.ngrok-free.dev

# backend/.env
FRONTEND_ORIGIN=http://127.0.0.1:5173
FRONTEND_ORIGIN_REGEX=https://.*\.ngrok-free\.dev
```

如果前端和后端分别映射成两个 HTTPS 域名，则需要跨站 Cookie：

```env
# frontend/.env
VITE_API_BASE_URL=https://api-demo.ngrok-free.dev

# backend/.env
FRONTEND_ORIGIN=https://demo.ngrok-free.dev
COOKIE_SECURE=true
COOKIE_SAMESITE=none
```

改完环境变量后必须重启服务；如果浏览器里已有旧 Cookie，先清理当前站点数据再登录。

## 上线前配置检查

部署上线前必须收紧演示配置，不能沿用 ngrok 或局域网调试设置：

```env
# backend/.env
APP_ENV=production
FRONTEND_ORIGIN=https://your-production-domain.example
FRONTEND_ORIGIN_REGEX=
ALLOW_PRIVATE_NETWORK_ORIGINS=false
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
COOKIE_DOMAIN=
```

如果生产环境前后端分成不同站点，按实际域名设置 `VITE_API_BASE_URL` 和 `FRONTEND_ORIGIN`；如果是跨站 Cookie，必须使用 `COOKIE_SECURE=true` 和 `COOKIE_SAMESITE=none`。生产环境不需要 `VITE_ALLOWED_HOSTS`，它只服务于 Vite 本地开发。

## 本地运行产物

以下目录和文件是本地运行产物，已经通过 `.gitignore` 忽略：

- `node_modules/`
- `dist/`
- `logs/`
- `data/`
- `backend/data/`
- `.env`
- `.DS_Store`
