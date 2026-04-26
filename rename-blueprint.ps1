# === KONFIGURATION ===
$GitHubUser  = "dibi73"
$RepoName    = "ha-bookstack-sync"
$NewDomain   = "bookstack_sync"
$NewName     = "BookStack Sync"
$DryRun      = $false   # erst $true zum Pruefen, dann auf $false setzen
# =====================

# Alte Werte aus dem ludeeus-Blueprint
$OldDomain    = "integration_blueprint"
$OldName      = "Integration Blueprint"
$OldRepoPath  = "ludeeus/integration_blueprint"
$NewRepoPath  = "$GitHubUser/$RepoName"
$OldOwner     = "@ludeeus"
$NewOwner     = "@$GitHubUser"

Write-Host ""
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "  Blueprint-Umbenennung" -ForegroundColor Cyan
Write-Host "===============================================" -ForegroundColor Cyan
Write-Host "Domain:   $OldDomain  ->  $NewDomain"
Write-Host "Name:     $OldName  ->  $NewName"
Write-Host "Repo:     $OldRepoPath  ->  $NewRepoPath"
Write-Host "Owner:    $OldOwner  ->  $NewOwner"
if ($DryRun) {
    Write-Host "MODUS:    DRY-RUN (nichts wird wirklich geaendert)" -ForegroundColor Yellow
} else {
    Write-Host "MODUS:    LIVE (Aenderungen werden geschrieben)" -ForegroundColor Red
}
Write-Host ""

# Sicherheits-Check
if (-not (Test-Path "custom_components\$OldDomain")) {
    Write-Host "FEHLER: Ordner 'custom_components\$OldDomain' nicht gefunden." -ForegroundColor Red
    Write-Host "Bitte das Skript im Wurzelverzeichnis des geklonten Blueprints ausfuehren." -ForegroundColor Red
    exit 1
}

$Extensions  = @("*.py", "*.json", "*.md", "*.yaml", "*.yml", "*.txt", "*.toml", "*.cfg")
$ExcludeDirs = @(".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache")

Write-Host "[Schritt 1] Suche Dateien mit zu ersetzenden Inhalten..." -ForegroundColor Green
$Files = Get-ChildItem -Path . -Recurse -File -Include $Extensions | Where-Object {
    $path = $_.FullName
    -not ($ExcludeDirs | Where-Object { $path -like "*\$_\*" })
}

$ReplacementCount = 0
foreach ($file in $Files) {
    $content = Get-Content -Path $file.FullName -Raw -Encoding UTF8
    if ($null -eq $content) { continue }

    $newContent = $content
    $newContent = $newContent -replace [regex]::Escape($OldRepoPath), $NewRepoPath
    $newContent = $newContent -replace [regex]::Escape($OldDomain),   $NewDomain
    $newContent = $newContent -replace [regex]::Escape($OldName),     $NewName
    $newContent = $newContent -replace [regex]::Escape($OldOwner),    $NewOwner

    if ($newContent -ne $content) {
        $relPath = Resolve-Path -Path $file.FullName -Relative
        Write-Host "  [aendern] $relPath" -ForegroundColor Gray
        $ReplacementCount++

        if (-not $DryRun) {
            $utf8NoBom = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($file.FullName, $newContent, $utf8NoBom)
        }
    }
}
Write-Host "Gefundene Dateien mit Aenderungen: $ReplacementCount"
Write-Host ""

Write-Host "[Schritt 2] Benenne Integrations-Ordner um..." -ForegroundColor Green
$OldDir = "custom_components\$OldDomain"
if (Test-Path $OldDir) {
    Write-Host "  $OldDir -> custom_components\$NewDomain" -ForegroundColor Gray
    if (-not $DryRun) {
        Rename-Item -Path $OldDir -NewName $NewDomain
    }
} else {
    Write-Host "  Ordner $OldDir nicht gefunden (vielleicht schon umbenannt?)" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "===============================================" -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "DRY-RUN abgeschlossen. Wenn alles gut aussieht:" -ForegroundColor Yellow
    Write-Host "Setze \$DryRun = \$false und fuehre das Skript erneut aus." -ForegroundColor Yellow
} else {
    Write-Host "Umbenennung abgeschlossen!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Naechste Schritte:" -ForegroundColor Cyan
    Write-Host "  1. Pruefen: git status"
    Write-Host "  2. Diff:    git diff"
    Write-Host "  3. Testen:  in VS Code 'Reopen in Container' und script\develop"
    Write-Host "  4. Commit:  git add . ; git commit -m 'Initial rename from blueprint'"
    Write-Host "  5. Push:    git push"
}
Write-Host "===============================================" -ForegroundColor Cyan