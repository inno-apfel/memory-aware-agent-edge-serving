param(
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$StopFile,
    [double]$IntervalSeconds = 5
)

if ($IntervalSeconds -le 0) { throw 'IntervalSeconds must be positive' }
if (Test-Path -LiteralPath $Output) { throw 'Refusing to overwrite existing telemetry' }

while (-not (Test-Path -LiteralPath $StopFile)) {
    try {
        $metric = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory -ErrorAction Stop
        $sample = [ordered]@{
            wall_time = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
            available_mib = $metric.AvailableMBytes
            pages_input_s = $metric.PagesInputPersec
            pages_output_s = $metric.PagesOutputPersec
            page_reads_s = $metric.PageReadsPersec
            page_writes_s = $metric.PageWritesPersec
            committed_pct = $metric.PercentCommittedBytesInUse
        }
    } catch {
        $sample = [ordered]@{
            wall_time = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
            error = $_.Exception.Message
        }
    }
    $sample | ConvertTo-Json -Compress | Add-Content -LiteralPath $Output -Encoding UTF8
    Start-Sleep -Milliseconds ([int]($IntervalSeconds * 1000))
}
