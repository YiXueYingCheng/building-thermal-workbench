param([Parameter(Mandatory=$true)][string]$Database,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$TaskDb=[IO.Path]::GetFullPath($Database)
$TaskOut=[IO.Path]::GetFullPath($Output)
New-Item -ItemType Directory -Path $TaskOut -Force | Out-Null
$TaskConnection=[Data.Odbc.OdbcConnection]::new()
$TaskBuilder=[Data.Odbc.OdbcConnectionStringBuilder]::new()
$TaskBuilder['Driver']='Microsoft Access Driver (*.mdb, *.accdb)'
$TaskBuilder['Dbq']=$TaskDb
$TaskBuilder['ReadOnly']='1'
$TaskConnection.ConnectionString=$TaskBuilder.ConnectionString
$TaskCounts=[ordered]@{}
$TaskErrors=@()
$TaskConnection.Open()
try {
    $TaskNames=@($TaskConnection.GetSchema('Tables').Rows | Where-Object {$_.TABLE_TYPE -eq 'TABLE' -and !$_.TABLE_NAME.StartsWith('MSys')} | ForEach-Object TABLE_NAME | Sort-Object)
    foreach($TaskName in $TaskNames) {
        if($TaskName -in @('LOG','SURFACE_SUN_SHADE_MAP','GROUND_CONSTRUCTION','GROUND_Q') -or $TaskName -like 'RESULT_*'){continue}
        if($TaskName -notmatch '^[A-Za-z0-9_]+$'){throw 'Unsupported table name'}
        $TaskCmd=$TaskConnection.CreateCommand();$TaskReader=$null
        try {
            $TaskCmd.CommandText='SELECT * FROM ['+$TaskName+']';$TaskCmd.CommandTimeout=60
            $TaskReader=$TaskCmd.ExecuteReader();$TaskRows=[Collections.Generic.List[object]]::new()
            while($TaskReader.Read()) {
                $TaskRow=[ordered]@{}
                for($TaskCol=0;$TaskCol -lt $TaskReader.FieldCount;$TaskCol++) {
                    $TaskValue=$TaskReader.GetValue($TaskCol)
                    if($TaskValue -is [DBNull]){$TaskValue=$null}
                    elseif($TaskValue -is [byte[]]){$TaskValue=@{binary_bytes=$TaskValue.Length;base64=[Convert]::ToBase64String($TaskValue)}}
                    elseif($TaskValue -is [DateTime]){$TaskValue=$TaskValue.ToString('o')}
                    $TaskRow[$TaskReader.GetName($TaskCol)]=$TaskValue
                }
                $TaskRows.Add($TaskRow)
            }
            $TaskCounts[$TaskName]=$TaskRows.Count
            ConvertTo-Json -InputObject $TaskRows.ToArray() -Depth 12 | Set-Content -LiteralPath (Join-Path $TaskOut ($TaskName+'.json')) -Encoding utf8
        } catch {$TaskErrors+=@{table=$TaskName;error=$_.Exception.Message}}
        finally {if($TaskReader){$TaskReader.Close()};$TaskCmd.Dispose()}
    }
} finally {$TaskConnection.Close();$TaskConnection.Dispose()}
ConvertTo-Json -InputObject @{table_counts=$TaskCounts;errors=$TaskErrors;passed=($TaskErrors.Count -eq 0)} -Depth 12 | Set-Content -LiteralPath (Join-Path (Split-Path $TaskOut) 'extraction.json') -Encoding utf8
if($TaskErrors.Count){throw 'Some tables could not be read; see extraction.json'}
