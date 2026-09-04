[CmdletBinding()]
param(
    [switch]$Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$WorkspacePrefix = $Workspace.TrimEnd('\') + '\'
$ArchiveRoot = Join-Path $Workspace 'archive_legacy'
$StagingRoot = Join-Path $Workspace 'staging\cn_legacy_probes'
$MetadataRoot = Join-Path $Workspace 'metadata'
$ArchiveManifest = Join-Path $ArchiveRoot 'archive_manifest.csv'
$CleanupReport = Join-Path $MetadataRoot 'workspace_cleanup_report.json'
$ArchivedAt = [DateTimeOffset]::Now.ToString('o')

function Resolve-SafeWorkspacePath {
    param([Parameter(Mandatory)][string]$Path)
    $Full = [System.IO.Path]::GetFullPath($Path)
    if (-not $Full.StartsWith($WorkspacePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside workspace: $Full"
    }
    if ($Full.Equals($Workspace, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing to target the workspace root.'
    }
    return $Full
}

function Get-WorkspaceRelativePath {
    param([Parameter(Mandatory)][string]$Path)
    return [System.IO.Path]::GetRelativePath(
        $Workspace,
        [System.IO.Path]::GetFullPath($Path)
    ).Replace('\', '/')
}

function Get-PathFiles {
    param([Parameter(Mandatory)][string]$Path)
    $Item = Get-Item -LiteralPath $Path -Force
    if ($Item.PSIsContainer) {
        return @(Get-ChildItem -LiteralPath $Item.FullName -Recurse -File -Force)
    }
    return @($Item)
}

$ArchiveRows = [System.Collections.Generic.List[object]]::new()
$ArchiveActions = [System.Collections.Generic.List[object]]::new()
$StagingRows = [System.Collections.Generic.List[object]]::new()
$ProbeCleanupRows = [System.Collections.Generic.List[object]]::new()
$DeletedCachePaths = [System.Collections.Generic.List[string]]::new()
$RemovedEmptyDirectories = [System.Collections.Generic.List[string]]::new()

function Register-ArchiveMove {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][string]$Replacement
    )
    $Source = Resolve-SafeWorkspacePath $Source
    $Destination = Resolve-SafeWorkspacePath $Destination
    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }
    if (Test-Path -LiteralPath $Destination) {
        throw "Archive destination already exists: $Destination"
    }
    $SourceItem = Get-Item -LiteralPath $Source -Force
    $Files = @(Get-PathFiles $Source)
    $TotalBytes = ($Files | Measure-Object Length -Sum).Sum
    $MoveRows = [System.Collections.Generic.List[object]]::new()
    foreach ($File in $Files) {
        $ArchivedFile = if ($SourceItem.PSIsContainer) {
            Join-Path $Destination ([System.IO.Path]::GetRelativePath($Source, $File.FullName))
        } else {
            $Destination
        }
        $Row = [pscustomobject]@{
            original_path = Get-WorkspaceRelativePath $File.FullName
            archive_path = Get-WorkspaceRelativePath $ArchivedFile
            bytes = [int64]$File.Length
            sha256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            reason = $Reason
            replacement_or_reference = $Replacement
            archived_at = $ArchivedAt
        }
        $MoveRows.Add($Row)
        $ArchiveRows.Add($Row)
    }
    $ArchiveActions.Add([pscustomobject]@{
        source = Get-WorkspaceRelativePath $Source
        destination = Get-WorkspaceRelativePath $Destination
        files = $Files.Count
        bytes = [int64]$TotalBytes
        reason = $Reason
    })
    if ($Execute) {
        $Parent = Split-Path -Parent $Destination
        New-Item -ItemType Directory -Path $Parent -Force | Out-Null
        Move-Item -LiteralPath $Source -Destination $Destination
        if (Test-Path -LiteralPath $ArchiveManifest) {
            $MoveRows | Export-Csv -LiteralPath $ArchiveManifest -NoTypeInformation -Encoding utf8 -Append
        } else {
            $MoveRows | Export-Csv -LiteralPath $ArchiveManifest -NoTypeInformation -Encoding utf8
        }
    }
}

function Assert-QueueStopped {
    $StatePath = Join-Path $MetadataRoot 'data_crawl_queue_state.json'
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return
    }
    $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ($State.status -notin @('stopped_by_signal', 'not_started', 'complete', 'completed', 'failed', 'stopped_after_failures')) {
        throw "Queue is not safely stopped (status=$($State.status))."
    }
    $CandidatePids = [System.Collections.Generic.HashSet[int]]::new()
    if ($null -ne $State.current_stage) {
        foreach ($Value in @($State.current_stage.parent_runner_pid, $State.current_stage.child_pid)) {
            if ($null -ne $Value -and [int]$Value -gt 0) {
                [void]$CandidatePids.Add([int]$Value)
            }
        }
    }
    $PidPath = Join-Path $MetadataRoot 'data_crawl_queue_pid.json'
    if (Test-Path -LiteralPath $PidPath) {
        $PidRecord = Get-Content -LiteralPath $PidPath -Raw | ConvertFrom-Json
        if ($null -ne $PidRecord.pid -and [int]$PidRecord.pid -gt 0) {
            [void]$CandidatePids.Add([int]$PidRecord.pid)
        }
    }
    foreach ($ProcessId in $CandidatePids) {
        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            throw "Recorded queue process is still alive: PID $ProcessId"
        }
    }
}

Assert-QueueStopped
New-Item -ItemType Directory -Path $ArchiveRoot -Force | Out-Null
New-Item -ItemType Directory -Path $MetadataRoot -Force | Out-Null

$TagItems = @(
    'CharacterTagAnalyze-clusters.py',
    'CharacterTagAnalyze-freq.py',
    'CharacterTagAnalyze-LDA.py',
    'CharacterTagAnalyze-textrank.py',
    'CharacterTagAnalyze-tfidf.py',
    'TagGetMoeWiki.py',
    'CharacterTagAnalyze-results-freq',
    'CharacterTagAnalyze-results-LDA',
    'CharacterTagAnalyze-results-textrank',
    'CharacterTagAnalyze-results-tfidf',
    'keyword_clusters',
    'cache',
    'cache_data',
    'stopwords.txt',
    '方正书宋简体.ttf'
)
foreach ($Name in $TagItems) {
    Register-ArchiveMove `
        -Source (Join-Path $Workspace $Name) `
        -Destination (Join-Path $ArchiveRoot "tag_analysis_v1\$Name") `
        -Reason 'Legacy tag/text-analysis bundle removed from the maintained numeric vote-analysis path.' `
        -Replacement 'Official numeric pipeline under scripts_pipeline/; retained user mappings Character_tag.xlsx and 萌点提取结果.xlsx'
}

$MonolithicItems = @('SummarizeAllData.py', 'touhou_vote.json', 'data_statistic')
foreach ($Name in $MonolithicItems) {
    Register-ArchiveMove `
        -Source (Join-Path $Workspace $Name) `
        -Destination (Join-Path $ArchiveRoot "monolithic_vote_json_v1\$Name") `
        -Reason 'Deprecated monolithic data model; JP gender fields are known empty and supplemental official data is incomplete.' `
        -Replacement 'data_processed/ official tables and analysis_results/demographic_audit*'
}

$PlotItems = @(
    'TouhouVote.py',
    'TouhouVoteMusic.py',
    'top7.py',
    'top15.py',
    'top30.py',
    'GroupAnalyze_jp.py',
    'CharacterAnalyze_cn.py',
    'difference.py',
    'top7_percentage.png',
    'group_percentages.png'
)
foreach ($Name in $PlotItems) {
    Register-ArchiveMove `
        -Source (Join-Path $Workspace $Name) `
        -Destination (Join-Path $ArchiveRoot "vote_plotting_v1\$Name") `
        -Reason 'Legacy plotting/normalization implementation superseded by the maintained reproducible pipeline.' `
        -Replacement 'scripts_pipeline/ and analysis_results/; user-corrected workbooks remain at workspace root'
}

Register-ArchiveMove `
    -Source (Join-Path $Workspace 'readme.md') `
    -Destination (Join-Path $ArchiveRoot 'root_readme_2025.md') `
    -Reason 'Historical root README describes programs now retained as legacy bundles.' `
    -Replacement 'README.md and scripts_pipeline/README.md'

$RootProbeFiles = @(Get-ChildItem -LiteralPath $Workspace -File -Force -Filter '.tmp_cn_*')
if ($RootProbeFiles.Count -gt 0) {
    $FormalHashIndex = @{}
    foreach ($FormalRootName in @('data_raw\cn_official', 'data_raw\cn_official_legacy')) {
        $FormalRoot = Join-Path $Workspace $FormalRootName
        if (-not (Test-Path -LiteralPath $FormalRoot)) { continue }
        foreach ($FormalFile in Get-ChildItem -LiteralPath $FormalRoot -Recurse -File -Force) {
            $FormalHash = (Get-FileHash -LiteralPath $FormalFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            if (-not $FormalHashIndex.ContainsKey($FormalHash)) {
                $FormalHashIndex[$FormalHash] = Get-WorkspaceRelativePath $FormalFile.FullName
            }
        }
    }
    $DiagnosticProbeNames = @(
        '.tmp_cn_probe_headers.txt',
        '.tmp_cn_probe_v2_body.html',
        '.tmp_cn_probe_v2_headers.txt',
        '.tmp_cn_probe_v2_i1_body.html',
        '.tmp_cn_probe_v2_i1_headers.txt'
    )
    $InvalidProbeNames = @(
        '.tmp_cn_v5_chara_crossvote.html',
        '.tmp_cn_v5_cross_guess1.html',
        '.tmp_cn_v5_cross_guess2.html',
        '.tmp_cn_v5_cross_guess3.html',
        '.tmp_cn_v5_cross_guess4.html',
        '.tmp_cn_v5_crossvote_js.html',
        '.tmp_cn_v5_crossvote.js',
        '.tmp_cn_v5_music_crossvote.html',
        '.tmp_cn_v6_chara_crossvote.html',
        '.tmp_cn_v6_crossvote_js.html',
        '.tmp_cn_v6_music_crossvote.html',
        '.tmp_cn_v7_chara_crossvote.html',
        '.tmp_cn_v7_crossvote_js.html',
        '.tmp_cn_v7_music_crossvote.html'
    )
    foreach ($File in $RootProbeFiles) {
        $Digest = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $Action = ''
        $DestinationRelative = ''
        $Reason = ''
        if ($FormalHashIndex.ContainsKey($Digest)) {
            $Action = 'deleted_exact_formal_duplicate'
            $DestinationRelative = [string]$FormalHashIndex[$Digest]
            $Reason = 'Byte-identical SHA-256-verified formal raw file already exists.'
            if ($Execute) {
                Remove-Item -LiteralPath (Resolve-SafeWorkspacePath $File.FullName) -Force
            }
        } elseif ($DiagnosticProbeNames -contains $File.Name) {
            $Action = 'archived_network_diagnostic'
            $DiagnosticDestination = Join-Path $ArchiveRoot "network_diagnostics\2026-08-15-cn-probes\$($File.Name)"
            $DestinationRelative = Get-WorkspaceRelativePath $DiagnosticDestination
            $Reason = 'Retained HTTP diagnostic without analysis value in the main workspace.'
            Register-ArchiveMove `
                -Source $File.FullName `
                -Destination $DiagnosticDestination `
                -Reason $Reason `
                -Replacement 'Formal official responses under data_raw/cn_official_legacy/'
        } elseif ($InvalidProbeNames -contains $File.Name) {
            $Action = 'deleted_invalid_probe_response'
            $Reason = 'Confirmed load-failure or 404 probe with no unique official data.'
            if ($Execute) {
                Remove-Item -LiteralPath (Resolve-SafeWorkspacePath $File.FullName) -Force
            }
        } else {
            $Action = 'staged_unique_probe'
            $Reason = 'Unique probe retained for CN legacy import or evidence review.'
            $Destination = Resolve-SafeWorkspacePath (Join-Path $StagingRoot $File.Name)
            $DestinationRelative = Get-WorkspaceRelativePath $Destination
            if (Test-Path -LiteralPath $Destination) {
                throw "Probe staging destination already exists: $Destination"
            }
            $StagingRows.Add([pscustomobject]@{
                original_path = Get-WorkspaceRelativePath $File.FullName
                staged_path = $DestinationRelative
                bytes = [int64]$File.Length
                sha256 = $Digest
                moved_at = $ArchivedAt
                status = 'retained_for_cn_legacy_import_and_coverage_recovery'
            })
            if ($Execute) {
                New-Item -ItemType Directory -Path $StagingRoot -Force | Out-Null
                Move-Item -LiteralPath $File.FullName -Destination $Destination
            }
        }
        $ProbeCleanupRows.Add([pscustomobject]@{
            original_path = Get-WorkspaceRelativePath $File.FullName
            bytes = [int64]$File.Length
            sha256 = $Digest
            action = $Action
            destination_or_reference = $DestinationRelative
            reason = $Reason
            processed_at = $ArchivedAt
        })
    }
    if ($Execute) {
        if ($StagingRows.Count -gt 0) {
            $StagingRows | Export-Csv -LiteralPath (Join-Path $StagingRoot 'inventory.csv') -NoTypeInformation -Encoding utf8
        }
        $ProbeCleanupRows | Export-Csv -LiteralPath (Join-Path $MetadataRoot 'cn_probe_cleanup.csv') -NoTypeInformation -Encoding utf8
    }
}

$VenvPath = Resolve-SafeWorkspacePath (Join-Path $Workspace '.venv')
$VenvSummary = $null
if (Test-Path -LiteralPath $VenvPath) {
    $VenvFiles = @(Get-ChildItem -LiteralPath $VenvPath -Recurse -File -Force)
    $VenvBytes = ($VenvFiles | Measure-Object Length -Sum).Sum
    $EnvironmentArchive = Resolve-SafeWorkspacePath (Join-Path $ArchiveRoot 'environment_py311_broken')
    $PackageRows = [System.Collections.Generic.List[object]]::new()
    $SitePackages = Join-Path $VenvPath 'Lib\site-packages'
    if (Test-Path -LiteralPath $SitePackages) {
        foreach ($DistInfo in Get-ChildItem -LiteralPath $SitePackages -Directory -Filter '*.dist-info') {
            $Metadata = Join-Path $DistInfo.FullName 'METADATA'
            if (-not (Test-Path -LiteralPath $Metadata)) { continue }
            $NameLine = (Select-String -LiteralPath $Metadata -Pattern '^Name: ' | Select-Object -First 1).Line
            $VersionLine = (Select-String -LiteralPath $Metadata -Pattern '^Version: ' | Select-Object -First 1).Line
            $PackageRows.Add([pscustomobject]@{
                name = ($NameLine -replace '^Name: ', '')
                version = ($VersionLine -replace '^Version: ', '')
                dist_info = $DistInfo.Name
            })
        }
    }
    $VenvSummary = [pscustomobject]@{
        path = '.venv'
        files = $VenvFiles.Count
        bytes = [int64]$VenvBytes
        action = if ($Execute) { 'deleted_after_dependency_inventory' } else { 'would_delete_after_dependency_inventory' }
        reason = 'Broken Python 3.11 environment points to a missing interpreter and an old workspace location.'
        dependency_inventory = 'archive_legacy/environment_py311_broken/packages.csv'
    }
    if ($Execute) {
        New-Item -ItemType Directory -Path $EnvironmentArchive -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $VenvPath 'pyvenv.cfg') -Destination (Join-Path $EnvironmentArchive 'pyvenv.cfg')
        $PackageRows | Sort-Object name | Export-Csv -LiteralPath (Join-Path $EnvironmentArchive 'packages.csv') -NoTypeInformation -Encoding utf8
        Remove-Item -LiteralPath $VenvPath -Recurse -Force
    }
}

$CacheBytes = [int64]0
$CacheFiles = 0
$BytecodeDirectories = @(
    Get-ChildItem -LiteralPath $Workspace -Recurse -Directory -Force -Filter '__pycache__' -ErrorAction SilentlyContinue |
        Where-Object {
            -not $_.FullName.StartsWith($ArchiveRoot + '\', [StringComparison]::OrdinalIgnoreCase) -and
            -not $_.FullName.StartsWith($VenvPath + '\', [StringComparison]::OrdinalIgnoreCase)
        }
)
foreach ($Directory in $BytecodeDirectories) {
    $SafeDirectory = Resolve-SafeWorkspacePath $Directory.FullName
    $Files = @(Get-ChildItem -LiteralPath $SafeDirectory -Recurse -File -Force -ErrorAction SilentlyContinue)
    $CacheFiles += $Files.Count
    $CacheBytes += [int64](($Files | Measure-Object Length -Sum).Sum)
    $DeletedCachePaths.Add((Get-WorkspaceRelativePath $SafeDirectory))
    if ($Execute) {
        Remove-Item -LiteralPath $SafeDirectory -Recurse -Force
    }
}
$LooseBytecode = @(
    Get-ChildItem -LiteralPath $Workspace -Recurse -File -Force -Filter '*.pyc' -ErrorAction SilentlyContinue |
        Where-Object {
            -not $_.FullName.StartsWith($ArchiveRoot + '\', [StringComparison]::OrdinalIgnoreCase) -and
            -not $_.FullName.StartsWith($VenvPath + '\', [StringComparison]::OrdinalIgnoreCase) -and
            $_.FullName -notmatch '[\\/]__pycache__[\\/]'
        }
)
foreach ($File in $LooseBytecode) {
    $SafeFile = Resolve-SafeWorkspacePath $File.FullName
    $CacheFiles += 1
    $CacheBytes += [int64]$File.Length
    $DeletedCachePaths.Add((Get-WorkspaceRelativePath $SafeFile))
    if ($Execute) {
        Remove-Item -LiteralPath $SafeFile -Force
    }
}

foreach ($RelativeLog in @(
    'metadata\logs\data_crawl_queue\runner.stdout.log',
    'metadata\logs\data_crawl_queue\runner.stderr.log'
)) {
    $LogPath = Resolve-SafeWorkspacePath (Join-Path $Workspace $RelativeLog)
    if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -eq 0) {
        $DeletedCachePaths.Add((Get-WorkspaceRelativePath $LogPath))
        if ($Execute) {
            Remove-Item -LiteralPath $LogPath -Force
        }
    }
}

foreach ($RelativeDirectory in @('data_raw\cn', 'data_raw\jp')) {
    $DirectoryPath = Resolve-SafeWorkspacePath (Join-Path $Workspace $RelativeDirectory)
    if (
        (Test-Path -LiteralPath $DirectoryPath) -and
        @(Get-ChildItem -LiteralPath $DirectoryPath -Force).Count -eq 0
    ) {
        $RemovedEmptyDirectories.Add((Get-WorkspaceRelativePath $DirectoryPath))
        if ($Execute) {
            Remove-Item -LiteralPath $DirectoryPath -Force
        }
    }
}

$Report = [ordered]@{
    schema_version = 1
    generated_at = $ArchivedAt
    mode = if ($Execute) { 'executed' } else { 'dry_run' }
    queue_verified_stopped = $true
    archive_actions = @($ArchiveActions)
    archive_files = $ArchiveRows.Count
    archive_bytes = [int64](($ArchiveRows | Measure-Object bytes -Sum).Sum)
    staged_cn_probe_files = $StagingRows.Count
    staged_cn_probe_bytes = [int64](($StagingRows | Measure-Object bytes -Sum).Sum)
    deleted_duplicate_probe_files = @($ProbeCleanupRows | Where-Object action -eq 'deleted_exact_formal_duplicate').Count
    deleted_invalid_probe_files = @($ProbeCleanupRows | Where-Object action -eq 'deleted_invalid_probe_response').Count
    archived_diagnostic_probe_files = @($ProbeCleanupRows | Where-Object action -eq 'archived_network_diagnostic').Count
    probe_cleanup_index = 'metadata/cn_probe_cleanup.csv'
    deleted_regenerable_cache_files = $CacheFiles
    deleted_regenerable_cache_bytes = $CacheBytes
    deleted_cache_paths = @($DeletedCachePaths)
    removed_empty_directories = @($RemovedEmptyDirectories)
    removed_broken_environment = $VenvSummary
    protected_paths = @(
        'data_raw/',
        'data_processed/',
        'metadata/*manifest*',
        'metadata/*coverage*',
        'metadata/*validation*',
        'Character-MusicAnalyze.py',
        'CharacterAnalyze_jp.py',
        '人气拉表统计.opju',
        '*.xlsx'
    )
}

if ($Execute) {
    $Report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $CleanupReport -Encoding utf8
}
$Report | ConvertTo-Json -Depth 8
