# MySQL 分域建库与离线备份整理

## 建库和权限检查

在源码目录运行 `npm run --silent db:init:mysql -- --prefix schoolapp --client-host 127.0.0.1`。此命令只向标准输出写 SQL：不会连接数据库、读取或修改 `.env`，也不接收密码。Windows 兼容入口为 `scripts/init-mysql-db.ps1 -Prefix schoolapp -ClientHost 127.0.0.1`。前缀须为 1–15 位小写字母数字，客户端来源为精确主机/IP。示例仅适合同机 TCP 访问；部署时替换为数据库实际看到的受控客户端来源。

DBA 应在 MySQL 8.0.16 及以上专用会话审查整份计划后执行，客户端遇错即停止，禁止使用 `--force`。计划使用会话临时表读取授权元数据进行核对。预检拒绝非 TLS 的同名账号、额外的全局、跨库、表级/列级、代理、角色或可转授权限；目标库已有业务表而无已绑定域内权限时也拒绝接管。失败时检查现有账号/库，重新选择未使用的部署前缀，或者由 DBA 纠正归属后再重复执行。计划不会撤销历史授权或轮换现有密码。

每个独立环境有 13 个数据所有者，库名与账号均为前缀加 `identity/profile/career/training/interview/media/assessment/analytics/credentials/usage/provenance/providers/operations` 中的一项。库使用 UTF-8 二进制排序，权限限于本库数据和初始化所需的建表、修改、索引、引用。两座业务网关不分配数据库账户。公开验真用单独的 `<前缀>verifier` 账号，在 `<前缀>credentials` 只有 SELECT。每个学校的单校数据库需独立选择前缀和运行绑定；实际标识列按 [标识列检查](MYSQL-IDENTIFIERS.md) 再验。

新建账号是 `REQUIRE SSL ACCOUNT LOCK` 的占位账号。通过学校秘密管理流程设置认证材料，再解锁并分发给相应服务。不要在 SQL 计划、仓库、日志、终端参数或同一共享环境中存储密码。已配置的专用账号重跑计划时保留原凭据与锁定状态。数据库地址/用户名/密码按域前缀（如 `IDENTITY_MYSQL_*`）注入，公开验真亦使用 `CREDENTIALS_MYSQL_*` 字段，但只注入 verifier 凭据。服务启动仍应使用专属标识、TLS 信任及学校绑定。

可在一次性 Unix 套接字实例复验 `python scripts/check_native_mysql_plan.py --mysqld /path/to/mysql/bin/mysqld`。脚本只启动新的临时数据目录，不接受现有数据库 DSN。

## 旧演示与物理备份

旧演示数据写入命令已关闭。新学校用 `python -m services.identity.bootstrap --help` 录入首个校级账号，集成演练采用临时合成学校。

`scripts/import_ibd_backup.py` 仅供离线阶段整理 MySQL 物理备份，不作为在线系统恢复入口。需要管理员已审核的本地 ibd2sql 提取器、只读备份目录、**无记录的可信 SQLite 结构模板**，以及仓库外尚不存在的输出文件。先在隔离、加密、有足够容量的暂存卷上操作：

```sh
python scripts/import_ibd_backup.py --schema /offline/empty.sqlite --backup-dir /offline/ibd --extractor /tools/ibd2sql/main.py --row-counts /offline/counts.json --output /offline/recovered.sqlite
```

`counts.json` 用表名映射到已核对的行数。未提供清单时，仅接受每个备份表都能提取出非空结果；空表必须显式核对为零。转换器仅取得备份文件的临时副本。工具只解释单行、带显式列名及字面值的 INSERT/REPLACE，拒绝额外 SQL、未知表列、重复键、触发器或非空模板，不执行转换器返回的 SQL。结果全部通过检查后，以同一文件系统的硬链接原子发布，禁止覆盖已存在路径。物理页损坏、版本差异、无法无损表示的 MySQL 特性需要先在受控环境修复或转换，这个工具不能修复损坏的物理页。产物含学生资料，须按学校备份制度保管，并按各域迁移工具分批核对后切换。

旧 `e2e_student_registration.py` 命令已改接真实学校管理浏览器验收。传入只读构建目录，例如 `python scripts/e2e_student_registration.py --admin-build /tmp/admin-build`，测试使用新建服务、身份数据库和学校记录。旧 `e2e_resume_form.py` 命令运行原生简历表单及签名服务契约测试，源码副本中只有 `services/` 和 `shared/`；不再向运行中的旧服务器发送测试请求。
