# build.ps1 — PowerShell port of build.py (runs on this machine without Python).
# Compiles src/*.json into data.json (same shape the app + widget consume).
# Usage:  pwsh build/build.ps1            (writes data.json)
#         pwsh build/build.ps1 -Verify    (build in-memory, deep-compare to committed data.json, no write)

param([switch]$Verify)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$srcDir = Join-Path $root 'src'
$EMDASH = [char]0x2014

function LoadJson($p) { Get-Content -Raw -Encoding UTF8 $p | ConvertFrom-Json }
# Round half to even (banker's) — matches how the committed totals block was generated.
function Rnd($x) { [long][math]::Round([double]$x, [System.MidpointRounding]::ToEven) }
function HasProp($o, $n) { $null -ne $o -and ($o.PSObject.Properties.Name -contains $n) }

$ingredients = LoadJson (Join-Path $srcDir 'ingredients.json')
$meals       = LoadJson (Join-Path $srcDir 'meals.json')
$week        = LoadJson (Join-Path $srcDir 'week.json')

$slotLabel = @{ breakfast = 'Breakfast'; lunch = 'Lunch'; dinner = 'Dinner' }
$slotOrder = @('breakfast', 'lunch', 'dinner')
$SHAKE = 'koia'
$MACROS = @('kcal', 'p', 'c', 'fib', 'f')

# --- nutrition + labels (strip _comment and the grocery block) ---
$nutrition = [ordered]@{}
$labels = [ordered]@{}
foreach ($prop in $ingredients.PSObject.Properties) {
    if ($prop.Name.StartsWith('_')) { continue }
    $s = $prop.Value
    $nutrition[$prop.Name] = [ordered]@{ basis = $s.basis; kcal = $s.kcal; p = $s.p; c = $s.c; fib = $s.fib; f = $s.f }
    $labels[$prop.Name]    = [ordered]@{ name = $s.name; unit = $s.unit }
}

function NutOf($ing, $amt) {
    $n = $nutrition[$ing]
    $k = if ($n['basis'] -eq '100g') { $amt / 100.0 } else { [double]$amt }
    @{ kcal = $n['kcal'] * $k; p = $n['p'] * $k; c = $n['c'] * $k; fib = $n['fib'] * $k; f = $n['f'] * $k }
}
function MealTotals($comps, $who) {
    $t = @{ kcal = 0.0; p = 0.0; c = 0.0; fib = 0.0; f = 0.0 }
    foreach ($cp in $comps) {
        $a = $cp.$who
        if ($a) { $x = NutOf $cp.ing $a; foreach ($m in $MACROS) { $t[$m] += $x[$m] } }
    }
    $t
}

# --- days ---
$days = [ordered]@{}
foreach ($dk in $week.weekOrder) {
    $wd = $week.days.$dk
    $mealsOut = @()
    foreach ($slot in $slotOrder) {
        $sv = $wd.slots.$slot
        if ($null -eq $sv) { continue }
        if ($sv -is [string]) { $mid = $sv; $noteOv = $null }
        else { $mid = $sv.meal; $noteOv = if (HasProp $sv 'note') { $sv.note } else { $null } }
        $m = $meals.$mid
        $obj = [ordered]@{ name = ($slotLabel[$slot] + ' ' + $EMDASH + ' ' + $m.name); tag = $m.tag }
        if ((HasProp $m 'lpr') -and $m.lpr) { $obj['lpr'] = $true }
        $note = if ($null -ne $noteOv) { $noteOv } elseif (HasProp $m 'note') { $m.note } else { '' }
        if ($note) { $obj['note'] = $note }
        $comps = @()
        foreach ($cp in $m.components) { $comps += [ordered]@{ ing = $cp.ing; him = $cp.him; her = $cp.her } }
        $obj['comps'] = @($comps)
        $mealsOut += $obj
    }
    $days[$dk] = [ordered]@{
        label = $wd.label; sub = $wd.sub; meals = @($mealsOut)
        shake = [ordered]@{ ing = $SHAKE; him = $wd.shake.him; her = $wd.shake.her }
    }
}

# --- totals (widget) ---
$totals = [ordered]@{}
foreach ($dk in $week.weekOrder) {
    $wd = $week.days.$dk
    $dm = @()
    foreach ($slot in $slotOrder) {
        $sv = $wd.slots.$slot
        if ($null -eq $sv) { continue }
        $mid = if ($sv -is [string]) { $sv } else { $sv.meal }
        $mm = $meals.$mid
        $dm += , @{ name = $mm.name; components = $mm.components }
    }
    $entry = [ordered]@{ label = $wd.label; sub = $wd.sub }
    foreach ($who in @('him', 'her')) {
        $floor = if ($who -eq 'him') { 180 } else { 100 }
        $tot = @{ kcal = 0.0; p = 0.0; c = 0.0; fib = 0.0; f = 0.0 }
        $ml = @()
        foreach ($m in $dm) {
            $mt = MealTotals $m.components $who
            foreach ($k in $MACROS) { $tot[$k] += $mt[$k] }
            if ($mt['kcal'] -gt 0) { $ml += [ordered]@{ name = $m.name; kcal = (Rnd $mt['kcal']) } }
        }
        $sk = $wd.shake.$who
        if ($sk) {
            $x = NutOf $SHAKE $sk
            foreach ($k in $MACROS) { $tot[$k] += $x[$k] }
            $ml += [ordered]@{ name = $labels[$SHAKE]['name']; kcal = (Rnd $x['kcal']) }
        }
        $entry[$who] = [ordered]@{
            kcal = (Rnd $tot['kcal']); p = (Rnd $tot['p']); c = (Rnd $tot['c']); fib = (Rnd $tot['fib']); f = (Rnd $tot['f'])
            floorMet = ($tot['p'] -ge $floor)
            target = $week.targets.$who.kcal; ptarget = $week.targets.$who.p
            meals = @($ml)
        }
    }
    $totals[$dk] = $entry
}

$data = [ordered]@{
    nutrition = $nutrition; labels = $labels; targets = $week.targets
    days = $days; weekOrder = @($week.weekOrder); weekId = $week.weekId; totals = $totals
}

# ---------- deep compare ----------
function IsMap($o) { ($o -is [System.Collections.IDictionary]) -or ($o -is [pscustomobject]) }
function MapKeys($o) { if ($o -is [System.Collections.IDictionary]) { @($o.Keys) } else { @($o.PSObject.Properties.Name) } }
function MapGet($o, $k) { if ($o -is [System.Collections.IDictionary]) { $o[$k] } else { $o.$k } }
function IsNum($o) { $o -is [int] -or $o -is [long] -or $o -is [double] -or $o -is [decimal] -or $o -is [single] }

$script:diffs = @()
function DeepCompare($a, $b, $path) {
    if ((IsMap $a) -and (IsMap $b)) {
        $ka = @(MapKeys $a); $kb = @(MapKeys $b)
        foreach ($k in $ka) { if ($kb -notcontains $k) { $script:diffs += "$path.$k : only in candidate" } }
        foreach ($k in $kb) { if ($ka -notcontains $k) { $script:diffs += "$path.$k : only in committed" } }
        foreach ($k in $ka) { if ($kb -contains $k) { DeepCompare (MapGet $a $k) (MapGet $b $k) "$path.$k" } }
        return
    }
    if (($a -is [Array]) -and ($b -is [Array])) {
        if ($a.Count -ne $b.Count) { $script:diffs += "$path : array len $($a.Count) vs $($b.Count)"; return }
        for ($i = 0; $i -lt $a.Count; $i++) { DeepCompare $a[$i] $b[$i] "$path[$i]" }
        return
    }
    if (($a -is [bool]) -or ($b -is [bool])) {
        if ([bool]$a -ne [bool]$b) { $script:diffs += "$path : bool $a vs $b" }; return
    }
    if ((IsNum $a) -and (IsNum $b)) {
        if ([math]::Abs([double]$a - [double]$b) -gt 1e-6) { $script:diffs += "$path : num $a vs $b" }; return
    }
    if ([string]$a -ne [string]$b) { $script:diffs += "$path : '$a' vs '$b'" }
}

if ($Verify) {
    $committed = LoadJson (Join-Path $root 'data.json')
    DeepCompare $data $committed '$'
    if ($script:diffs.Count -eq 0) {
        Write-Output "PASS: candidate data.json is semantically identical to committed data.json."
    }
    else {
        Write-Output ("FAIL: {0} difference(s):" -f $script:diffs.Count)
        $script:diffs | Select-Object -First 40 | ForEach-Object { Write-Output "  $_" }
    }
}
else {
    $json = $data | ConvertTo-Json -Depth 30 -Compress
    Set-Content -Path (Join-Path $root 'data.json') -Value $json -Encoding UTF8 -NoNewline
    Write-Output ("wrote " + (Join-Path $root 'data.json'))
}
