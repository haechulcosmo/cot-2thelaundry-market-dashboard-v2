param(
  [string]$ProjectDir = ".",
  [string]$ArchivePath = "site-package.tgz"
)

$ErrorActionPreference = "Stop"

$project = (Resolve-Path $ProjectDir).Path
$stage = Join-Path $project ".site_stage"
$dist = Join-Path $project "dist"
$hosting = Join-Path $project ".openai\\hosting.json"

if (-not (Test-Path (Join-Path $dist "server\\index.js"))) {
  throw "Missing dist/server/index.js"
}

if (-not (Test-Path $hosting)) {
  throw "Missing .openai/hosting.json"
}

Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path (Join-Path $stage "dist\\.openai") -Force | Out-Null
Copy-Item -Path (Join-Path $dist "*") -Destination (Join-Path $stage "dist") -Recurse -Force
Copy-Item -LiteralPath $hosting -Destination (Join-Path $stage "dist\\.openai\\hosting.json") -Force

$archiveFull = Join-Path $project $ArchivePath
if (Test-Path $archiveFull) {
  Remove-Item -LiteralPath $archiveFull -Force
}

tar.exe -czf $archiveFull -C $stage dist
tar.exe -tzf $archiveFull
