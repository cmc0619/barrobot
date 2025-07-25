# Barrobot version 0.005
"""
app.py – Complete Flask server for the Bar-Robot
(2025-07-20, with automatic CocktailDB downloader)

• First run (or if recipes.json is missing):
      – Downloads every drink from TheCocktailDB
      – Converts all measures to ounces
      – Scales so the smallest non-zero measure becomes 1.5 oz
      – Caches the result in recipes.json (offline from then on)

• Features:
      – Menu (only makeable drinks)
      – Drink detail page (click thumbnail)
      – Suggestions (exactly one missing) and Suggestions 2 (≥1 missing)
      – Configure Bottles UI (slots, pantry, substitutions, safe-mode)
      – Motor Controls with live slot test (API /api/rotate/<slot>)
      – Safe-mode toggle

Requires: `pip install flask requests`
"""

from __future__ import annotations
from pathlib import Path
import json, re, requests, os, math
from typing import Any, Dict, List, Tuple
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify
)
import hardware                      # your GPIO helper

# ─── Paths & constants ───────────────────────────────────────────
SHOT = 1.5   # dispenser step, in oz
BASE_DIR     = Path(__file__).parent
CONFIG_PATH  = BASE_DIR / "config.json"
RECIPES_PATH = BASE_DIR / "recipes.json"
DEFAULT_PIN_MAP = {"DIR": 20, "STEP": 21, "ENABLE": 16, "ACTUATOR": 26}
COCKTAIL_API   = "https://www.thecocktaildb.com/api/json/v1/1"
# Read CocktailDB API key from env or config.json
ENV_KEY = os.getenv("COCKTAILDB_API_KEY")
CFG_KEY = json.loads(CONFIG_PATH.read_text()).get("api_key") if CONFIG_PATH.exists() else None
API_KEY = ENV_KEY or CFG_KEY or "1"   # default to free key "1"

FREE_BASE = "https://www.thecocktaildb.com/api/json/v1/1"
PAID_BASE = f"https://www.thecocktaildb.com/api/json/v2/{API_KEY}"

app = Flask(__name__)
app.secret_key = "change-me-in-production"

# ─── Utility helpers ─────────────────────────────────────────────
def _norm(s: Any) -> Any:
    return s.strip().lower() if isinstance(s, str) and s.strip() else None

_OZ_RX = re.compile(r"(?P<num>[\d./]+)\s*(?P<u>oz|ounce|ounces|ml|cl)?", re.I)

def _qty_to_oz(raw: str | None) -> float:
    """
    Parse CocktailDB measure → fluid-ounces.
    Handles mixed fractions (“2 1/2 oz”), metric, etc.
    Returns 0.0 for obvious garnishes/solids.
    """
    if not raw:
        return 0.0

    txt = raw.strip().lower()

    # skip garnishes
    if any(w in txt for w in ["slice", "wedge", "dash", "pinch",
                              "sprig", "piece", "cube", "twist"]):
        return 0.0

    # mixed fraction  e.g. "2 1/2 oz"
    m = re.match(r"(\d+)\s+(\d)/(\d)", txt)
    if m:
        whole, num, den = map(float, m.groups())
        qty = whole + num / den
        unit = re.search(r"(oz|ounce|ounces|ml|cl)", txt)
        unit = unit.group(1) if unit else "oz"
    else:
        # simple number or simple fraction
        m = re.match(r"(\d+/\d+|\d+(?:\.\d+)?)\s*(oz|ounce|ounces|ml|cl)?", txt)
        if not m:
            return 0.0
        num_txt, unit = m.groups()
        qty = (float(num_txt.split("/")[0]) / float(num_txt.split("/")[1])
               if "/" in num_txt else float(num_txt))
        unit = unit or ""

    # convert
    if unit == "ml":
        qty *= 0.033814
    elif unit == "cl":
        qty *= 0.33814
    return round(qty, 2)

def _scale(lst: list[dict]) -> list[dict]:
    """
    Scale *liquid* ingredients so the smallest non-zero qty_oz is 1.5.
    Works on a list of dicts like:
        {"item": "gin", "qty_oz": 2.5, "raw": "2 1/2 oz"}
    Garnishes (qty_oz == 0) are left untouched.
    """
    liquids = [d["qty_oz"] for d in lst if d["qty_oz"] > 0]
    if not liquids:
        return lst

    factor = 1.5 / min(liquids)
    for d in lst:
        if d["qty_oz"] > 0:
            d["qty_oz"] = round(d["qty_oz"] * factor, 2)
    return lst

def _nearest_multiple(value: float, step: float) -> float:
    """
    Return the multiple of *step* that is *closest* to *value*.
    Exactly halfway (.75 when step=1.5) rounds **down** to the lower multiple,
    so 2.25 → 1.5, 2.99 → 3.0, 3.76 → 4.5.
    """
    return math.floor((value / step) + 0.5) * step

def scale_for_slots(recipe: Dict[str, Any], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    shot = cfg.get("shot_size", 1.5)       # 1.5 = one dispense
    items = recipe["ingredients"]

    # ── 1. find largest slot liquid ─────────────────────────────
    slot_liq = [d for d in items if d["item"] in cfg["slots"] and d["qty_oz"] > 0]
    if not slot_liq:
        return items                       # nothing to scale

    anchor_qty = max(d["qty_oz"] for d in slot_liq)

    # ── 2. factor that sends anchor to *nearest* shot multiple ──
    target = _nearest_multiple(anchor_qty, shot)
    if target == 0:                        # safety
        target = shot
    base_factor = target / anchor_qty

    # ── 3. apply factor & round slot liquids to nearest shot ───
    scaled: list[dict] = []
    for d in items:
        new = d.copy()
        if d["qty_oz"] > 0:
            new["qty_oz"] = d["qty_oz"] * base_factor
            if d["item"] in cfg["slots"]:
                new["qty_oz"] = _nearest_multiple(new["qty_oz"], shot)
            new["qty_oz"] = round(new["qty_oz"], 2)
        scaled.append(new)

    return scaled

# ─── Config load / save ──────────────────────────────────────────
def load_config() -> Dict[str, Any]:
    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    cfg.setdefault("api_key", API_KEY)   # keep whatever key we detected
    cfg.setdefault("shot_size", 1.5)      # ounces per dispense
    cfg.setdefault("slots", [None] * 12)
    cfg.setdefault("pantry", [])
    cfg.setdefault("substitutions", {})
    cfg.setdefault("safe_mode", True)
    cfg.setdefault("pins", DEFAULT_PIN_MAP.copy())
    cfg["slots"]         = [_norm(s) for s in cfg["slots"]]
    cfg["pantry"]        = [_norm(p) for p in cfg["pantry"] if _norm(p)]
    cfg["substitutions"] = {k.lower(): v.lower()
                            for k, v in cfg["substitutions"].items()}
    return cfg

def save_config(cfg): CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

# ─── Recipe downloader & cache ───────────────────────────────────
def _download_all() -> List[Dict[str, Any]]:
    """
    Fetch the full CocktailDB catalogue and return a list of drinks in our
    internal format (raw measures + qty_oz).

    • If API_KEY is present and not "1" → paid endpoint, single call:
        GET /search.php?s=
    • Otherwise → free tier, loop A-Z with /search.php?f=a … f=z
    """
    # Decide which base URL to hit
    if API_KEY and API_KEY not in ("", "1"):
        base = PAID_BASE
        print("[Downloader] Paid API key detected → single-call fetch")
        try:
            resp = requests.get(f"{base}/search.php", params={"s": ""}, timeout=30)
            resp.raise_for_status()
            drinks_json = resp.json().get("drinks", []) or []
        except Exception as exc:                       # noqa: BLE001
            print("[Downloader] FAILED:", exc)
            return []
    else:
        base = FREE_BASE
        print("[Downloader] Using free API → A-Z loop")
        drinks_json: list[dict] = []
        for letter in "abcdefghijklmnopqrstuvwxyz":
            try:
                r = requests.get(f"{base}/search.php", params={"f": letter}, timeout=10)
                if r.status_code == 200 and r.json().get("drinks"):
                    drinks_json.extend(r.json()["drinks"])
            except Exception:
                continue

    print(f"[Downloader] {len(drinks_json)} drinks received")

    processed: List[Dict[str, Any]] = []
    for d in drinks_json:
        # Build list of ingredient dicts
        raw_ings: list[dict] = []
        for i in range(1, 16):
            ing_name = d.get(f"strIngredient{i}")
            if ing_name and ing_name.strip():
                measure = d.get(f"strMeasure{i}") or ""
                raw_ings.append({
                    "item":   _norm(ing_name),
                    "qty_oz": _qty_to_oz(measure),
                    "raw":    measure.strip()
                })

        processed.append({
            "id":           d["idDrink"],
            "name":         d["strDrink"],
            "image":        d["strDrinkThumb"],
            "instructions": d["strInstructions"],
            "ingredients":  _scale(raw_ings),   # slot-aware scaling happens later
        })

    RECIPES_PATH.write_text(json.dumps(processed, indent=2))
    print("[Downloader] recipes.json written")
    return processed

def load_recipes() -> List[Dict[str, Any]]:
    return json.loads(RECIPES_PATH.read_text()) if RECIPES_PATH.exists() else _download_all()

def parse_ingredients(r): return [(i["item"], i["qty_oz"]) for i in r["ingredients"]]

# ─── Availability helpers ────────────────────────────────────────
def _avail(item: str, cfg):         # slot / pantry / substitution
    item = item.lower()
    if item in cfg["slots"] or item in cfg["pantry"]:
        return True
    sub = cfg["substitutions"].get(item)
    return bool(sub and (sub in cfg["slots"] or sub in cfg["pantry"]))

def _slot_for(item: str, cfg) -> int | None:
    item = item.lower()
    if item in cfg["slots"]:
        return cfg["slots"].index(item)
    sub = cfg["substitutions"].get(item)
    if sub and sub in cfg["slots"]:
        return cfg["slots"].index(sub)
    return None

# ─── Routes – UI pages ───────────────────────────────────────────
@app.route("/")
def menu():
    cfg = load_config()
    drinks = [d for d in load_recipes()
              if all(_avail(i, cfg) for i, _ in parse_ingredients(d))]
    return render_template("menu.html", drinks=drinks)

@app.route("/drink/<drink_id>")
def drink_detail(drink_id):
    d = next((x for x in load_recipes() if x["id"] == drink_id), None)
    if not d: flash("Drink not found", "error"); return redirect(url_for("menu"))
    return render_template("drink.html", drink=d)

@app.route("/suggestions")
def suggestions():
    cfg = load_config(); ideas=[]
    for r in load_recipes():
        miss=[i for i,_ in parse_ingredients(r) if not _avail(i,cfg)]
        if len(miss)==1: ideas.append({"recipe":r,"missing":miss[0]})
    return render_template("suggestions.html",ideas=ideas)

@app.route("/suggestions2")
def suggestions2():
    cfg = load_config(); ideas=[]
    for r in load_recipes():
        miss=[i for i,_ in parse_ingredients(r) if not _avail(i,cfg)]
        if miss: ideas.append({"recipe":r,"missing":miss})
    return render_template("suggestions2.html",ideas=ideas)

# ─── Configure Bottles ───────────────────────────────────────────
@app.route("/configure", methods=["GET","POST"])
def configure():
    cfg=load_config()
    if request.method=="POST":
        shot_txt = request.form.get("shot_size") or "1.5"
        try:
            cfg["shot_size"] = max(0.5, float(shot_txt))
        except ValueError:
            cfg["shot_size"] = 1.5

        cfg["slots"]=[_norm(request.form.get(f"slot{i}")) for i in range(12)]
        cfg["pantry"]=[_norm(p) for p in (request.form.get("pantry") or "").split(",") if _norm(p)]
        subs={}; 
        for n in range(6):
            k=_norm(request.form.get(f"sub_key{n}")); v=_norm(request.form.get(f"sub_val{n}"))
            if k and v: subs[k]=v
        cfg["substitutions"]=subs
        cfg["safe_mode"]=bool(request.form.get("safe_mode"))
        save_config(cfg); flash("Configuration saved.","success")
        return redirect(url_for("menu"))
    return render_template("configure.html", bottle_config=cfg)

# ─── Motor Controls + API rotate ─────────────────────────────────
@app.route("/motor", methods=["GET","POST"])
def motor_controls():
    cfg=load_config()
    if request.method=="POST":
        cfg["pins"]={sig:int(request.form[sig]) for sig in ("DIR","STEP","ENABLE","ACTUATOR")}
        save_config(cfg); hardware.set_pin_map(cfg["pins"])
        flash("Pin map saved.","success"); return redirect(url_for("menu"))
    return render_template("motor_controls.html", pins=cfg["pins"])

@app.route("/api/rotate/<int:slot>", methods=["POST"])
def api_rotate(slot:int):
    if not 1<=slot<=12: return jsonify(status="error",msg="range"),400
    cfg=load_config(); hardware.set_pin_map(cfg["pins"]); hardware.set_safe_mode(cfg["safe_mode"])
    hardware.rotate_to_slot(slot-1); return jsonify(status="ok")

# ─── Make drink ─────────────────────────────────────────────────
@app.route("/make_drink/<name>")
def make_drink(name: str):
    cfg = load_config()

    # Apply current GPIO settings
    hardware.set_pin_map(cfg["pins"])
    hardware.set_safe_mode(cfg["safe_mode"])

    # Look up the recipe (case-insensitive)
    drink = next(
        (d for d in load_recipes() if d["name"].lower() == name.lower()),
        None
    )
    if drink is None:
        flash(f"No recipe named “{name}”.", "error")
        return redirect(url_for("menu"))

    # Go ingredient by ingredient
    for idx, (item, qty) in enumerate(parse_ingredients(drink)):
        if not _avail(item, cfg):
            flash(f"Missing {item}", "error")
            return redirect(url_for("menu"))

        slot = _slot_for(item, cfg)

        # Fun status messages
        flash(("Pulling" if idx == 0 else "Adding") + f" {item}…", "info")

        if slot is not None:
            # Dispense automatically
            hardware.rotate_to_slot(slot)
            flash(f"Dispensing {qty:g} oz!", "info")
            hardware.press_actuator(repetitions=round(qty))
        else:
            # Pantry item → manual add
            flash(f"(Pantry) Please add {qty:g} oz {item} manually.", "info")

    flash(f"{drink['name']} is ready — cheers!", "success")
    return redirect(url_for("menu"))
# ─── Dev run ─────────────────────────────────────────────────────
if __name__ == "__main__":
    cfg0 = load_config()
    hardware.set_pin_map(cfg0["pins"])
    hardware.set_safe_mode(cfg0["safe_mode"])
    try:
        app.run(host="0.0.0.0", port=5000, debug=True)
    finally:
        hardware.cleanup()

