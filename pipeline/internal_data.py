from pathlib import Path
import pandas as pd
import json

INTERNAL_DIR = Path("data/internal")


def set_internal_directory(directory):
    global INTERNAL_DIR
    INTERNAL_DIR = Path(directory)

def load_internal_files():
    """Load the four internal files without modifying the originals."""

    commission_rates = pd.read_csv(
        INTERNAL_DIR / "commission_rates.csv"
    )

    overrides = pd.read_csv(
        INTERNAL_DIR / "category_commission_overrides.csv"
    )

    translation_patch = pd.read_csv(
        INTERNAL_DIR / "category_translation_patch.csv"
    )

    with open(INTERNAL_DIR / "campaigns.json", encoding="utf-8") as file:
        campaigns = json.load(file)

    return commission_rates, overrides, translation_patch, campaigns


def clean_commission_rates(commission_rates):
    """Normalize tier names and record corrections."""

    rates = commission_rates.copy()
    issues = []

    for index, row in rates.iterrows():
        original_tier = row["tier"]
        cleaned_tier = original_tier.strip().title()

        if original_tier != cleaned_tier:
            issues.append({
                "source_file": "commission_rates.csv",
                "row_number": index + 2,
                "original_value": original_tier,
                "corrected_value": cleaned_tier,
                "reason": "Tier capitalization or whitespace normalized"
            })

        rates.at[index, "tier"] = cleaned_tier

    return rates, issues


def clean_category_overrides(overrides):
    """Normalize category names and reject invalid date ranges."""

    cleaned = overrides.copy()
    issues = []

    for index, row in cleaned.iterrows():
        original_name = row["category_name_en"]
        cleaned_name = original_name.strip().lower()

        if original_name != cleaned_name:
            issues.append({
                "source_file": "category_commission_overrides.csv",
                "row_number": index + 2,
                "original_value": original_name,
                "corrected_value": cleaned_name,
                "reason": "Category name whitespace or capitalization normalized"
            })

        cleaned.at[index, "category_name_en"] = cleaned_name

    cleaned["effective_from"] = pd.to_datetime(
        cleaned["effective_from"], errors="coerce"
    )
    cleaned["effective_to"] = pd.to_datetime(
        cleaned["effective_to"], errors="coerce"
    )

    invalid_dates = (
        cleaned["effective_to"].notna()
        & (cleaned["effective_from"] > cleaned["effective_to"])
    )

    for index, row in cleaned[invalid_dates].iterrows():
        issues.append({
            "source_file": "category_commission_overrides.csv",
            "row_number": index + 2,
            "original_value": (
                f'{row["effective_from"].date()} to '
                f'{row["effective_to"].date()}'
            ),
            "corrected_value": None,
            "reason": "Rejected: effective_from is after effective_to"
        })

    # Keep only valid override records.
    cleaned = cleaned.loc[~invalid_dates].copy()

    return cleaned, issues

def get_clean_internal_data():
    """Return cleaned internal files and their data-quality issues."""

    rates, overrides, translation_patch, campaigns = load_internal_files()

    rates, rate_issues = clean_commission_rates(rates)
    overrides, override_issues = clean_category_overrides(overrides)

    issues = rate_issues + override_issues

    return {
        "commission_rates": rates,
        "category_overrides": overrides,
        "translation_patch": translation_patch,
        "campaigns": campaigns,
        "issues": issues,
    }

def main():
    rates, overrides, translation_patch, campaigns = load_internal_files()

    rates, rate_issues = clean_commission_rates(rates)
    overrides, override_issues = clean_category_overrides(overrides)

    issues = rate_issues + override_issues

    print("Cleaned commission tiers:")
    print(rates[["tier", "rate"]])

    print("\nValid category overrides:")
    print(overrides[["category_name_en", "fixed_rate"]])

    print("\nData-quality issues recorded:", len(issues))
    for issue in issues:
        print(issue)

    print("\nTranslation patches loaded:", len(translation_patch))
    print("Campaigns loaded:", len(campaigns))


if __name__ == "__main__":
    main()