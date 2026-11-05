// 仅生成供 DBA 审核的 MySQL 8 DDL。此工具不连接数据库、不读取部署环境，也不接收密码。
'use strict';

const { isIP } = require('node:net');
const owners = ['identity', 'profile', 'career', 'training', 'interview', 'media', 'assessment',
  'analytics', 'credentials', 'usage', 'provenance', 'providers', 'operations'];
const ownerRights = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'REFERENCES', 'INDEX'];

function sqlPlan(prefix = 'schoolapp', host = 'localhost') {
  // 数据库级 GRANT 会解释下划线和百分号通配符。生成的库名只含 ASCII 字母或数字。
  if (!/^[a-z][a-z0-9]{0,14}$/.test(prefix) || !(typeof host === 'string' && host.length <= 60 && (isIP(host) || host.split('.').every(label => /^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/.test(label)))))
    throw new Error('前缀须为 1 至 15 位小写字母数字；客户端须为精确主机名或 IP，不能使用通配符。');
  const rows = [...owners, 'verifier'].map(role => ({
    user: prefix + role, host, db: prefix + (role === 'verifier' ? 'credentials' : role), readonly: role === 'verifier',
  }));
  const allowed = ownerRights.map(r => "'"+r+"'").join(',');
  const joins = "p ON BINARY g.GRANTEE=BINARY CONCAT(QUOTE(p.account_name),'@',QUOTE(p.client_host))";
  const plan = [
    '-- MySQL 8.0.16+。请在专用 DBA 会话中按顺序执行，遇错即停，禁止 --force。没有连接或写入旧库的步骤。',
    '-- 先验证同名账号已有的权限。新账号使用 TLS 且保持锁定，由秘密管理系统设置认证与解锁。',
    'SET @native_acl_ok=0;',
    'DROP TEMPORARY TABLE IF EXISTS mysql.native_plan_accounts, mysql.native_plan_guard;',
    '-- 以下临时表仅在当前 DBA 会话中存在。检查失败时不得继续执行后续 GRANT。',
    'CREATE TEMPORARY TABLE mysql.native_plan_accounts (account_name VARCHAR(32) COLLATE utf8mb4_bin, client_host VARCHAR(60) COLLATE utf8mb4_bin, db_name VARCHAR(64) COLLATE utf8mb4_bin, read_only_role BOOL) CHARACTER SET utf8mb4;',
    'INSERT INTO mysql.native_plan_accounts VALUES '+ rows.map(r => "('"+r.user+"','"+r.host+"','"+r.db+"',"+(r.readonly?1:0)+')').join(',\n')+';',
    'CREATE TEMPORARY TABLE mysql.native_plan_guard (problem_count BIGINT NOT NULL CHECK(problem_count=0));',
    // 权限目录的服务器排序规则可能不同；标识逐字节比较，避免误把同形主体列入合法登录集。
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM mysql.user u JOIN mysql.native_plan_accounts p ON BINARY u.User=BINARY p.account_name AND BINARY u.Host=BINARY p.client_host WHERE u.ssl_type='' OR (u.account_locked='N' AND COALESCE(u.authentication_string,'')='');",
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM mysql.user u JOIN mysql.native_plan_accounts p ON BINARY u.User=BINARY p.account_name WHERE BINARY u.Host<>BINARY p.client_host;",
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM information_schema.SCHEMATA d JOIN mysql.native_plan_accounts p ON BINARY d.SCHEMA_NAME=BINARY p.db_name WHERE d.DEFAULT_COLLATION_NAME NOT IN ('utf8mb4_bin','utf8mb4_0900_bin');",
    // 新账号不自动接管已有数据。只有显式绑定到本库的原专用账号可以在有业务表时重跑授权。
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM mysql.native_plan_accounts p WHERE p.read_only_role=0 AND EXISTS (SELECT 1 FROM information_schema.TABLES t WHERE BINARY t.TABLE_SCHEMA=BINARY p.db_name) AND NOT EXISTS (SELECT 1 FROM information_schema.SCHEMA_PRIVILEGES g WHERE BINARY g.GRANTEE=BINARY CONCAT(QUOTE(p.account_name),'@',QUOTE(p.client_host)) AND BINARY g.TABLE_SCHEMA=BINARY p.db_name);",
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM mysql.role_edges e JOIN mysql.native_plan_accounts p ON BINARY e.FROM_USER=BINARY p.account_name AND BINARY e.FROM_HOST=BINARY p.client_host;",
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM information_schema.USER_PRIVILEGES g JOIN mysql.native_plan_accounts "+joins+" WHERE g.PRIVILEGE_TYPE<>'USAGE' OR g.IS_GRANTABLE='YES';",
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM information_schema.SCHEMA_PRIVILEGES g JOIN mysql.native_plan_accounts "+joins+" WHERE BINARY g.TABLE_SCHEMA<>BINARY p.db_name OR g.IS_GRANTABLE='YES' OR g.PRIVILEGE_TYPE NOT IN ("+allowed+") OR (p.read_only_role AND g.PRIVILEGE_TYPE<>'SELECT');",
    ...['TABLE_PRIVILEGES','COLUMN_PRIVILEGES'].map(name => "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM information_schema."+name+" g JOIN mysql.native_plan_accounts "+joins+";"),
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM mysql.role_edges e JOIN mysql.native_plan_accounts p ON BINARY e.TO_USER=BINARY p.account_name AND BINARY e.TO_HOST=BINARY p.client_host;",
    ...['procs_priv','proxies_priv','global_grants'].map(name => "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM mysql."+name+" g JOIN mysql.native_plan_accounts p ON BINARY g.User=BINARY p.account_name AND BINARY g.Host=BINARY p.client_host;"),
    "INSERT INTO mysql.native_plan_guard SELECT COUNT(*) FROM mysql.proxies_priv g JOIN mysql.native_plan_accounts p ON BINARY g.Proxied_user=BINARY p.account_name AND BINARY g.Proxied_host=BINARY p.client_host;",
    // 强制角色会隐式赋予所有新账号权限。此计划无法隔离这种服务器设置，应先由 DBA 核实。
    "INSERT INTO mysql.native_plan_guard SELECT IF(@@GLOBAL.mandatory_roles='',0,1);",
  ];
  const checks = plan.filter(line => line.startsWith('INSERT INTO mysql.native_plan_guard')).length;
  plan.push('SET @native_acl_ok=(SELECT COUNT(*)='+checks+' AND COALESCE(SUM(problem_count),1)=0 FROM mysql.native_plan_guard);');
  function guarded(statement) {
    // CHECK 失败的规则不会产生记录。即使客户端忽略错误继续执行，未经全部预检也只能调用空操作。
    const literal = statement.replaceAll("'", "''");
    plan.push("SET @native_acl_sql=IF(@native_acl_ok=1,'"+literal+"','DO 0');",
              'PREPARE native_acl_statement FROM @native_acl_sql;', 'EXECUTE native_acl_statement;',
              'DEALLOCATE PREPARE native_acl_statement;');
  }
  for (const r of rows) {
    const account="'"+r.user+"'@'"+r.host+"'";
    if (!r.readonly) guarded('CREATE DATABASE IF NOT EXISTS `'+r.db+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin');
    guarded('CREATE USER IF NOT EXISTS '+account+' REQUIRE SSL ACCOUNT LOCK');
    guarded('GRANT '+(r.readonly?'SELECT':ownerRights.join(', '))+' ON `'+r.db+'`.* TO '+account);
  }
  plan.push('DROP TEMPORARY TABLE mysql.native_plan_accounts, mysql.native_plan_guard;');
  return plan.join('\n')+'\n';
}

if (require.main === module) {
  try {
    const args = process.argv.slice(2);
    if (args.includes('--help')) {
      console.log('用法：npm run db:init:mysql -- --prefix schoolapp --client-host localhost\n输出 DDL 供审核，不连接数据库。');
    } else {
      const options = {};
      for (let i=0; i<args.length; i+=2) {
        if (!['--prefix','--client-host'].includes(args[i]) || !args[i+1] || Object.hasOwn(options,args[i]))
          throw new Error('参数错误。只接受 --prefix 和 --client-host。');
        options[args[i]] = args[i+1];
      }
      process.stdout.write(sqlPlan(options['--prefix'],options['--client-host']));
    }
  } catch (err) { console.error(err.message); process.exitCode=2; }
}
module.exports = { sqlPlan };
