# 招聘岗位 JSON 同步

管理端“招聘信息 → 招聘岗位 → 从数据源同步”读取维护人员配置的接口。页面不接受任意 URL，也不显示地址或认证令牌。

在管理后端环境中配置后重启管理后端：

```dotenv
JOB_POSTING_SYNC_ENDPOINT=https://your-feed.example/jobs
JOB_POSTING_SYNC_SOURCE=campus-feed
# 可选；使用 Authorization: Bearer，带令牌必须使用 HTTPS
JOB_POSTING_SYNC_TOKEN=
```

数据源通过 GET 返回 UTF-8 JSON，顶层可为数组或如下对象：

```json
{
  "items": [
    {
      "id": "job-001",
      "title": "软件工程师",
      "company": "示例公司",
      "city": "上海",
      "description": "岗位职责",
      "requirements": "任职要求",
      "skills": ["Python", "SQL"],
      "tags": ["校招"],
      "headcount": 5,
      "status": "active",
      "published": true
    }
  ]
}
```

- `title` 和稳定的 `id`（或 `source_ref`）必填。相同数据源标识和外部编号重复同步时更新，不重复创建。更换接口但仍为同一数据源时保留 SOURCE；不同数据源使用不同 SOURCE。
- 可选字段与招聘岗位表单的 snake_case 字段一致。`skills`、`tags` 支持字符串或字符串数组。忽略远端的本地岗位目录 ID。
- `status` 为 `active` 或 `disabled`，新岗位默认启用；`published` 默认为 true。更新时未提供的字段保留原值，空字符串清空相应文本。
- 不删除数据源中消失的岗位，不改动手动或 Excel 来源的岗位。需要下架时发送同一编号并设置 `status: disabled`。
- 单次最多 2000 条、5 MB，网络读取超时 15 秒。不跟随 HTTP 重定向；不自动翻页，需要数据源适配成这一格式。
- 无效记录跳过并显示最多 20 条错误；有效记录写入。整批网络或 JSON 格式错误不写入。数据库异常回滚本批写入。
- 操作沿用岗位管理权限和来源校验，并记录新增、更新、失败数量的审计日志。

未配置数据源时页面禁用同步按钮。通用接口完成后，具体招聘平台仍需按上述格式提供数据；当前没有接入任何真实第三方平台。
