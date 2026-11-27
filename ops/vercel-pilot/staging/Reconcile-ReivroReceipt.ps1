#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ReceiptDirectory = 'C:\Users\LENOVO\REIVRO-Backups\reivro-staging-20261127-183321-65f72840'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$receiptPath = Join-Path $ReceiptDirectory 'receipt.json'
$archivePath = Join-Path $ReceiptDirectory 'reivro-staging.dump'
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $archivePath -PathType Leaf)) { throw 'Receipt or archive is missing.' }
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$actualBytes = (Get-Item -LiteralPath $archivePath).Length
if ($receipt.status -cne 'SELECTIVE_RESTORE_PASS' -or
    [string]$receipt.source_server_version_num -cnotmatch '^17\d{4}$' -or
    [string]$receipt.restore_server_version_num -cnotmatch '^19\d{4}$' -or
    [long]$receipt.archive_bytes -ne $actualBytes -or
    [int]$receipt.toc_entries -le 0 -or
    [string]$receipt.archive_sha256 -cne $actualHash) { throw 'Receipt reconciliation failed.' }
[pscustomobject]@{
    status = 'RECEIPT_RECONCILED'
    source_major = 17
    restore_major = 19
    archive_sha256 = $actualHash
    archive_bytes = $actualBytes
    toc_entries = [int]$receipt.toc_entries
    captured_utc = [string]$receipt.captured_utc
} | ConvertTo-Json
