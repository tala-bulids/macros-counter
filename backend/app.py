import os
import sys
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pydantic import ValidationError
from openai import OpenAI

# Ensure backend folder is on sys.path (fixes import issues on Windows)
sys.path.append(os.path.dirname(__file__))

from schema import ParseResult
from fdc import search_food, get_food_details, extract_macros_per_100g

# ---------------------------
# Paths + Static Hosting (Render-friendly)
# ---------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # .../MacCountProject/backend
PROJECT_DIR = os.path.dirname(BASE_DIR)                # .../MacCountProject
STATIC_DIR = os.path.join(PROJECT_DIR, "static")       # .../MacCountProject/static

# Serve static files from / (so /style.css and /app.js work)
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/")
CORS(app)

@app.get("/")
def home():
    return send_from_directory(STATIC_DIR, "index.html")


client = OpenAI()

SYSTEM_PROMPT = """
You are a meal text parser for macro estimation apps.

Return data that matches the provided ParseResult schema exactly.
Rules:
- Do NOT guess quantities. If missing, set quantity=null and ask in missing_info.
- Support Arabic/English and casual slang; normalize obvious typos (record in assumptions).
- Split into multiple dishes if the text mentions multiple items.
- For composite dishes (e.g., kabsa/mendi/pizza), do NOT invent a full recipe. Keep it as a dish and ask for missing details.
- Use these units when possible: g, ml, tsp, tbsp, cup, piece, slice.
- Keep confidence values between 0 and 1.
"""


# ---------------------------
# AI Parsing
# ---------------------------
def parse_with_ai(text: str) -> ParseResult:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    resp = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        text_format=ParseResult,
    )

    parsed = resp.output_parsed
    if parsed is None:
        raise RuntimeError("AI returned no parsed output (output_parsed is None).")

    return parsed


# ---------------------------
# Helpers
# ---------------------------
def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _scale(value_per_100g, grams: float) -> float:
    if value_per_100g is None:
        return 0.0
    return (float(value_per_100g) / 100.0) * grams


def _answers_lower_map(answers: dict) -> dict:
    out = {}
    for k, v in (answers or {}).items():
        if isinstance(k, str):
            out[k.strip().lower()] = v
    return out


def _round_macros(d: dict, ndigits: int = 2) -> dict:
    out = {}
    for k, v in (d or {}).items():
        try:
            out[k] = round(float(v), ndigits)
        except (TypeError, ValueError):
            out[k] = v
    return out


def _add_assumption(parsed: ParseResult, note: str) -> None:
    if not note:
        return
    if getattr(parsed, "assumptions", None) is None:
        parsed.assumptions = []
    parsed.assumptions.append(note)


def _clean_missing(missing: list[str], grams_sources: dict[str, float]) -> list[str]:
    cleaned = []
    for m in missing:
        ml = _norm(str(m))

        if "how many grams" in ml:
            drop = False
            for name in grams_sources.keys():
                if name and name in ml:
                    drop = True
                    break
            if drop:
                continue
            cleaned.append(m)
            continue

        if ("quantity" in ml or "amount" in ml) and any(name in ml for name in grams_sources.keys()):
            continue

        cleaned.append(m)
    return cleaned


# ---------------------------
# Auto-convert "piece/slice/tbsp..." -> grams using USDA portions
# ---------------------------
UNIT_ALIASES = {
    "piece": ["piece", "pieces", "unit", "whole", "large", "medium", "small", "egg"],
    "slice": ["slice", "slices"],
    "tbsp": ["tbsp", "tablespoon"],
    "tsp": ["tsp", "teaspoon"],
    "cup": ["cup"],
    "ml": ["ml", "milliliter", "millilitre"],
}


def _portion_label(portion: dict) -> str:
    modifier = _norm(portion.get("modifier"))
    desc = _norm(portion.get("portionDescription"))
    mu = portion.get("measureUnit") or {}
    mu_name = _norm(mu.get("name"))
    return modifier or mu_name or desc


def _find_gram_weight_from_portions(food_details: dict, unit: str) -> float | None:
    portions = food_details.get("foodPortions") or []
    u = _norm(unit)
    keywords = UNIT_ALIASES.get(u, [u])

    for p in portions:
        gw = p.get("gramWeight")
        if gw is None:
            continue

        label = _portion_label(p)
        if not label:
            continue

        if any(k in label for k in keywords):
            return float(gw)

    return None


def _try_convert_to_grams(ing, food_details: dict) -> tuple[float | None, str | None]:
    if ing.quantity is None:
        return None, None

    unit = _norm(ing.unit)
    if unit not in UNIT_ALIASES:
        return None, None

    gw = _find_gram_weight_from_portions(food_details, unit)
    if gw is None:
        return None, None

    grams = float(ing.quantity) * gw
    note = f"Converted {ing.quantity} {unit} of '{ing.name}' using USDA portion ({gw} g per {unit})."
    return grams, note


# ---------------------------
# FIX: Energy unit normalization (kJ -> kcal when needed)
# ---------------------------
KJ_TO_KCAL = 1.0 / 4.184


def _fix_energy_units_if_needed(per100: dict, parsed: ParseResult, food_desc: str) -> dict:
    if not per100:
        return per100

    cal = per100.get("calories_kcal_per_100g")
    if cal is None:
        return per100

    try:
        cal = float(cal)
    except (TypeError, ValueError):
        return per100

    p = float(per100.get("protein_g_per_100g") or 0.0)
    c = float(per100.get("carbs_g_per_100g") or 0.0)
    f = float(per100.get("fat_g_per_100g") or 0.0)

    expected_kcal = 4.0 * p + 4.0 * c + 9.0 * f

    if expected_kcal > 0:
        ratio = cal / expected_kcal
        if 3.2 <= ratio <= 5.2:
            per100["calories_kcal_per_100g"] = cal * KJ_TO_KCAL
            _add_assumption(parsed, f"Energy for '{food_desc}' looked like kJ; converted to kcal (÷4.184).")
            return per100

    if cal > 1000:
        per100["calories_kcal_per_100g"] = cal * KJ_TO_KCAL
        _add_assumption(parsed, f"Energy for '{food_desc}' was >1000 per 100g; assumed kJ and converted to kcal (÷4.184).")

    return per100


# ---------------------------
# Better candidate selection (don’t just pick candidates[0])
# ---------------------------
def _choose_best_fdc_match(ing_name: str, candidates: list[dict], parsed: ParseResult):
    ing_l = _norm(ing_name)

    best_item = None
    best_details = None
    best_per100 = None
    best_score = -10**9

    for cand in (candidates or []):
        desc = _norm(cand.get("description") or "")

        if any(bad in desc for bad in ["sandwich", "burger", "cake", "cookie", "pizza", "wrap", "roll"]):
            base_penalty = -10
        else:
            base_penalty = 0

        try:
            details = get_food_details(cand["fdcId"])
            per100 = extract_macros_per_100g(details)
            per100 = _fix_energy_units_if_needed(per100, parsed, cand.get("description") or ing_name)
        except Exception:
            continue

        cal = float(per100.get("calories_kcal_per_100g") or 0.0)
        fat = float(per100.get("fat_g_per_100g") or 0.0)
        prot = float(per100.get("protein_g_per_100g") or 0.0)
        carbs = float(per100.get("carbs_g_per_100g") or 0.0)

        score = 0 + base_penalty

        dtype = _norm(cand.get("dataType") or "")
        if "foundation" in dtype:
            score += 3
        if "sr legacy" in dtype or "sr_legacy" in dtype:
            score += 2

        if any(w in desc for w in ["raw", "whole", "fresh"]):
            score += 2

        if cal > 0:
            score += 1
        if prot > 0:
            score += 1
        if fat > 0:
            score += 1

        if "egg" in ing_l:
            user_wants_white = ("white" in ing_l or "egg white" in ing_l)
            if user_wants_white:
                if "white" in desc:
                    score += 6
                else:
                    score -= 5
            else:
                if "white" in desc:
                    score -= 8
                if "whole" in desc:
                    score += 6
                if fat < 2:
                    score -= 6

        expected_kcal = 4.0 * prot + 4.0 * carbs + 9.0 * fat
        if expected_kcal > 0 and cal > 0:
            ratio = cal / expected_kcal
            if 0.6 <= ratio <= 1.6:
                score += 2
            else:
                score -= 2

        if score > best_score:
            best_score = score
            best_item = cand
            best_details = details
            best_per100 = per100

    if best_item:
        _add_assumption(parsed, f"Selected USDA match: '{best_item.get('description')}' for '{ing_name}'.")

    return best_item, best_details, best_per100


# ---------------------------
# Routes
# ---------------------------
@app.post("/parse")
def parse_meal():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()

    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        result = parse_with_ai(text)
        return jsonify(result.model_dump())

    except ValidationError as e:
        return jsonify({"error": "Schema validation failed", "details": e.errors()}), 500

    except Exception as e:
        return jsonify({"error": "AI parse failed", "details": str(e)}), 502


@app.post("/macros")
def macros():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    answers = data.get("answers") or {}
    answers_map = _answers_lower_map(answers)

    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        parsed = parse_with_ai(text)

        missing = list(parsed.missing_info or [])
        breakdown = []

        grams_sources: dict[str, float] = {}
        answers_used: list[str] = []

        for dish in parsed.dishes:
            for ing in dish.ingredients:
                ing_name_l = _norm(ing.name)

                candidates = search_food(ing.name, page_size=3)
                if not candidates:
                    missing.append(f"Could not find '{ing.name}' in USDA database. Try a more specific name.")
                    continue

                best, details, per100 = _choose_best_fdc_match(ing.name, candidates, parsed)
                if not best or not details or not per100:
                    missing.append(f"Could not confidently match '{ing.name}' in USDA. Try a more specific name.")
                    continue

                grams = None

                if ing.quantity is not None and _norm(ing.unit) == "g":
                    grams = float(ing.quantity)

                if grams is None:
                    key = f"grams:{ing.name}".strip().lower()
                    if key in answers_map:
                        try:
                            grams = float(answers_map[key])
                            answers_used.append(key)
                        except (TypeError, ValueError):
                            missing.append(
                                f"Invalid grams value for '{ing.name}'. Provide a number in answers['grams:{ing.name}']."
                            )
                            continue

                conversion_note = None
                if grams is None:
                    grams, conversion_note = _try_convert_to_grams(ing, details)
                    if conversion_note:
                        _add_assumption(parsed, conversion_note)

                if grams is None:
                    missing.append(f"How many grams is '{ing.name}'? (send answers['grams:{ing.name}'])")
                    continue

                grams_sources[ing_name_l] = grams

                item_macros = {
                    "calories_kcal": _scale(per100.get("calories_kcal_per_100g"), grams),
                    "protein_g": _scale(per100.get("protein_g_per_100g"), grams),
                    "fat_g": _scale(per100.get("fat_g_per_100g"), grams),
                    "carbs_g": _scale(per100.get("carbs_g_per_100g"), grams),
                }

                breakdown.append(
                    {
                        "ingredient": ing.name,
                        "grams": round(float(grams), 2),
                        "fdc_best_match": best.get("description"),
                        "macros": _round_macros(item_macros, 3),
                    }
                )

        seen = set()
        unique_breakdown = []
        for b in breakdown:
            k = (_norm(b.get("ingredient")), float(b.get("grams") or 0.0), _norm(b.get("fdc_best_match")))
            if k in seen:
                continue
            seen.add(k)
            unique_breakdown.append(b)

        totals = {"calories_kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0}
        for b in unique_breakdown:
            m = b.get("macros") or {}
            totals["calories_kcal"] += float(m.get("calories_kcal") or 0.0)
            totals["protein_g"] += float(m.get("protein_g") or 0.0)
            totals["fat_g"] += float(m.get("fat_g") or 0.0)
            totals["carbs_g"] += float(m.get("carbs_g") or 0.0)

        totals = _round_macros(totals, 2)

        missing = _clean_missing(missing, grams_sources)
        missing = sorted(set(missing))

        return jsonify(
            {
                "parsed": parsed.model_dump(),
                "breakdown": unique_breakdown,
                "totals": totals,
                "missing_info": missing,
                "answers_used": sorted(set(answers_used)),
            }
        )

    except Exception as e:
        return jsonify({"error": "Macro calculation failed", "details": str(e)}), 502


if __name__ == "__main__":
    # Local works + Render (Render provides PORT env)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False, use_reloader=False)
