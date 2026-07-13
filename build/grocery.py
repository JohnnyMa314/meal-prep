#!/usr/bin/env python3
"""
grocery.py — compile src/*.json into grocery.json (raw purchase amounts, pack-rounded).

Sums cooked amounts (both people) across the week, converts cooked -> raw via each
ingredient's yield, rounds UP to real pack sizes, groups purchases (e.g. chicken cuts),
and lists staples/aromatics separately. Inventory subtraction is Phase 3.

    python build/grocery.py            # writes grocery.json
    python build/grocery.py --check    # diff computed vs the hand-written grocery list
"""

import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

LB = 453.592
TOL = 0.06  # pack-fraction tolerance: absorbs tiny overshoots so we don't jump a full pack
SLOT_ORDER = ["breakfast", "lunch", "dinner"]

GROUP_LABEL = {"chicken": "Chicken (thigh + breast)"}
UNIT_WORD = {
    "lb": "lb", "cup_dry": "cups dry", "dozen": "dozen", "bottle": "bottles",
    "can": "can", "container": "container", "tub": "tub", "carton": "carton",
    "bag": "bag", "gallon": "gallon", "each": "",
}


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


def ceil_pack(x, pack):
    return math.ceil(x / pack - TOL) * pack


def fmt_qty(qty, unit):
    if unit == "each":
        return f"{qty}"
    return f"{qty} {UNIT_WORD[unit]}".rstrip()


def compute():
    ingredients = load("ingredients.json")
    meals = load("meals.json")
    week = load("week.json")

    spec = {k: v for k, v in ingredients.items() if not k.startswith("_")}

    # --- sum consumption across the week (both people) ---
    cooked_g, count_u = {}, {}
    for dk in week["weekOrder"]:
        wd = week["days"][dk]
        for slot in SLOT_ORDER:
            sv = wd["slots"].get(slot)
            if sv is None:
                continue
            mid = sv if isinstance(sv, str) else sv["meal"]
            for cp in meals[mid]["components"]:
                amt = cp["him"] + cp["her"]
                if amt == 0:
                    continue
                if spec[cp["ing"]]["basis"] == "unit":
                    count_u[cp["ing"]] = count_u.get(cp["ing"], 0) + amt
                else:
                    cooked_g[cp["ing"]] = cooked_g.get(cp["ing"], 0) + amt
        count_u["koia"] = count_u.get("koia", 0) + wd["shake"]["him"] + wd["shake"]["her"]

    # --- group + convert to purchase quantities ---
    groups, staples = {}, []
    for ing in sorted(set(cooked_g) | set(count_u)):   # sorted => deterministic output
        g = spec[ing]["grocery"]
        if g.get("is_staple"):
            staples.append(spec[ing]["name"])
            continue
        gk = g.get("purchase_group", ing)
        grp = groups.setdefault(gk, {"base_g": 0.0, "count": 0.0, "spec": g,
                                     "label": spec[ing]["name"], "members": []})
        if spec[ing]["basis"] == "unit":
            grp["count"] += count_u[ing]
        else:
            grp["base_g"] += cooked_g[ing] / g["yield"]   # cooked -> raw/dry grams
        grp["members"].append(ing)

    order = []
    for gk, grp in groups.items():
        g = grp["spec"]
        pu, pack, ug = g["purchase_unit"], g["pack_size"], g["unit_grams"]
        if pu == "lb":
            x = grp["base_g"] / LB
        elif pu == "cup_dry":
            x = grp["base_g"] / ug
        elif pu == "dozen":
            x = grp["count"] / 12.0
        elif pu == "bottle":
            x = grp["count"]
        else:  # each / can / container / tub / carton / bag / gallon
            x = grp["base_g"] / ug
        qty = ceil_pack(x, pack)
        if qty == int(qty):
            qty = int(qty)
        label = GROUP_LABEL.get(gk, grp["label"])
        order.append({
            "key": gk, "name": label, "quantity": qty, "unit": pu,
            "display": fmt_qty(qty, pu),
            "cooked_g": round(grp["base_g"] * g["yield"], 1) if grp["base_g"] else None,
            "raw_g": round(grp["base_g"], 1) if grp["base_g"] else None,
            "count": grp["count"] or None,
            "members": grp["members"],
        })

    order.sort(key=lambda r: r["name"])
    result = {
        "weekId": week["weekId"],
        "note": "Gross purchase (round-up). Phase 3 subtracts fridge inventory to get the net order.",
        "order": order,
        "staples": sorted(staples),
    }
    return result


HAND = {  # grocery-list.md for this week: group key -> expected quantity
    "ground_beef": 5, "chicken": 3, "shrimp": 2, "steak": 1, "egg": 2, "koia": 5,
    "rice": 2.75, "farro": 1.25, "lentils": 1.75, "beans": 1, "oats": 1, "tortilla": 6,
    "sweet_potato": 3.75, "peppers": 2.5, "spinach": 1.75, "yu_choy": 1.5, "brussels": 1.25,
    "broccolini": 0.75, "squash": 0.75, "onion": 2, "mushrooms": 0.5, "edamame": 0.5,
    "avocado": 4, "mango": 4, "strawberry": 1, "greek_yogurt": 1, "milk": 0.5, "cheese": 1,
}
HAND_NOTE = {"koia": "weekend shakes from stock", "tortilla": "sold in 6-packs",
             "avocado": "ripeness overbuy", "greek_yogurt": "1 tub + small extra"}


def main():
    result = compute()
    if "--check" in sys.argv:
        print(f"{'ITEM':<26} {'COMPUTED':<14} {'HAND-LIST':<14} MATCH")
        print(f"{'-'*24:<26} {'-'*12:<14} {'-'*12:<14} -----")
        n_match = 0
        for item in result["order"]:
            k, comp = item["key"], item["quantity"]
            if k in HAND:
                exp = HAND[k]
                ok = abs(comp - exp) < 1e-6
                mark = "OK" if ok else "**  " + HAND_NOTE.get(k, "diff")
                n_match += ok
                exp_disp = f"{exp} {UNIT_WORD[item['unit']]}".rstrip()
                print(f"{item['name']:<26} {item['display']:<14} {exp_disp:<14} {mark}")
        print()
        print(f"Matched {n_match}/{len(result['order'])} lines exactly. "
              f"Staples (buy-when-low): {', '.join(result['staples'])}")
        return
    out = os.path.join(ROOT, "grocery.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    main()
