[CmdletBinding()]
param(
  [string]$Prefix = 'schoolapp',
  [string]$ClientHost = 'localhost'
)

# Windows 兼容入口只打印原生分域 DDL，不接收口令、不运行 mysql、不修改 .env。
$ErrorActionPreference = 'Stop'
& node (Join-Path $PSScriptRoot 'native-mysql-plan.js') --prefix $Prefix --client-host $ClientHost
exit $LASTEXITCODE
