#You need to have this running first to scrape
#python -m uvicorn worker_service.scrape:app --host 127.0.0.1 --port 8000 --reload
#Then Run: .\worker_service\scrape.ps1 -Url "https://example.com"


param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Url,

    [string]$ApiUrl = "http://127.0.0.1:8000/scrape",

    [int]$TimeoutSeconds = 60,

    [switch]$ForceRefresh
)

try {
    $uri = [System.Uri]$Url
} catch {
    Write-Error "Invalid URL: $Url"
    exit 1
}

$domain = "{0}://{1}" -f $uri.Scheme, $uri.Host
$payload = @{
    domain  = $domain
    pages   = @(@{ url = $Url })
    mode    = "fetch_if_changed"
    options = @{
        force_refresh   = [bool]$ForceRefresh
        client_has_pack = $false
        timeout_s       = $TimeoutSeconds
        rate_limit_ms   = 0
    }
}

try {
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri $ApiUrl `
        -ContentType "application/json" `
        -Body ($payload | ConvertTo-Json -Depth 8)
} catch {
    Write-Error "Failed to call scrape API at $ApiUrl. Is uvicorn running?"
    Write-Error $_
    exit 1
}

if (-not $response.changed_pages -or $response.changed_pages.Count -eq 0) {
    if ($response.errors -and $response.errors.Count -gt 0) {
        Write-Host "Scrape completed with errors:"
        $response.errors | ForEach-Object { Write-Host ("- {0}: {1}" -f $_.url, $_.error) }
    } else {
        Write-Host "No scraped page content was returned."
    }
    exit 1
}

$page = $response.changed_pages[0]

$safeHost = ($uri.Host -replace "[^a-zA-Z0-9.-]", "_")
$pathPart = $uri.AbsolutePath.Trim("/")
if ([string]::IsNullOrWhiteSpace($pathPart)) {
    $pathPart = "root"
}
$safePath = ($pathPart -replace "[^a-zA-Z0-9._-]", "_")
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outFile = Join-Path $PSScriptRoot ("scraped_{0}_{1}_{2}.txt" -f $safeHost, $safePath, $stamp)

$text = @(
    "URL: $($page.url)"
    "TITLE: $($page.title)"
    "CHECKED_AT: $($response.checked_at)"
    "CACHE_HIT: $($response.cache_hit)"
    ""
    $page.normalized_text
) -join [Environment]::NewLine

Set-Content -Path $outFile -Value $text -Encoding UTF8
Write-Host "Saved scraped text to: $outFile"
