# grocery.ps1 — compile src/*.json into grocery.json (raw purchase amounts, pack-rounded).
# Sums cooked amounts (both people) across the week, converts cooked -> raw via each
# ingredient's yield, rounds UP to real pack sizes, groups purchases (e.g. chicken cuts),
# and lists staples/aromatics separately. Inventory subtraction is Phase 3.
#
# Usage:  pwsh build/grocery.ps1           (writes grocery.json)
#         pwsh build/grocery.ps1 -Check    (also diff computed vs the hand-written grocery list)

param([switch]$Check)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$srcDir = Join-Path $root 'src'
$LB = 453.592
$TOL = 0.06   # pack-fraction tolerance: absorbs tiny overshoots so we don't jump a full pack

function LoadJson($p) { Get-Content -Raw -Encoding UTF8 $p | ConvertFrom-Json }
function HasProp($o, $n) { $null -ne $o -and ($o.PSObject.Properties.Name -contains $n) }
function CeilPack($x, $pack) { [math]::Ceiling($x / $pack - $TOL) * $pack }

$ingredients = LoadJson (Join-Path $srcDir 'ingredients.json')
$meals       = LoadJson (Join-Path $srcDir 'meals.json')
$week        = LoadJson (Join-Path $srcDir 'week.json')

$slotOrder = @('breakfast', 'lunch', 'dinner')

# ingredient spec lookup
$spec = @{}
foreach ($p in $ingredients.PSObject.Properties) { if (-not $p.Name.StartsWith('_')) { $spec[$p.Name] = $p.Value } }

# --- sum consumption across the week (both people) ---
$cookedG = @{}   # 100g-basis ingredients: total cooked grams
$countU  = @{}   # unit-basis ingredients: total count
foreach ($dk in $week.weekOrder) {
    $wd = $week.days.$dk
    foreach ($slot in $slotOrder) {
        $sv = $wd.slots.$slot
        if ($null -eq $sv) { continue }
        $mid = if ($sv -is [string]) { $sv } else { $sv.meal }
        foreach ($cp in $meals.$mid.components) {
            $amt = [double]$cp.him + [double]$cp.her
            if ($amt -eq 0) { continue }
            $s = $spec[$cp.ing]
            if ($s.basis -eq 'unit') { $countU[$cp.ing] = ([double]($countU[$cp.ing]) + $amt) }
            else { $cookedG[$cp.ing] = ([double]($cookedG[$cp.ing]) + $amt) }
        }
    }
    $countU['koia'] = ([double]($countU['koia']) + [double]$wd.shake.him + [double]$wd.shake.her)
}

$GROUP_LABEL = @{ chicken = 'Chicken (thigh + breast)' }
$UNIT_WORD = @{ lb = 'lb'; cup_dry = 'cups dry'; dozen = 'dozen'; bottle = 'bottles';
    can = 'can'; container = 'container'; tub = 'tub'; carton = 'carton'; bag = 'bag'; gallon = 'gallon'; each = '' }

function FmtQty($qty, $unit, $label) {
    if ($unit -eq 'each') { return "$qty" }
    $w = $UNIT_WORD[$unit]
    return "$qty $w"
}

# --- build purchase lines ---
$order = @()
$staples = @()
$groups = @{}   # groupKey -> @{ base_g; count; members=@(); spec }

foreach ($ing in ($cookedG.Keys + $countU.Keys | Select-Object -Unique)) {
    $s = $spec[$ing]
    $g = $s.grocery
    if ($g.is_staple) { $staples += $s.name; continue }
    $groupKey = if (HasProp $g 'purchase_group') { $g.purchase_group } else { $ing }
    if (-not $groups.ContainsKey($groupKey)) { $groups[$groupKey] = @{ base_g = 0.0; count = 0.0; members = @(); spec = $g; label = $s.name } }
    if ($s.basis -eq 'unit') { $groups[$groupKey].count += [double]$countU[$ing] }
    else { $groups[$groupKey].base_g += [double]$cookedG[$ing] / [double]$g.yield }   # cooked -> raw/dry grams
    $groups[$groupKey].members += $ing
}

foreach ($gk in $groups.Keys) {
    $grp = $groups[$gk]
    $g = $grp.spec
    $pu = $g.purchase_unit; $pack = [double]$g.pack_size; $ug = $g.unit_grams
    switch ($pu) {
        'lb'      { $x = $grp.base_g / $LB }
        'cup_dry' { $x = $grp.base_g / [double]$ug }
        'dozen'   { $x = $grp.count / 12.0 }
        'bottle'  { $x = $grp.count }
        default   { $x = $grp.base_g / [double]$ug }   # each / can / container / tub / carton / bag / gallon
    }
    $qty = CeilPack $x $pack
    if ($qty -eq [math]::Floor($qty)) { $qty = [int]$qty }
    $label = if ($GROUP_LABEL.ContainsKey($gk)) { $GROUP_LABEL[$gk] } else { $grp.label }
    $order += [ordered]@{
        key = $gk; name = $label; quantity = $qty; unit = $pu
        display = (FmtQty $qty $pu $label)
        cooked_g = if ($grp.base_g -gt 0) { [math]::Round($grp.base_g * [double]$g.yield, 1) } else { $null }
        raw_g = if ($grp.base_g -gt 0) { [math]::Round($grp.base_g, 1) } else { $null }
        count = if ($grp.count -gt 0) { $grp.count } else { $null }
        members = $grp.members
    }
}

$order = $order | Sort-Object { $_.name }

$out = [ordered]@{
    weekId = $week.weekId
    note = 'Gross purchase (round-up). Phase 3 subtracts fridge inventory to get the net order.'
    order = @($order)
    staples = @($staples | Sort-Object)
}

if ($Check) {
    # hand-written grocery list for this week (grocery-list.md) as { groupKey = expected quantity }
    $hand = @{
        ground_beef = 5; chicken = 3; shrimp = 2; steak = 1; egg = 2; koia = 5;
        rice = 2.75; farro = 1.25; lentils = 1.75; beans = 1; oats = 1; tortilla = 6;
        sweet_potato = 3.75; peppers = 2.5; spinach = 1.75; yu_choy = 1.5; brussels = 1.25;
        broccolini = 0.75; squash = 0.75; onion = 2; mushrooms = 0.5; edamame = 0.5;
        avocado = 4; mango = 4; strawberry = 1; greek_yogurt = 1; milk = 0.5; cheese = 1
    }
    $handNote = @{ koia = 'weekend shakes from stock'; tortilla = 'sold in 6-packs'; avocado = 'ripeness overbuy'; mango = 'hand says 3-4'; greek_yogurt = '1 tub + small extra' }
    "{0,-26} {1,-14} {2,-14} {3}" -f 'ITEM', 'COMPUTED', 'HAND-LIST', 'MATCH'
    "{0,-26} {1,-14} {2,-14} {3}" -f ('-'*24), ('-'*12), ('-'*12), ('-----')
    $nMatch = 0; $nTotal = 0
    foreach ($item in $order) {
        $k = $item.key; $nTotal++
        $comp = $item.quantity
        if ($hand.ContainsKey($k)) {
            $exp = $hand[$k]
            $ok = [math]::Abs([double]$comp - [double]$exp) -lt 1e-6
            if ($ok) { $nMatch++; $mark = 'OK' } else { $mark = '**  ' + $(if ($handNote.ContainsKey($k)) { $handNote[$k] } else { 'diff' }) }
            "{0,-26} {1,-14} {2,-14} {3}" -f $item.name, $item.display, ("{0} {1}" -f $exp, $UNIT_WORD[$item.unit]), $mark
        }
        else {
            "{0,-26} {1,-14} {2,-14} {3}" -f $item.name, $item.display, '(none)', '?'
        }
    }
    ""
    "Matched {0}/{1} lines exactly. Staples (buy-when-low): {2}" -f $nMatch, $nTotal, ($staples -join ', ')
}
else {
    $json = $out | ConvertTo-Json -Depth 20
    Set-Content -Path (Join-Path $root 'grocery.json') -Value $json -Encoding UTF8
    Write-Output ("wrote " + (Join-Path $root 'grocery.json'))
}
