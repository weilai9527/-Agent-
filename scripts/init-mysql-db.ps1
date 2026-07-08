param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 3306,
  [string]$User = "root",
  [string]$Database = "multi_agent_interview",
  [string]$Charset = "utf8mb4"
)

$ErrorActionPreference = "Stop"

function ConvertFrom-SecureStringPlainText {
  param([securestring]$SecureValue)

  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

$mysql = (Get-Command mysql.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $mysql) {
  $defaultPath = "C:\Program Files\MySQL\MySQL Server 9.6\bin\mysql.exe"
  if (Test-Path $defaultPath) {
    $mysql = $defaultPath
  }
}

if (-not $mysql) {
  throw "mysql.exe was not found. Add MySQL Server bin directory to PATH, then retry."
}

$securePassword = Read-Host "Enter MySQL password for user '$User'" -AsSecureString
$plainPassword = ConvertFrom-SecureStringPlainText $securePassword

$databaseNamePattern = "^[A-Za-z0-9_]+$"
if ($Database -notmatch $databaseNamePattern) {
  throw "Database name can only contain letters, numbers, and underscores."
}
if ($Charset -notmatch $databaseNamePattern) {
  throw "Charset can only contain letters, numbers, and underscores."
}

$sql = "CREATE DATABASE IF NOT EXISTS ``$Database`` CHARACTER SET $Charset COLLATE ${Charset}_unicode_ci"

$previousMysqlPwd = $env:MYSQL_PWD
try {
  $env:MYSQL_PWD = $plainPassword
  & $mysql -h $HostName -P $Port -u $User --default-character-set=$Charset --execute=$sql
  if ($LASTEXITCODE -ne 0) {
    throw "MySQL command failed with exit code $LASTEXITCODE."
  }
} finally {
  $env:MYSQL_PWD = $previousMysqlPwd
}

$envPath = Join-Path $PSScriptRoot "..\backend\.env"
$examplePath = Join-Path $PSScriptRoot "..\backend\.env.example"
if (-not (Test-Path $envPath)) {
  Copy-Item -LiteralPath $examplePath -Destination $envPath
}

$content = Get-Content -Raw -Encoding UTF8 $envPath
$updates = @{
  MYSQL_HOST = $HostName
  MYSQL_PORT = [string]$Port
  MYSQL_USER = $User
  MYSQL_PASSWORD = $plainPassword
  MYSQL_DATABASE = $Database
  MYSQL_CHARSET = $Charset
}

foreach ($key in $updates.Keys) {
  $escaped = [regex]::Escape($key)
  $line = "$key=$($updates[$key])"
  if ($content -match "(?m)^$escaped=") {
    $content = [regex]::Replace($content, "(?m)^$escaped=.*$", $line)
  } else {
    $content = $content.TrimEnd() + "`r`n$line`r`n"
  }
}

Set-Content -LiteralPath $envPath -Value $content -Encoding UTF8
Write-Host "Created database '$Database' and updated backend\.env."
