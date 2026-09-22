# 第四版原始前端

本次直接使用 D:/Astrainterview/v4 的完整 HTML、CSS、JavaScript 及 PDF 资源，未移植或混用旧 React 页面。

入口是 frontend/index.html；原始脚本、样式与 vendor 位于 frontend/public，全部与 v4 源文件进行 SHA256 校验。传统脚本保持原顺序加载，Vite 构建时直接复制静态资源，不将其转换成 ES 模块。

端口与代理配置未改：前端默认 5173，后端 3001。启动 npm run dev:frontend，构建 npm run build。

界面采用第四版原型行为：演示登录、固定面试题、本地录音、示例报告；并未接入项目的真实认证、数据库和 AI 服务。后端和管理员端代码保持不变。

原 React 前端及上一次适配文件已备份到 D:/Astrainterview/ui-integration/before-exact-v4-*，不再由当前项目入口加载。
