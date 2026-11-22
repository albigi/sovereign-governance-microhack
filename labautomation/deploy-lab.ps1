#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('Validate', 'Deploy', 'Remove')]
    [string] $Action = 'Validate',
    [guid] $SubscriptionId,
    [guid] $RunId,
    [string] $Location,
    [switch] $SpendApproved,
    # Opt-in for a subscription that already pays for these Defender plans. Names the exact plans; never changes them.
    [ValidateSet('StorageAccounts', 'KeyVaults', 'CloudPosture', IgnoreCase = $false)]
    [string[]] $AcceptPaidDefenderPlans,
    [string] $ApprovalReference,
    [datetime] $ApprovalExpires,
    [string] $ApprovalCurrency,
    [decimal] $ApprovalCeiling
)

$ErrorActionPreference = 'Stop'

function Invoke-AzCli ([string[]] $CliArgs) {
    $result = & az @CliArgs --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        throw "az $($CliArgs[0..1] -join ' ') failed (exit $LASTEXITCODE); see CLI error above."
    }
    return $result
}

$template = Join-Path $PSScriptRoot 'main.bicep'
if ($Action -ne 'Remove') {
    if (-not $Location) {
        $Location = (Get-Content -Raw (Join-Path $PSScriptRoot 'lab-defaults.json') | ConvertFrom-Json).location
    }
    if ($Location -cnotmatch '^[a-z][a-z0-9]+$') {
        throw 'Use an Azure region name such as germanywestcentral.'
    }
}
if ($Action -eq 'Validate') {
    Invoke-AzCli @('bicep', 'build', '--file', $template, '--stdout') | Out-Null
    Write-Output "Bicep compiled locally; planned region: $Location. No subscription contacted."
    return
}
if (-not $SubscriptionId -or $SubscriptionId -eq [guid]::Empty -or -not $RunId -or $RunId -eq [guid]::Empty) {
    throw 'Deploy and Remove require explicit -SubscriptionId and -RunId.'
}
if ($Action -eq 'Deploy' -and -not $SpendApproved) {
    throw 'Deploy requires a dated spend approval covering this sandbox, a ceiling and -SpendApproved.'
}
$accepted = @($AcceptPaidDefenderPlans | Select-Object -Unique)
if ($Action -eq 'Deploy' -and $accepted.Count) {
    if ([string]::IsNullOrWhiteSpace($ApprovalReference) -or -not $PSBoundParameters.ContainsKey('ApprovalExpires') -or
        -not $ApprovalCurrency -or $ApprovalCeiling -le 0) {
        throw 'Accepting paid Defender plans requires -ApprovalReference, -ApprovalExpires, -ApprovalCurrency and a positive -ApprovalCeiling from the dated approval.'
    }
    if ($ApprovalCurrency -cnotmatch '^[A-Z]{3}$') {
        throw 'Use the three-letter uppercase currency code of the approval, for example EUR.'
    }
    if ($ApprovalExpires.ToUniversalTime() -le [datetime]::UtcNow) {
        throw 'The approval has expired. Obtain a current one; no change made.'
    }
}

$sub = $SubscriptionId.ToString()
$active = Invoke-AzCli @('account', 'show', '--query', 'id', '--output', 'tsv')
if ($active -ne $sub) {
    throw 'The active Azure CLI subscription is not the requested sandbox. Check the target; no change made.'
}
$deployment = 'mh-' + $RunId.ToString('N')
$group = "rg-$deployment"
$scopeArgs = @('--subscription', $sub)

function Test-LabGroup {
    $exists = Invoke-AzCli (@('group', 'exists', '--name', $group, '--output', 'tsv') + $scopeArgs)
    if ($exists -eq 'true') { return $true }
    if ($exists -eq 'false') { return $false }
    throw 'Unexpected resource group lookup result; no further action.'
}

if ($Action -eq 'Deploy') {
    if (Test-LabGroup) { throw 'Group already exists. Never reuse or adopt an existing group; choose a fresh run ID.' }
    $inherited = @()
    foreach ($plan in 'StorageAccounts', 'KeyVaults', 'CloudPosture') {
        $reported = @(Invoke-AzCli (@('security', 'pricing', 'show', '--name', $plan, '--query', 'pricingTier',
            '--output', 'tsv') + $scopeArgs))
        $tier = if ($reported.Count -eq 1) { [string] $reported[0] } else { '' }
        if ($tier -ceq 'Free') { continue }
        if ($tier -ceq 'Standard' -and $accepted -ccontains $plan) { $inherited += $plan; continue }
        if ($tier -cne 'Standard') {
            throw "Cannot read a recognised tier for Defender plan '$plan'; setup stops with or without an opt-in. No change made."
        }
        throw "Cannot confirm the Free tier for Defender plan '$plan'. Use a suitable sandbox, or accept this exact plan under the lab guide's opt-in; do not disable protection."
    }
    if ($inherited.Count) {
        Write-Warning ("Inherited paid Defender plans: $($inherited -join ', '). Plan settings are not changed. Plan charges for the lab's storage accounts and vault are added, and existing resources keep billing. " +
            "Approval: $ApprovalReference, expires $($ApprovalExpires.ToString('s')), recorded ceiling $ApprovalCeiling $ApprovalCurrency (not enforced).")
    }
    Invoke-AzCli (@('deployment', 'sub', 'create', '--name', $deployment, '--location', $Location,
        '--template-file', $template, '--output', 'none') + $scopeArgs)
    Write-Output $group
    return
}

if ($Action -eq 'Remove') {
    if (-not (Test-LabGroup)) {
        Write-Output "$group is absent. Check challenge-specific subscription objects separately."
        return
    }
    $tags = Invoke-AzCli (@('group', 'show', '--name', $group, '--query', 'tags', '--output', 'json') + $scopeArgs) |
        ConvertFrom-Json
    if ($tags.lab -cne 'sovereign-governance-microhack' -or $tags.run -cne $deployment) {
        throw 'Ownership tags do not match this lab run. Refusing deletion.'
    }
    Invoke-AzCli (@('group', 'delete', '--name', $group, '--yes') + $scopeArgs)
    if (Test-LabGroup) { throw 'The group still exists. Do not mark teardown complete.' }
    Write-Output "Verified absent: $group. Check challenge-specific subscription objects separately."
}
