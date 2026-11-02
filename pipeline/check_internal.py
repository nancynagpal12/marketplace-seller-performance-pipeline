from pathlib import Path
import pandas as pd
import json

# Folder containing the internal files
INTERNAL_DIR = Path("data/internal")

# Read the three CSV files
commission_rates = pd.read_csv(
    INTERNAL_DIR / "commission_rates.csv"
)

overrides = pd.read_csv(
    INTERNAL_DIR / "category_commission_overrides.csv"
)

translation_patch = pd.read_csv(
    INTERNAL_DIR / "category_translation_patch.csv"
)

# Read the JSON file
with open(INTERNAL_DIR / "campaigns.json", encoding="utf-8") as file:
    campaigns = json.load(file)

# Display the results
print("Commission rates:", len(commission_rates), "rows")
print(commission_rates)

print("\nCategory overrides:", len(overrides), "rows")
print(overrides)

print("\nTranslation patches:", len(translation_patch), "rows")
print(translation_patch)

print("\nCampaigns:", len(campaigns))
for campaign in campaigns:
    print(campaign["campaign_id"], "-", campaign["name"])

# Identify suspicious values without modifying the original files
print("\n--- Data Quality Checks ---")

print("\nCommission rates with inconsistent tier capitalization:")
print(
    commission_rates[
        commission_rates["tier"]
        != commission_rates["tier"].str.title()
    ]
)

print("\nOverrides with leading/trailing spaces in category names:")
print(
    overrides[
        overrides["category_name_en"]
        != overrides["category_name_en"].str.strip()
    ]
)

overrides["effective_from"] = pd.to_datetime(
    overrides["effective_from"], errors="coerce"
)
overrides["effective_to"] = pd.to_datetime(
    overrides["effective_to"], errors="coerce"
)

print("\nOverrides with invalid date ranges:")
print(
    overrides[
        overrides["effective_to"].notna()
        & (overrides["effective_from"] > overrides["effective_to"])
    ]
)