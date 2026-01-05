from fdc import search_food, get_food_details, extract_macros_per_100g

q = "egg"
foods = search_food(q, page_size=3)
print("Top candidates:")
for f in foods:
    print("-", f.get("description"), "| fdcId:", f.get("fdcId"))

fdc_id = foods[0]["fdcId"]
details = get_food_details(fdc_id)
macros = extract_macros_per_100g(details)
print("\nMacros per 100g:", macros)
