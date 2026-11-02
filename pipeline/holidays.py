import time
import requests

HOLIDAY_API_URL = "https://date.nager.at/api/v3/PublicHolidays"

# Cache holiday results in memory so each year is fetched only once.
_holiday_cache = {}


def get_brazil_holidays(year):
    """Fetch and cache Brazil's public holiday data for a year."""

    if year in _holiday_cache:
        return _holiday_cache[year]

    url = f"{HOLIDAY_API_URL}/{year}/BR"
    last_error = None

    for attempt in range(3):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            holidays = response.json()

            _holiday_cache[year] = holidays
            return holidays

        except (requests.RequestException, ValueError) as error:
            last_error = error

            if attempt < 2:
                time.sleep(attempt + 1)

    raise RuntimeError(
        f"Could not fetch Brazil holidays for {year} after 3 attempts: "
        f"{last_error}"
    )


def get_holiday_dates(year, state=None):
    """
    Return public holiday dates applicable nationally or to a state.

    Nager.Date uses subdivision identifiers such as BR-SP in counties.
    """
    holidays = get_brazil_holidays(year)
    dates = set()

    for holiday in holidays:
        holiday_types = holiday.get("types", [])
        counties = holiday.get("counties") or []

        # Include national public holidays.
        if "Public" in holiday_types and not counties:
            dates.add(holiday["date"])

        # Include public holidays that apply to the requested state.
        if state and f"BR-{state.upper()}" in counties:
            if "Public" in holiday_types:
                dates.add(holiday["date"])

    return dates

if __name__ == "__main__":
    if __name__ == "__main__":
    	holidays = get_brazil_holidays(2017)

    print(f"Total holidays returned for 2017: {len(holidays)}")

    for holiday in holidays:
        if "Public" in holiday.get("types", []):
            print(
                holiday["date"],
                "|",
                holiday["localName"],
                "| Counties:",
                holiday.get("counties"),
                "| Types:",
                holiday.get("types")
            )