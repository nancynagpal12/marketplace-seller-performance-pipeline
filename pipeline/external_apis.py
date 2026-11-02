import time
from functools import lru_cache

import pandas as pd
import requests


# API endpoints
FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rates"
IBGE_STATES_URL = (
    "https://servicodados.ibge.gov.br/api/v1/localidades/estados"
)

TIMEOUT = 30
MAX_ATTEMPTS = 3


def fetch_json(url, params=None):
    """Fetch JSON from an API with timeout and retry handling."""

    last_error = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            return response.json()

        except (requests.RequestException, ValueError) as error:
            last_error = error

            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"API request failed after {MAX_ATTEMPTS} attempts. "
        f"URL: {url}. Error: {last_error}"
    )


@lru_cache(maxsize=32)
def get_brl_usd_rates(start_date, end_date):
    """
    Fetch historical BRL-to-USD exchange rates for a date range.

    Returns a DataFrame containing the rate date and exchange rate.
    """

    params = {
        "from": start_date,
        "to": end_date,
        "base": "BRL",
        "quotes": "USD",
    }

    data = fetch_json(FRANKFURTER_URL, params=params)

    if not isinstance(data, list):
        raise ValueError(
            "Unexpected Frankfurter response: expected a list of rates."
        )

    rates = pd.DataFrame(data)

    if rates.empty:
        raise ValueError(
            f"No BRL-to-USD rates returned for {start_date} to {end_date}."
        )

    required_columns = {"date", "rate"}

    if not required_columns.issubset(rates.columns):
        raise ValueError(
            "Frankfurter response is missing expected columns: "
            f"{required_columns - set(rates.columns)}"
        )

    rates = rates.rename(columns={"date": "rate_date"})

    rates["rate_date"] = pd.to_datetime(
        rates["rate_date"], errors="raise"
    ).dt.date

    rates["rate"] = pd.to_numeric(
        rates["rate"], errors="raise"
    )

    rates = rates.sort_values("rate_date").reset_index(drop=True)

    return rates[["rate_date", "rate"]]


@lru_cache(maxsize=1)
def get_state_region_mapping():
    """
    Fetch Brazilian state abbreviations and their geographic regions.

    Returns a DataFrame with state_code and region columns.
    """

    data = fetch_json(IBGE_STATES_URL)

    if not isinstance(data, list) or not data:
        raise ValueError(
            "Unexpected IBGE response: expected a non-empty list of states."
        )

    records = []

    for state in data:
        region_data = state.get("regiao") or {}

        records.append({
            "state_code": state.get("sigla"),
            "state_name": state.get("nome"),
            "region": region_data.get("nome"),
        })

    mapping = pd.DataFrame(records)

    if mapping[["state_code", "region"]].isna().any().any():
        raise ValueError(
            "IBGE response contains states with missing codes or regions."
        )

    return mapping.sort_values("state_code").reset_index(drop=True)

def convert_brl_to_usd(data, amount_col, date_col, rates):
    """
    Convert BRL amounts to USD using the latest exchange rate
    available on or before the transaction date.
    """

    result = data.copy()
    result["_original_order"] = range(len(result))

    result[date_col] = pd.to_datetime(
        result[date_col], errors="coerce"
    )

    rate_data = rates.copy()

    rate_data["rate_date"] = pd.to_datetime(
        rate_data["rate_date"], errors="coerce"
    )

    rate_data["rate_date"] = rate_data["rate_date"].astype(
        "datetime64[ns]"
    )

    result[date_col] = result[date_col].astype(
        "datetime64[ns]"
    )

    rate_data["rate"] = pd.to_numeric(
        rate_data["rate"], errors="coerce"
    )

    rate_data = rate_data.dropna(
        subset=["rate_date", "rate"]
    ).sort_values("rate_date")

    valid_dates = result[result[date_col].notna()].copy()
    invalid_dates = result[result[date_col].isna()].copy()

    valid_dates = valid_dates.sort_values(date_col)

    converted = pd.merge_asof(
        valid_dates.drop(
        columns=["rate_date", "rate"],
        errors="ignore"
    ),
    rate_data,
    left_on=date_col,
    right_on="rate_date",
    direction="backward",
    )

    converted[f"{amount_col}_usd"] = (
        pd.to_numeric(converted[amount_col], errors="coerce")
        * converted["rate"]
    )

    invalid_dates["rate_date"] = pd.NaT
    invalid_dates["rate"] = float("nan")
    invalid_dates[f"{amount_col}_usd"] = float("nan")

    result = pd.concat(
        [converted, invalid_dates],
        ignore_index=True,
    )

    result = result.sort_values("_original_order")
    result = result.drop(columns="_original_order")

    return result.reset_index(drop=True)

if __name__ == "__main__":
    print("Testing Frankfurter API...")

    fx_rates = get_brl_usd_rates(
        "2018-01-01",
        "2018-01-10",
    )

    print("\nBRL-to-USD exchange rates:")
    print(fx_rates.to_string(index=False))

    print("\nTesting IBGE API...")

    state_regions = get_state_region_mapping()

    print("Number of Brazilian states and federal district:",
          len(state_regions))

    print("\nSample state-to-region mapping:")
    print(state_regions.head(10).to_string(index=False))

    print("\nAPI tests completed successfully.")