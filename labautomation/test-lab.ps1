#requires -Version 7.0
# CLI test double: no Azure sign-in, permissions or network access required.
$ErrorActionPreference = 'Stop'
$entry = Join-Path $PSScriptRoot 'deploy-lab.ps1'
$target = @{ SubscriptionId = [guid]::NewGuid(); RunId = [guid]::NewGuid() }
$name = 'mh-' + $target.RunId.ToString('N')
$state = @{
    Active = $target.SubscriptionId.ToString()
    Exists = $false
    Owned = $true
    FailLookup = $false
    FailPricing = $false
    Tier = @{ StorageAccounts = 'Free'; KeyVaults = 'Free'; CloudPosture = 'Free' }
    Deletes = 0
    Creates = 0
    PricingWrites = 0
    Calls = 0
}

function az {
    $global:LASTEXITCODE = 0
    $state.Calls++
    $verb = $args[0..1] -join ' '
    if ($verb -eq 'account show') { return $state.Active }
    if ($verb -eq 'bicep build') { return '{}' }
    if ($args -notcontains '--subscription' -or
        $args[$args.IndexOf('--subscription') + 1] -ne $target.SubscriptionId.ToString()) {
        throw "Unscoped CLI call: $verb"
    }
    if ($verb -eq 'security pricing') {
        if ($args[2] -ne 'show') { $state.PricingWrites++; throw "Defender setting write attempted: $verb $($args[2])" }
        if ($state.FailPricing) { $global:LASTEXITCODE = 1; return }
        return $state.Tier[$args[$args.IndexOf('--name') + 1]]
    }
    if ($verb -eq 'deployment sub') {
        if ($args[2] -ne 'create' -or $args[$args.IndexOf('--name') + 1] -cne $name) {
            throw 'Unexpected deployment target'
        }
        $state.Creates++
        $state.Exists = $true
        return
    }
    if ($args[$args.IndexOf('--name') + 1] -cne "rg-$name") { throw 'Unexpected group target' }
    switch ($verb) {
        'group exists' {
            if ($state.FailLookup) { $global:LASTEXITCODE = 1; return }
            return $state.Exists.ToString().ToLowerInvariant()
        }
        'group show' {
            if ($state.Owned) { return (@{lab = 'sovereign-governance-microhack'; run = $name} | ConvertTo-Json) }
            return '{}'
        }
        'group delete' { $state.Deletes++; $state.Exists = $false }
        default { throw "Unexpected CLI call: $verb" }
    }
}

function Expect-Error ([scriptblock] $Run, [string] $Message) {
    try { & $Run } catch {
        if ($_.Exception.Message -like $Message) { return }
        throw
    }
    throw "Expected error: $Message"
}

& $entry | Out-Null
if ($state.Creates -or $state.Deletes) { throw 'Default Validate must not create or delete anything' }
Expect-Error { & $entry -Action Deploy @target } '*spend approval*'
Expect-Error { & $entry -Action Remove } '*explicit*'
if ($state.Calls -ne 1) { throw 'Missing approval or target should stop before any CLI call' }
$state.Active = [guid]::NewGuid().ToString()
Expect-Error { & $entry -Action Deploy @target -SpendApproved } '*not the requested sandbox*'
$state.Active = $target.SubscriptionId.ToString()
$state.FailLookup = $true
Expect-Error { & $entry -Action Deploy @target -SpendApproved } '*group exists failed*'
$state.FailLookup = $false
foreach ($plan in @($state.Tier.Keys)) {
    $state.Tier[$plan] = 'Standard'
    Expect-Error { & $entry -Action Deploy @target -SpendApproved } "*Free tier*$plan*"
    $state.Tier[$plan] = 'Free'
}
$state.Tier.KeyVaults = ''
Expect-Error { & $entry -Action Deploy @target -SpendApproved } '*recognised tier*KeyVaults*'
$state.Tier.KeyVaults = 'Free'
$result = & $entry -Action Deploy @target -SpendApproved
if ($result -cne "rg-$name") { throw 'Deploy did not return the group name for subsequent challenges' }
if ($state.Creates -ne 1 -or $state.Deletes -or -not $state.Exists) {
    throw 'Deploy must create the group without deleting it'
}
$before = $state.Calls
& $entry -Action Validate @target -SpendApproved | Out-Null
if ($state.Calls -ne $before + 1 -or $state.Creates -ne 1 -or $state.Deletes -or -not $state.Exists) {
    throw 'Validate with an owned group and deployment arguments must only compile locally'
}
Expect-Error { & $entry -Action Deploy @target -SpendApproved } '*already exists*'
$state.Owned = $false
Expect-Error { & $entry -Action Remove @target } '*Refusing deletion*'
if ($state.Deletes -or $state.Creates -ne 1) { throw 'Unsafe deploy or removal' }
$state.Owned = $true
$state.Tier.StorageAccounts = 'Standard' # Changed pricing must not prevent cleanup.
& $entry -Action Remove @target | Out-Null
& $entry -Action Remove @target | Out-Null
if ($state.Deletes -ne 1 -or $state.Exists -or $state.Creates -ne 1) {
    throw 'Remove and its absent-group retry must delete only the owned group once and never create'
}

# Opt-in for an already-protected subscription: named plans plus approval metadata, never a setting change.
$ack = @{ ApprovalReference = 'approval-record-1'; ApprovalExpires = (Get-Date).AddDays(1); ApprovalCurrency = 'EUR'; ApprovalCeiling = 5 }
$all = 'StorageAccounts', 'KeyVaults', 'CloudPosture'
foreach ($plan in $all) { $state.Tier[$plan] = 'Standard' }
$before = $state.Calls
$badAck = @(
    @{ Change = @{ ApprovalReference = ' ' }; Error = '*Defender plans requires*' },
    @{ Change = @{ ApprovalCeiling = 0 }; Error = '*Defender plans requires*' },
    @{ Change = @{ ApprovalExpires = (Get-Date).AddDays(-1) }; Error = '*expired*' },
    @{ Change = @{ ApprovalCurrency = 'eur' }; Error = '*currency code*' },
    @{ Change = @{ ApprovalCurrency = 'EURO' }; Error = '*currency code*' }
)
foreach ($case in $badAck) {
    $partial = $ack.Clone()
    foreach ($key in $case.Change.Keys) { $partial[$key] = $case.Change[$key] }
    Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all @partial } $case.Error
}
Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all } '*Defender plans requires*'
foreach ($missing in 'ApprovalReference', 'ApprovalExpires', 'ApprovalCurrency', 'ApprovalCeiling') {
    $partial = $ack.Clone()
    $partial.Remove($missing)
    Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all @partial } '*Defender plans requires*'
}
Expect-Error { & $entry -Action Deploy @target -AcceptPaidDefenderPlans $all @ack } '*spend approval*'
Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans 'storageaccounts' @ack } '*AcceptPaidDefenderPlans*'
if ($state.Calls -ne $before) { throw 'Invalid or missing approval metadata must stop before any CLI call' }
Expect-Error { & $entry -Action Deploy @target -SpendApproved @ack } '*Free tier*StorageAccounts*' # Metadata alone is not an opt-in.
Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans 'StorageAccounts', 'CloudPosture' @ack } '*Free tier*KeyVaults*'
$state.Tier.KeyVaults = ''
Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all @ack } '*recognised tier*KeyVaults*'
$state.Tier.KeyVaults = 'standard' # Tier names are case-sensitive.
Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all @ack } '*recognised tier*KeyVaults*'
$state.Tier.KeyVaults = 'Standard'
$state.FailPricing = $true
Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all @ack } '*security pricing*failed*'
$state.FailPricing = $false
$state.Active = [guid]::NewGuid().ToString()
Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all @ack } '*not the requested sandbox*'
$state.Active = $target.SubscriptionId.ToString()
if ($state.Creates -ne 1) { throw 'A refused opt-in must create nothing' }

$state.Tier.CloudPosture = 'Free' # Accepting a plan that is Free is harmless and not reported as inherited.
$result = & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all @ack -WarningVariable warned -WarningAction SilentlyContinue
if ($result -cne "rg-$name") { throw 'Opt-in deploy did not return the group name' }
if ($warned.Count -ne 1 -or $warned[0].Message -notlike '*StorageAccounts, KeyVaults*approval-record-1*EUR*not enforced*' -or
    $warned[0].Message -like '*CloudPosture*') {
    throw 'Opt-in deploy must report only the inherited plans with the approval metadata'
}
if ($state.Creates -ne 2 -or $state.Deletes -ne 1 -or -not $state.Exists -or $state.PricingWrites) {
    throw 'Opt-in Deploy must create once without deleting or writing Defender settings'
}
Expect-Error { & $entry -Action Deploy @target -SpendApproved -AcceptPaidDefenderPlans $all @ack } '*already exists*'
$state.Owned = $false
Expect-Error { & $entry -Action Remove @target -AcceptPaidDefenderPlans $all @ack } '*Refusing deletion*'
$state.Owned = $true
& $entry -Action Remove @target | Out-Null
if ($state.Deletes -ne 2 -or $state.Exists -or $state.Creates -ne 2 -or $state.PricingWrites) {
    throw 'Opt-in Remove must keep ownership checks, never create and never write Defender settings'
}

# Challenge 2 stops if the lab group is outside the Corp archetype's allowed regions.
$region = (Get-Content -Raw (Join-Path $PSScriptRoot 'lab-defaults.json') | ConvertFrom-Json).location
$archetypes = Join-Path $PSScriptRoot '..' 'resources' 'archetypes.json'
$regionCheck = 'Corp region check skipped: resources/archetypes.json absent'
if (Test-Path -LiteralPath $archetypes) {
    $corp = (Get-Content -Raw -LiteralPath $archetypes | ConvertFrom-Json).archetypes | Where-Object id -eq 'corp'
    if ($region -cnotin @($corp.parameters.allowed_locations)) {
        throw "Default region $region is not in allowed_locations of the Corp archetype; challenge 2 would stop."
    }
    $regionCheck = "default region $region allowed by Corp"
}
Write-Output "PASS: action isolation (Validate read-only, Deploy never deletes, Remove never creates), Free-only default, explicit paid-Defender opt-in and approval metadata, target checks, CLI errors, collision and guarded teardown (mock CLI); $regionCheck."
