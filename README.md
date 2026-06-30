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

如果用 ngrok 暴露 Vite 开发服务，需要把当前 ngrok 域名加入 `frontend/vite.config.js` 的 `server.allowedHosts`。例如：

```js
server: {
  host: '127.0.0.1',
  allowedHosts: ['freckles-flying-patio.ngrok-free.dev'],
}
```

ngrok 免费域名变化后，需要同步更新这里并重启前端服务。

## 本地运行产物

以下目录和文件是本地运行产物，已经通过 `.gitignore` 忽略：

- `node_modules/`
- `dist/`
- `logs/`
- `data/`
- `backend/data/`
- `.env`
- `.DS_Store`

