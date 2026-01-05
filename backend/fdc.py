import os
import time
from typing import Optional

import requests

FDC_BASE = "https://api.nal.usda.gov/fdc/v1"

# Macros by nutrient NAME (works across many food types)
MACRO_KEYS = {
    "calories_kcal_per_100g": ["Energy"],
    "protein_g_per_100g": ["Protein"],
    "fat_g_per_100g": ["Total lipid (fat)"],
    "carbs_g_per_100g": ["Carbohydrate, by difference"],
}


def _fdc_key() -> str:
    key = os.getenv("FDC_API_KEY")
    if not key:
        raise RuntimeError("Missing FDC_API_KEY environment variable.")
    # Quick sanity check: OpenAI keys start with sk- (avoid accidental mixups)
    if key.strip().startswith("sk-"):
        raise RuntimeError(
            "FDC_API_KEY looks like an OpenAI key (starts with 'sk-'). "
            "Use your data.gov FoodData Central API key instead."
        )
    return key.strip()


def _redact_url(url: str) -> str:
    # Remove api_key from URL if present
    if "api_key=" not in url:
        return url
    base = url.split("api_key=")[0]
    return base + "api_key=REDACTED"


def _request_with_retries(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    json: Optional[dict] = None,
    timeout: int = 30,
    retries: int = 2,
    backoff_sec: float = 0.8,
) -> dict:
    last_exc = None
    for attempt in range(retries + 1):
        try:
            r = requests.request(
                method=method,
                url=url,
                params=params,
                json=json,
                timeout=timeout,
                headers={"Accept": "application/json"},
            )

            # Raise informative error (without leaking api_key)
            if r.status_code >= 400:
                safe_url = _redact_url(r.url or url)
                # Try to read error json text safely
                try:
                    detail = r.json()
                except Exception:
                    detail = (r.text or "").strip()[:500]
                raise requests.HTTPError(
                    f"{r.status_code} {r.reason} | url={safe_url} | detail={detail}"
                )

            return r.json()

        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff_sec * (2 ** attempt))
                continue
            raise

        except requests.HTTPError as e:
            # No retry on 4xx typically (bad key / forbidden / etc.)
            raise

    # Should not reach here
    raise last_exc or RuntimeError("Unknown request failure")


def search_food(query: str, page_size: int = 5) -> list[dict]:
    """
    Returns top candidate foods from FoodData Central search.
    """
    url = f"{FDC_BASE}/foods/search"
    params = {"api_key": _fdc_key()}
    payload = {
        "query": query,
        "pageSize": page_size,
        # Prefer generic sources first
        "dataType": ["Foundation", "SR Legacy", "Survey (FNDDS)"],
    }

    data = _request_with_retries("POST", url, params=params, json=payload)
    return data.get("foods", [])


def get_food_details(fdc_id: int) -> dict:
    """
    Food details by FDC ID.
    """
    url = f"{FDC_BASE}/food/{fdc_id}"
    params = {"api_key": _fdc_key()}
    return _request_with_retries("GET", url, params=params)


def extract_macros_per_100g(food_details: dict) -> dict:
    """
    Returns macros per 100g using nutrient names.
    """
    nutrients = food_details.get("foodNutrients", [])
    by_name = {}

    for n in nutrients:
        nutrient = n.get("nutrient") or {}
        name = nutrient.get("name")
        amount = n.get("amount")
        unit = nutrient.get("unitName")
        if name and amount is not None:
            by_name[name] = {"amount": float(amount), "unit": unit}

    def pick(nutrient_names: list[str]) -> Optional[float]:
        for nm in nutrient_names:
            if nm in by_name:
                return by_name[nm]["amount"]
        return None

    return {
        "calories_kcal_per_100g": pick(MACRO_KEYS["calories_kcal_per_100g"]),
        "protein_g_per_100g": pick(MACRO_KEYS["protein_g_per_100g"]),
        "fat_g_per_100g": pick(MACRO_KEYS["fat_g_per_100g"]),
        "carbs_g_per_100g": pick(MACRO_KEYS["carbs_g_per_100g"]),
    }
