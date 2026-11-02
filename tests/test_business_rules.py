import pandas as pd
import pytest

from pipeline import transform
from pipeline import load_facts


def test_r6_uses_latest_available_rate_and_never_future_rate():
    data = pd.DataFrame({
        "amount": [100, 100, 50],
        "transaction_date": ["2024-01-02", "2024-01-04", None]
    })

    rates = pd.DataFrame({
        "rate_date": ["2024-01-01", "2024-01-03"],
        "rate": [0.20, 0.25]
    })

    result = transform.convert_brl_to_usd(
        data, "amount", "transaction_date", rates
    )

    assert result.loc[0, "amount_usd"] == pytest.approx(20)
    assert result.loc[1, "amount_usd"] == pytest.approx(25)
    assert pd.isna(result.loc[2, "amount_usd"])


def test_r9_calculates_business_days_and_excludes_holidays(monkeypatch):
    monkeypatch.setattr(
        transform,
        "get_holiday_dates",
        lambda year, state=None: ["2024-01-08"]
    )

    data = pd.DataFrame({
        "approval_date": [
            pd.Timestamp("2024-01-05"),
            pd.Timestamp("2024-01-05"),
            pd.NaT
        ],
        "delivery_date": [
            pd.Timestamp("2024-01-09"),
            pd.Timestamp("2024-01-04"),
            pd.Timestamp("2024-01-09")
        ],
        "customer_state": ["SP", "SP", "SP"]
    })

    result = transform.calculate_weekday_lead_days(data)

    # Monday is a holiday; only Tuesday counts.
    assert result.loc[0, "weekday_lead_days"] == 1

    # Delivery before approval and missing approval are invalid.
    assert pd.isna(result.loc[1, "weekday_lead_days"])
    assert pd.isna(result.loc[2, "weekday_lead_days"])


def test_r9_identifies_missing_and_invalid_dates():
    data = pd.DataFrame({
        "order_id": ["A", "B", "C"],
        "order_approved_at": [
            "2024-01-05",
            None,
            "2024-01-09"
        ],
        "order_delivered_customer_date": [
            None,
            "2024-01-10",
            "2024-01-08"
        ]
    })

    result = transform.calculate_calendar_lead_days(data)

    assert result.loc[0, "lead_time_issue"] == "missing_delivery_date"
    assert result.loc[1, "lead_time_issue"] == "missing_approval_date"
    assert result.loc[2, "lead_time_issue"] == "delivery_before_approval"


def test_r12_assigns_seller_tiers_using_previous_month_revenue():
    data = pd.DataFrame({
        "seller_id": ["A", "B", "C", "D"],
        "order_month": pd.PeriodIndex(
            ["2024-02", "2024-02", "2024-02", "2024-02"],
            freq="M"
        ),
        "monthly_revenue": [1000, 1000, 1000, 1000]
    })

    previous = pd.DataFrame({
        "seller_id": ["A", "B", "C"],
        "order_month": pd.PeriodIndex(
            ["2024-01", "2024-01", "2024-01"],
            freq="M"
        ),
        "monthly_revenue": [4999, 5000, 20001]
    })

    result = transform.assign_seller_tiers(
        pd.concat([data, previous], ignore_index=True)
    )

    february = result[result["order_month"] == pd.Period("2024-02")]
    tiers = february.set_index("seller_id")["seller_tier"]

    assert tiers["A"] == "Bronze"
    assert tiers["B"] == "Silver"
    assert tiers["C"] == "Gold"
    assert tiers["D"] == "Bronze"


def test_r13_category_override_takes_precedence_over_tier_rate(monkeypatch):
    monkeypatch.setattr(
        transform,
        "get_clean_internal_data",
        lambda: {"translation_patch": pd.DataFrame()}
    )

    monkeypatch.setattr(
        transform.pd,
        "read_csv",
        lambda *args, **kwargs: pd.DataFrame()
    )

    def fake_resolve_categories(data, products, translations, patch):
        result = data.copy()
        result["product_category_name_english"] = "electronics"
        return result

    monkeypatch.setattr(
        transform,
        "resolve_item_categories",
        fake_resolve_categories
    )

    order_items = pd.DataFrame({
        "order_id": ["O1"],
        "order_item_id": [1],
        "product_id": ["P1"],
        "seller_id": ["S1"],
        "price": [100.0],
        "freight_value": [20.0]
    })

    orders = pd.DataFrame({
        "order_id": ["O1"],
        "order_purchase_timestamp": ["2024-01-10"],
        "order_approved_at": ["2024-01-10"],
        "order_status": ["delivered"]
    })

    products = pd.DataFrame({"product_id": ["P1"]})

    seller_tiers = pd.DataFrame({
        "seller_id": ["S1"],
        "order_month": [pd.Period("2024-01", freq="M")],
        "seller_tier": ["Bronze"]
    })

    commission_rates = pd.DataFrame({
        "tier": ["Bronze"],
        "rate": [0.10],
        "effective_from": ["2024-01-01"],
        "effective_to": ["2024-12-31"]
    })

    category_overrides = pd.DataFrame({
        "category_name_en": ["electronics"],
        "fixed_rate": [0.20],
        "effective_from": ["2024-01-01"],
        "effective_to": ["2024-12-31"]
    })

    fx_rates = pd.DataFrame({
        "rate_date": ["2024-01-01"],
        "rate": [0.20]
    })

    result = transform.calculate_item_commission(
        order_items,
        orders,
        products,
        seller_tiers,
        commission_rates,
        category_overrides,
        fx_rates
    )

    assert result.loc[0, "commission_rate"] == pytest.approx(0.20)
    assert result.loc[0, "commission_brl"] == pytest.approx(20.0)

    # Gross includes freight, but commission is based on item price only.
    assert result.loc[0, "item_gross_brl"] == pytest.approx(120.0)


def test_r18_highest_priority_campaign_wins():
    items = pd.DataFrame({
        "order_id": ["O1"],
        "category_name": ["electronics"]
    })

    orders = pd.DataFrame({
        "order_id": ["O1"],
        "customer_id": ["C1"],
        "order_purchase_timestamp": ["2024-01-15"]
    })

    customers = pd.DataFrame({
        "customer_id": ["C1"],
        "customer_state": ["SP"],
        "region": ["Southeast"]
    })

    campaigns = [
        {
            "campaign_id": "LOW",
            "start": "2024-01-01",
            "end": "2024-01-31",
            "priority": 1,
            "target_states": ["SP"],
            "target_regions": [],
            "categories": ["ALL"]
        },
        {
            "campaign_id": "HIGH",
            "start": "2024-01-10",
            "end": "2024-01-31",
            "priority": 5,
            "target_states": [],
            "target_regions": ["Southeast"],
            "categories": ["electronics"]
        }
    ]

    result = transform.attribute_campaigns(
        items, orders, customers, campaigns
    )

    assert result.loc[0, "campaign_id"] == "HIGH"


def test_r18_later_start_date_breaks_equal_priority_tie():
    items = pd.DataFrame({
        "order_id": ["O1"],
        "category_name": ["electronics"]
    })

    orders = pd.DataFrame({
        "order_id": ["O1"],
        "customer_id": ["C1"],
        "order_purchase_timestamp": ["2024-01-15"]
    })

    customers = pd.DataFrame({
        "customer_id": ["C1"],
        "customer_state": ["SP"],
        "region": ["Southeast"]
    })

    campaigns = [
        {
            "campaign_id": "EARLIER",
            "start": "2024-01-01",
            "end": "2024-01-31",
            "priority": 5,
            "target_states": ["SP"],
            "target_regions": [],
            "categories": ["ALL"]
        },
        {
            "campaign_id": "LATER",
            "start": "2024-01-10",
            "end": "2024-01-31",
            "priority": 5,
            "target_states": ["SP"],
            "target_regions": [],
            "categories": ["ALL"]
        }
    ]

    result = transform.attribute_campaigns(
        items, orders, customers, campaigns
    )

    assert result.loc[0, "campaign_id"] == "LATER"

def test_r18_region_campaign_not_matched_when_region_unavailable():
    items = pd.DataFrame({
        "order_id": ["O1", "O2"],
        "category_name": ["health_beauty", "health_beauty"]
    })

    orders = pd.DataFrame({
        "order_id": ["O1", "O2"],
        "customer_id": ["C1", "C2"],
        "order_purchase_timestamp": [
            "2018-05-10",
            "2018-05-10"
        ]
    })

    customers = pd.DataFrame({
        "customer_id": ["C1", "C2"],
        "customer_state": ["SP", "RJ"],
        "region": [None, None]
    })

    campaigns = [
        {
            "campaign_id": "C005",
            "start": "2018-05-07",
            "end": "2018-05-13",
            "priority": 2,
            "target_states": [],
            "target_regions": ["Sul"],
            "categories": ["health_beauty"]
        },
        {
            "campaign_id": "SP_ONLY",
            "start": "2018-05-01",
            "end": "2018-05-13",
            "priority": 2,
            "target_states": ["SP"],
            "target_regions": [],
            "categories": ["ALL"]
        }
    ]

    result = transform.attribute_campaigns(
        items, orders, customers, campaigns
    )

    # State-based matching must continue to work.
    assert result.loc[0, "campaign_id"] == "SP_ONLY"

    # Missing region must never match the South campaign.
    assert pd.isna(result.loc[1, "campaign_id"])

def enrich_customers_with_ibge(customers):
    # Get cached IBGE mapping and availability status
    state_mapping, ibge_available = get_ibge_enrichment_status()

    if ibge_available:
        enriched = enrich_state_region(
            customers,
            state_mapping,
            "customer_state"
        )

        print("\nIBGE state-region enrichment completed!")
        print("Customer regions:")
        print(enriched["region"].value_counts(dropna=False))

        return enriched, True

    # IBGE unavailable: preserve customer data
    # and leave region unknown instead of guessing.
    customers = customers.copy()
    customers["region"] = None

    return customers, False
def test_ibge_enrichment_succeeds_when_api_is_available(monkeypatch):
    customers = pd.DataFrame({
        "customer_id": ["C1"],
        "customer_state": ["SP"]
    })

    state_mapping = pd.DataFrame({
        "state_code": ["SP"],
        "state_name": ["São Paulo"],
        "region": ["Sudeste"]
    })

    monkeypatch.setattr(
        load_facts,
        "get_state_region_mapping",
        lambda: state_mapping
    )

    result, available = load_facts.enrich_customers_with_ibge(customers)

    assert available is True
    assert result.loc[0, "region"] == "Sudeste"

def test_ibge_fallback_preserves_customer_data_when_api_fails(monkeypatch):
    customers = pd.DataFrame({
        "customer_id": ["C1"],
        "customer_state": ["SP"],
        "customer_zip_code_prefix": [12345]
    })

    calls = {"count": 0}

    def fail_ibge():
        calls["count"] += 1
        raise RuntimeError("IBGE unavailable")

    monkeypatch.setattr(
        load_facts,
        "get_state_region_mapping",
        fail_ibge
    )

    load_facts.get_ibge_enrichment_status.cache_clear()

    result, available = load_facts.enrich_customers_with_ibge(customers)

    assert available is False
    assert result.loc[0, "customer_state"] == "SP"
    assert result.loc[0, "customer_zip_code_prefix"] == 12345
    assert pd.isna(result.loc[0, "region"])

    # Second call should reuse the cached failure.
    load_facts.enrich_customers_with_ibge(customers)
    assert calls["count"] == 1
