from pathlib import Path
import pandas as pd
import numpy as np
from pipeline.holidays import get_holiday_dates
from pipeline.external_apis import get_brl_usd_rates, convert_brl_to_usd

from pipeline.internal_data import get_clean_internal_data

DATA_DIR = Path("data/input")


def build_customer_dimension(orders, customers):
    # R1: Use customer_unique_id as the real customer identity.

    customer_orders = orders.merge(
        customers[["customer_id", "customer_unique_id", "customer_state"]],
        on="customer_id",
        how="left"
    )

    customer_orders["order_purchase_timestamp"] = pd.to_datetime(
        customer_orders["order_purchase_timestamp"],
        errors="coerce"
    )

    customer_orders = customer_orders.sort_values(
        "order_purchase_timestamp"
    )

    customer_dimension = (
        customer_orders
        .drop_duplicates(subset="customer_unique_id", keep="first")
        [["customer_unique_id", "customer_state"]]
        .rename(columns={"customer_state": "home_state"})
        .reset_index(drop=True)
    )

    return customer_dimension

def apply_revenue_eligibility(orders):
    # R2: Keep every order for data-quality reporting.
    # Only delivered orders are eligible for revenue and commission.
    # Canceled and unavailable orders remain in the dataset but are ineligible.

    processed_orders = orders.copy()

    processed_orders["is_revenue_eligible"] = (
        processed_orders["order_status"] == "delivered"
    ).astype(int)

    return processed_orders


def calculate_order_revenue(order_items, orders):
    # Only delivered orders are eligible for revenue.
    delivered_orders = orders.loc[
        orders["order_status"] == "delivered",
        ["order_id"]
    ]

    eligible_items = order_items.merge(
        delivered_orders,
        on="order_id",
        how="inner"
    )

    order_revenue = (
        eligible_items
        .groupby("order_id", as_index=False)
        .agg(
            item_revenue=("price", "sum"),
            freight_total=("freight_value", "sum")
        )
    )

    order_revenue["total_order_value"] = (
        order_revenue["item_revenue"]
        + order_revenue["freight_total"]
    )

    return order_revenue
def join_revenue_with_orders(order_revenue, orders):
    order_summary = order_revenue.merge(
        orders[
            [
                "order_id",
                "order_status",
                "order_purchase_timestamp",
                "order_approved_at"
            ]
        ],
        on="order_id",
        how="left"
    )

    order_summary.rename(
        columns={
            "order_purchase_timestamp": "order_date"
        },
        inplace=True
    )

    # R6: Use approval date; fall back to purchase date.
    order_summary["fx_date"] = (
        order_summary["order_approved_at"]
        .fillna(order_summary["order_date"])
    )

    return order_summary
def add_usd_revenue(order_summary):
    result = order_summary.copy()

    rates = get_brl_usd_rates("2016-08-28", "2018-10-17")

    # R6: Convert using approval date, falling back to purchase date.
    result = convert_brl_to_usd(
        result, "item_revenue", "fx_date", rates
    )

    result = convert_brl_to_usd(
        result, "freight_total", "fx_date", rates
    )

    result["total_order_value_usd"] = (
        result["item_revenue_usd"] + result["freight_total_usd"]
    )

    return result

def calculate_seller_revenue(order_items):
    seller_revenue = (
        order_items
        .groupby("seller_id", as_index=False)
        .agg(
            item_revenue=("price", "sum"),
            freight_total=("freight_value", "sum")
        )
    )

    seller_revenue["total_order_value"] = (
        seller_revenue["item_revenue"] +
        seller_revenue["freight_total"]
    )

    return seller_revenue

def calculate_eligible_seller_revenue(order_items, orders):
    # Keep only delivered orders
    delivered_orders = orders[
        orders["order_status"] == "delivered"
    ][["order_id"]]

    # Keep order items belonging to delivered orders
    eligible_items = order_items.merge(
        delivered_orders,
        on="order_id",
        how="inner"
    )

    # Calculate revenue for each seller
    seller_revenue = (
        eligible_items
        .groupby("seller_id", as_index=False)
        .agg(
            item_revenue=("price", "sum"),
            freight_total=("freight_value", "sum")
        )
    )

    seller_revenue["total_order_value"] = (
        seller_revenue["item_revenue"]
        + seller_revenue["freight_total"]
    )

    return seller_revenue


def calculate_seller_monthly_revenue(order_items, orders):
    # Keep only delivered orders and their purchase dates
    delivered_orders = orders[
        orders["order_status"] == "delivered"
    ][["order_id", "order_purchase_timestamp"]].copy()

    delivered_orders["order_purchase_timestamp"] = pd.to_datetime(
        delivered_orders["order_purchase_timestamp"]
    )

    # Join eligible order items with order dates
    eligible_items = order_items.merge(
        delivered_orders,
        on="order_id",
        how="inner"
    )

    # Extract calendar month
    eligible_items["order_month"] = (
        eligible_items["order_purchase_timestamp"].dt.to_period("M")
    )

    # R12: Sum item price only (exclude freight)
    monthly_revenue = (
        eligible_items
        .groupby(["seller_id", "order_month"], as_index=False)
        .agg(
            monthly_revenue=("price", "sum")
        )
    )

    return monthly_revenue


def assign_seller_tiers(monthly_revenue):
    # Copy previous month's revenue
    previous_month = monthly_revenue.copy()

    # Shift each month's revenue to the following month
    previous_month["order_month"] = (
        previous_month["order_month"] + 1
    )

    previous_month.rename(
        columns={
            "monthly_revenue": "previous_month_revenue"
        },
        inplace=True
    )

    # Match previous month's revenue to each seller's current month
    result = monthly_revenue[["seller_id", "order_month"]].merge(
        previous_month,
        on=["seller_id", "order_month"],
        how="left"
    )

    # No previous month's sales means zero revenue
    result["previous_month_revenue"] = (
        result["previous_month_revenue"].fillna(0)
    )

    # Apply R12 tier rules
    result["seller_tier"] = "Bronze"

    result.loc[
        result["previous_month_revenue"].between(5000, 20000),
        "seller_tier"
    ] = "Silver"

    result.loc[
        result["previous_month_revenue"] > 20000,
        "seller_tier"
    ] = "Gold"

    return result

def calculate_item_commission(order_items, orders, products, seller_tiers, commission_rates, category_overrides, fx_rates):
    # Start with order items and attach order details
    result = order_items.merge(
    orders[[
        "order_id",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_status"
    ]],
    on="order_id",
    how="left"
    )

    # Keep only delivered orders
    result = result[
        result["order_status"] == "delivered"
    ].copy()

    # Convert purchase timestamp to date
    result["order_purchase_timestamp"] = pd.to_datetime(
        result["order_purchase_timestamp"]
    )

    result["order_approved_at"] = pd.to_datetime(
        result["order_approved_at"],
        errors="coerce"
    )

    # Use approval date; fall back to purchase date if approval is missing
    result["fx_transaction_date"] = result["order_approved_at"].fillna(
        result["order_purchase_timestamp"]
    )

    # Attach English product categories
    internal = get_clean_internal_data()

    result = resolve_item_categories(
        result,
        products,
        pd.read_csv(DATA_DIR / "product_category_name_translation.csv"),
        internal["translation_patch"]
    )

    # Attach seller tier for the order month
    result["order_month"] = (
        result["order_purchase_timestamp"].dt.to_period("M")
    )

    result = result.merge(
        seller_tiers[["seller_id", "order_month", "seller_tier"]],
        on=["seller_id", "order_month"],
        how="left"
    )

    # Convert commission effective dates
    commission_rates = commission_rates.copy()
    category_overrides = category_overrides.copy()

    for df in [commission_rates, category_overrides]:
        df["effective_from"] = pd.to_datetime(df["effective_from"])
        df["effective_to"] = pd.to_datetime(df["effective_to"])

    # Initialize commission rate
    result["commission_rate"] = None

    # Match active category overrides first
    for _, override in category_overrides.iterrows():
        mask = (
            (result["product_category_name_english"] == override["category_name_en"])
            & (result["order_purchase_timestamp"] >= override["effective_from"])
            & (
                result["order_purchase_timestamp"].dt.normalize() <= override["effective_to"]
                if pd.notna(override["effective_to"])
                else True
            )
        )

        result.loc[mask, "commission_rate"] = override["fixed_rate"]

    # Apply tier rates where no category override applies
    for _, rate in commission_rates.iterrows():
        mask = (
            (result["seller_tier"] == rate["tier"])
            & (result["order_purchase_timestamp"] >= rate["effective_from"])
            & (
                result["order_purchase_timestamp"].dt.normalize() <= rate["effective_to"]
                if pd.notna(rate["effective_to"])
                else True
            )
            & result["commission_rate"].isna()
        )

        result.loc[mask, "commission_rate"] = rate["rate"]

    # Item gross revenue includes price and freight
    result["item_gross_brl"] = (
        result["price"] + result["freight_value"]
    )

    # Commission is calculated on item price only, not freight
    result["commission_brl"] = (
        result["price"] * result["commission_rate"]
    )

    # R6: Convert item gross and commission to USD using the applicable FX rate
    result = convert_brl_to_usd(
        result,
        amount_col="item_gross_brl",
        date_col="fx_transaction_date",
        rates=fx_rates
    )

    # Keep the actual FX rate and date used
    result = result.rename(columns={
        "rate": "fx_rate",
        "rate_date": "fx_rate_date",
        "item_gross_brl_usd": "item_gross_usd"
    })

    # Use the same FX rate for commission conversion
    result["commission_usd"] = result["commission_brl"] * result["fx_rate"]

    return result

def clean_order_reviews(reviews):
    # R14: Convert review answer timestamp to datetime
    result = reviews.copy()

    result["review_answer_timestamp"] = pd.to_datetime(
        result["review_answer_timestamp"],
        errors="coerce"
    )

    # Sort latest review first
    result = result.sort_values(
        "review_answer_timestamp",
        ascending=False
    )

    # Keep only the latest review for each order
    result = result.drop_duplicates(
        subset="order_id",
        keep="first"
    )

    return result

def attribute_reviews_to_sellers(order_items, cleaned_reviews):
    # Get unique seller-order combinations
    seller_orders = order_items[
        ["order_id", "seller_id"]
    ].drop_duplicates()

    # Attach the latest review to each seller
    result = seller_orders.merge(
       cleaned_reviews[
         ["order_id", "review_score", "review_answer_timestamp"]
    ],
        on="order_id",
        how="left"
    )

    return result

def clean_geolocation(geolocation):
    result = geolocation.copy()

    # Keep only coordinates within Brazil's bounding box
    result = result[
        result["geolocation_lat"].between(-33.75, 5.27)
        & result["geolocation_lng"].between(-73.99, -34.79)
    ]

    # Calculate median coordinates for each ZIP-code prefix
    result = (
        result.groupby("geolocation_zip_code_prefix")
        .agg(
            latitude=("geolocation_lat", "median"),
            longitude=("geolocation_lng", "median")
        )
        .reset_index()
    )

    return result

def calculate_delivery_distance(order_items, orders, customers, sellers, geolocation):
    result = order_items.copy()

    # Get customer_id from orders
    result = result.merge(
        orders[["order_id", "customer_id"]],
        on="order_id",
        how="left"
    )

    # Attach customer ZIP prefix
    result = result.merge(
        customers[["customer_id", "customer_zip_code_prefix"]],
        on="customer_id",
        how="left"
    )

    # Attach seller ZIP prefix
    result = result.merge(
        sellers[["seller_id", "seller_zip_code_prefix"]],
        on="seller_id",
        how="left"
    )

    # Rename geolocation columns for customer and seller
    customer_geo = geolocation.rename(columns={
        "geolocation_zip_code_prefix": "customer_zip_code_prefix",
        "latitude": "customer_lat",
        "longitude": "customer_lng"
    })

    seller_geo = geolocation.rename(columns={
        "geolocation_zip_code_prefix": "seller_zip_code_prefix",
        "latitude": "seller_lat",
        "longitude": "seller_lng"
    })

    result = result.merge(customer_geo, on="customer_zip_code_prefix", how="left")
    result = result.merge(seller_geo, on="seller_zip_code_prefix", how="left")

    # Calculate Haversine distance
    lat1 = np.radians(result["customer_lat"])
    lon1 = np.radians(result["customer_lng"])
    lat2 = np.radians(result["seller_lat"])
    lon2 = np.radians(result["seller_lng"])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    )

    result["distance_km"] = 6371 * 2 * np.arcsin(np.sqrt(a))

    return result

def enrich_state_region(data, state_mapping, state_column):
    result = data.copy()

    result = result.merge(
        state_mapping,
        left_on=state_column,
        right_on="state_code",
        how="left"
    )

    result = result.drop(columns=["state_code"])

    return result

def parse_campaign_date(value, date_format=None):
    # UTC timestamps ending with Z
    if isinstance(value, str) and value.endswith("Z"):
        return (
            pd.to_datetime(value, utc=True)
            .tz_convert("America/Sao_Paulo")
            .tz_localize(None)
        )

    # DD/MM/YYYY format
    if date_format == "DD/MM/YYYY":
        return pd.to_datetime(value, format="%d/%m/%Y")

    # Normal YYYY-MM-DD dates
    return pd.to_datetime(value)

def attribute_campaigns(item_data, orders, customers, campaigns):
    result = item_data.copy()

    # Attach purchase timestamp and customer ID
    result = result.merge(
        orders[[
            "order_id",
            "customer_id",
            "order_purchase_timestamp"
        ]],
        on="order_id",
        how="left"
    )

    # Attach customer state and region (region may be unavailable)
    customer_columns = ["customer_id", "customer_state"]

    if "region" in customers.columns:
        customer_columns.append("region")

    result = result.merge(
        customers[customer_columns],
        on="customer_id",
        how="left"
    )

    if "region" not in result.columns:
        result["region"] = None

    result["order_purchase_timestamp"] = pd.to_datetime(
        result["order_purchase_timestamp"],
        errors="coerce"
    )
    result["campaign_id"] = None

    # Prepare campaign dates
    prepared_campaigns = []

    for campaign in campaigns:
        start = parse_campaign_date(
            campaign["start"],
            campaign.get("date_format")
        )

        end = parse_campaign_date(
            campaign["end"],
            campaign.get("date_format")
        )

        # Date-only end dates include the entire day
        if "T" not in campaign["end"]:
            end = (
                end
                + pd.Timedelta(days=1)
                - pd.Timedelta(microseconds=1)
            )

        prepared_campaigns.append({
            **campaign,
            "start_date": start,
            "end_date": end
        })

    # Match each item against campaigns
    for index, row in result.iterrows():
        matches = []

        for campaign in prepared_campaigns:
            # Check campaign date
            if pd.isna(row["order_purchase_timestamp"]):
                continue

            if not (
                campaign["start_date"]
                <= row["order_purchase_timestamp"]
                <= campaign["end_date"]
            ):
                continue

            # Check state or region
            target_states = campaign.get("target_states", [])
            target_regions = campaign.get("target_regions", [])

            state_match = (
                "ALL" in target_states
                or row["customer_state"] in target_states
            )

            region_match = (
                "ALL" in target_regions
                or row["region"] in target_regions
            )

            if not (state_match or region_match):
                continue

            # Check category
            categories = campaign.get("categories", [])

            category_match = (
                "ALL" in categories
                or row["category_name"] in categories
            )

            if not category_match:
                continue

            matches.append(campaign)

        # Highest priority wins; later start breaks ties
        if matches:
            selected = sorted(
                matches,
                key=lambda x: (
                    x["priority"],
                    x["start_date"]
                ),
                reverse=True
            )[0]

            result.at[index, "campaign_id"] = selected["campaign_id"]

    return result

def check_state_mapping_coverage(data, state_column, state_mapping):
    dataset_states = set(data[state_column].dropna().unique())
    mapped_states = set(state_mapping["state_code"].dropna().unique())

    missing_states = dataset_states - mapped_states

    return {
        "total_states": len(dataset_states),
        "mapped_states": len(dataset_states & mapped_states),
        "missing_states": sorted(missing_states)
    }

def build_r16_issues(distance_data):
    missing = distance_data[
        distance_data["distance_km"].isna()
    ]

    issues = []

    for _, row in missing.iterrows():
        issues.append({
            "rule_id": "R16",
            "order_id": row["order_id"],
            "seller_id": row["seller_id"],
            "issue_type": "missing_geolocation_coordinates",
            "description": "Customer or seller ZIP prefix has no matching coordinates"
        })

    return pd.DataFrame(issues)

def build_r6_issues(item_data):

    # Only consider items for which financial calculations were performed
    eligible_items = item_data[
        item_data["item_gross_brl"].notna()
    ]

    # Find eligible items with missing FX rates
    missing = eligible_items[
        eligible_items["fx_rate"].isna()
    ]

    issues = []

    for _, row in missing.iterrows():
        issues.append({
            "rule_id": "R6",
            "order_id": row["order_id"],
            "order_item_id": row["order_item_id"],
            "issue_type": "missing_fx_rate",
            "description": (
                "No applicable FX rate available on or before "
                "the transaction date"
            )
        })

    return pd.DataFrame(issues)

def resolve_item_categories(
    order_items,
    products,
    kaggle_translation,
    translation_patch
):
    # Attach Portuguese product category to each order item
    result = order_items.merge(
        products[["product_id", "product_category_name"]],
        on="product_id",
        how="left",
        validate="many_to_one"
    )

    # Normalize category names for matching
    result["product_category_name"] = (
        result["product_category_name"]
        .str.strip()
        .str.lower()
    )

    kaggle = kaggle_translation.copy()
    patch = translation_patch.copy()

    for df in [kaggle, patch]:
        df["product_category_name"] = (
            df["product_category_name"].str.strip().str.lower()
        )
        df["product_category_name_english"] = (
            df["product_category_name_english"]
            .str.strip()
            .str.lower()
        )

    # Build translation dictionaries
    kaggle_map = dict(zip(
        kaggle["product_category_name"],
        kaggle["product_category_name_english"]
    ))

    patch_map = dict(zip(
        patch["product_category_name"],
        patch["product_category_name_english"]
    ))

    # Apply R8 priority: patch first, then Kaggle
    result["product_category_name_english"] = (
        result["product_category_name"].map(patch_map)
        .fillna(result["product_category_name"].map(kaggle_map))
    )

    # Keep missing and untranslated categories distinguishable
    result.loc[
        result["product_category_name"].isna(),
        "product_category_name_english"
    ] = "uncategorized"

    result.loc[
        result["product_category_name"].notna()
        & result["product_category_name_english"].isna(),
        "product_category_name_english"
    ] = "unknown"

    return result


def prepare_delivery_metrics(orders):
    """Prepare delivered orders for delivery and lead-time metrics."""
    result = orders.copy()

    result["order_delivered_customer_date"] = pd.to_datetime(
        result["order_delivered_customer_date"], errors="coerce"
    )
    result["order_approved_at"] = pd.to_datetime(
        result["order_approved_at"], errors="coerce"
    )
    result["order_estimated_delivery_date"] = pd.to_datetime(
        result["order_estimated_delivery_date"], errors="coerce"
    )

    # R3: Identify delivered orders with missing delivery dates
    # before excluding them from delivery metrics.
    missing_delivery_mask = (
        (result["order_status"] == "delivered")
        & result["order_delivered_customer_date"].isna()
    )

    missing_delivery_orders = result.loc[missing_delivery_mask].copy()

    print(
        "R3 — Delivered orders missing delivery dates:",
        len(missing_delivery_orders)
    )

    # Delivery metrics require delivered orders with a delivery timestamp.
    result = result[
        (result["order_status"] == "delivered")
        & result["order_delivered_customer_date"].notna()
    ].copy()

    # Add the customer's state for state-specific holiday calculations.
    customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")

    customer_states = customers[
        ["customer_id", "customer_state"]
    ].drop_duplicates(subset=["customer_id"])

    result = result.merge(
        customer_states,
        on="customer_id",
        how="left",
        validate="many_to_one"
    )

    return result
def calculate_on_time_delivery(delivery_orders):
    # R10: Compare delivery dates, not timestamps.
    delivery_orders = delivery_orders.copy()

    delivery_orders["order_delivered_customer_date"] = pd.to_datetime(
        delivery_orders["order_delivered_customer_date"],
        errors="coerce"
    )

    delivery_orders["order_estimated_delivery_date"] = pd.to_datetime(
        delivery_orders["order_estimated_delivery_date"],
        errors="coerce"
    )

    delivery_orders["actual_delivery_date"] = (
        delivery_orders["order_delivered_customer_date"].dt.normalize()
    )

    delivery_orders["estimated_delivery_date"] = (
        delivery_orders["order_estimated_delivery_date"].dt.normalize()
    )

    delivery_orders["is_on_time"] = (
        delivery_orders["actual_delivery_date"]
        <= delivery_orders["estimated_delivery_date"]
    ).astype("boolean")

    delivery_orders.loc[
        delivery_orders["order_delivered_customer_date"].isna(),
        "is_on_time"
    ] = pd.NA

    return delivery_orders

def calculate_calendar_lead_days(delivery_orders):
    # Prepare dates for the later R9 business-day calculation.
    result = delivery_orders.copy()

    result["approval_date"] = pd.to_datetime(
        result["order_approved_at"], errors="coerce"
    ).dt.normalize()

    result["delivery_date"] = pd.to_datetime(
        result["order_delivered_customer_date"], errors="coerce"
    ).dt.normalize()

    result["calendar_lead_days"] = (
        result["delivery_date"] - result["approval_date"]
    ).dt.days

    # R9: Identify why calendar lead time cannot be calculated.
    result["lead_time_issue"] = None

    missing_approval = result["approval_date"].isna()
    missing_delivery = result["delivery_date"].isna()

    delivery_before_approval = (
        result["approval_date"].notna()
        & result["delivery_date"].notna()
        & (result["delivery_date"] < result["approval_date"])
    )

    result.loc[missing_approval, "lead_time_issue"] = (
        "missing_approval_date"
    )

    result.loc[missing_delivery, "lead_time_issue"] = (
        "missing_delivery_date"
    )

    result.loc[delivery_before_approval, "lead_time_issue"] = (
        "delivery_before_approval"
    )

    print("\nR9 — Lead-time data-quality checks")
    print("Missing approval dates:",
          (result["lead_time_issue"] == "missing_approval_date").sum())
    print("Missing delivery dates:",
          (result["lead_time_issue"] == "missing_delivery_date").sum())
    print("Delivery before approval:",
          (result["lead_time_issue"] == "delivery_before_approval").sum())

    # R9: Collect orders with lead-time data-quality issues.
    r9_issues = result.loc[
        result["lead_time_issue"].notna(),
        ["order_id", "lead_time_issue"]
    ].copy()

    print("\nR9 — Affected orders (first 10):")
    print(r9_issues.head(10))

    print("\nR9 — Total affected orders:", len(r9_issues))

    return result

def build_r9_data_quality_records(lead_time_results, run_id):
    """Build structured data-quality records for R9 lead-time issues."""
    issues = lead_time_results.loc[
        lead_time_results["lead_time_issue"].notna()
    ].copy()

    if issues.empty:
        return pd.DataFrame(
            columns=[
                "issue_id",
                "rule_id",
                "entity_type",
                "entity_id",
                "issue_type",
                "details",
                "detected_at",
                "run_id",
            ]
        )

    issues["issue_id"] = [
        f"R9-{i:04d}" for i in range(1, len(issues) + 1)
    ]
    issues["rule_id"] = "R9"
    issues["entity_type"] = "order"
    issues["entity_id"] = issues["order_id"]
    issues["issue_type"] = issues["lead_time_issue"]
    issues["details"] = issues["lead_time_issue"].map({
        "missing_approval_date": "Approval timestamp is missing.",
        "missing_delivery_date": "Customer delivery timestamp is missing.",
        "delivery_before_approval": (
            "Customer delivery date is earlier than approval date."
        ),
    })
    issues["detected_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    issues["run_id"] = run_id

    return issues[
        [
            "issue_id",
            "rule_id",
            "entity_type",
            "entity_id",
            "issue_type",
            "details",
            "detected_at",
            "run_id",
        ]
    ].reset_index(drop=True)

def build_r3_data_quality_records(missing_delivery, run_id):
    """Build structured data-quality records for R3 issues."""
    issues = missing_delivery.copy()

    columns = [
        "issue_id",
        "rule_id",
        "entity_type",
        "entity_id",
        "issue_type",
        "details",
        "detected_at",
        "run_id",
    ]

    if issues.empty:
        return pd.DataFrame(columns=columns)

    issues["issue_id"] = [
        f"R3-{i:04d}" for i in range(1, len(issues) + 1)
    ]
    issues["rule_id"] = "R3"
    issues["entity_type"] = "order"
    issues["entity_id"] = issues["order_id"]
    issues["issue_type"] = "missing_delivery_timestamp"
    issues["details"] = (
        "Order is marked delivered but the customer delivery timestamp is missing."
    )
    issues["detected_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    issues["run_id"] = run_id

    return issues[columns].reset_index(drop=True)

    # Combine R3 and R9 data-quality records.
    data_quality = pd.concat(
        [r3_data_quality, r9_data_quality],
        ignore_index=True
    )

    print("\nCombined Data-Quality Records")
    print("Total issues:", len(data_quality))
    print("\nIssues by rule:")
    print(data_quality["rule_id"].value_counts())
    print("\nDuplicate issue IDs:", data_quality["issue_id"].duplicated().sum())
    print("\nData-quality table preview:")
    print(data_quality.head())

    # Save the combined data-quality table.
    from pathlib import Path

    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "data_quality_issues.csv"
    data_quality.to_csv(output_file, index=False)

    print(f"\nData-quality table saved to: {output_file}")

def build_internal_data_quality_records(internal_issues, run_id):
    """Convert internal cleaning issues into the common data-quality schema."""

    columns = [
        "issue_id",
        "rule_id",
        "entity_type",
        "entity_id",
        "issue_type",
        "details",
        "detected_at",
        "run_id",
    ]

    if not internal_issues:
        return pd.DataFrame(columns=columns)

    records = []
    detected_at = pd.Timestamp.now(tz="UTC").isoformat()

    for index, issue in enumerate(internal_issues, start=1):
        records.append({
            "issue_id": f"INTERNAL-{index:04d}",
            "rule_id": "INTERNAL",
            "entity_type": "source_record",
            "entity_id": (
                f'{issue["source_file"]}:row_{issue["row_number"]}'
            ),
            "issue_type": "internal_data_cleaning",
            "details": (
                f'Reason: {issue["reason"]}; '
                f'original_value={issue["original_value"]!r}; '
                f'corrected_value={issue["corrected_value"]!r}'
            ),
            "detected_at": detected_at,
            "run_id": run_id,
        })

    return pd.DataFrame(records, columns=columns)


def calculate_weekday_lead_days(lead_time_results):
    """
    Calculate business-day lead time, excluding weekends and
    applicable Brazilian public holidays.

    The approval date is excluded; the delivery date is included
    when it is a business day.
    """
    result = lead_time_results.copy()

    holiday_cache = {}

    def count_business_days(row):
        approval_date = row["approval_date"]
        delivery_date = row["delivery_date"]
        state = row.get("customer_state")

        if pd.isna(approval_date) or pd.isna(delivery_date):
            return None

        if delivery_date < approval_date:
            return None

        start_year = approval_date.year
        end_year = delivery_date.year

        # Fetch holiday dates once per year and state for this run.
        holiday_dates = set()

        for year in range(start_year, end_year + 1):
            cache_key = (year, state)

            if cache_key not in holiday_cache:
                holiday_cache[cache_key] = get_holiday_dates(
                    year,
                    state=state
                )

            holiday_dates.update(holiday_cache[cache_key])

        business_dates = pd.date_range(
            start=approval_date.normalize() + pd.Timedelta(days=1),
            end=delivery_date.normalize(),
            freq="B"
        )

        return sum(
            date.strftime("%Y-%m-%d") not in holiday_dates
            for date in business_dates
        )

    result["weekday_lead_days"] = result.apply(
        count_business_days,
        axis=1
    )

    return result


def classify_seller_delivery(order_items, orders):
    # Keep only the columns needed from orders
    order_data = orders[[
        "order_id",
        "order_status",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date"
    ]].copy()

    # Convert timestamps
    date_columns = [
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date"
    ]

    for column in date_columns:
        order_data[column] = pd.to_datetime(
            order_data[column],
            errors="coerce"
        )

    # Get the earliest shipping deadline per seller per order
    seller_orders = (
        order_items
        .groupby(["order_id", "seller_id"], as_index=False)
        .agg(
            earliest_shipping_limit=("shipping_limit_date", "min")
        )
    )

    seller_orders["earliest_shipping_limit"] = pd.to_datetime(
        seller_orders["earliest_shipping_limit"],
        errors="coerce"
    )

    # Attach order delivery information
    result = seller_orders.merge(
        order_data,
        on="order_id",
        how="left"
    )

    # Keep only delivered orders with valid delivery timestamps
    result = result[
        (result["order_status"] == "delivered")
        & (result["order_delivered_customer_date"].notna())
        & (result["order_delivered_carrier_date"].notna())
    ].copy()

    # Determine seller responsibility
    result["delivery_responsibility"] = "on_time"

    seller_late = (
        result["order_delivered_carrier_date"].notna()
        & result["earliest_shipping_limit"].notna()
        & (
            result["order_delivered_carrier_date"]
            > result["earliest_shipping_limit"]
        )
    )

    order_late = (
        result["order_delivered_customer_date"].notna()
        & result["order_estimated_delivery_date"].notna()
        & (
            result["order_delivered_customer_date"].dt.normalize()
            > result["order_estimated_delivery_date"].dt.normalize()
        )
    )

    result.loc[seller_late, "delivery_responsibility"] = "seller_late"

    result.loc[
        ~seller_late & order_late,
        "delivery_responsibility"
    ] = "carrier_late"

    return result

def calculate_payment_reconciliation(order_items, order_payments):

    # Calculate item gross: price + freight
    item_gross = (
        order_items
        .assign(
            item_gross=(
                order_items["price"]
                + order_items["freight_value"]
            )
        )
        .groupby("order_id", as_index=False)
        .agg(item_gross=("item_gross", "sum"))
    )

    # Calculate total payments and net cash excluding vouchers
    payment_summary = (
        order_payments
        .assign(
            net_cash=lambda df: df["payment_value"].where(
                df["payment_type"] != "voucher", 0
            )
        )
        .groupby("order_id", as_index=False)
        .agg(
            total_payments_brl=("payment_value", "sum"),
            net_cash_paid_brl=("net_cash", "sum")
        )
    )

    # Combine item and payment summaries
    reconciliation = item_gross.merge(
        payment_summary,
        on="order_id",
        how="outer"
    )

    # Treat a missing side as zero for reconciliation
    reconciliation[
        ["item_gross", "total_payments_brl", "net_cash_paid_brl"]
    ] = reconciliation[
        ["item_gross", "total_payments_brl", "net_cash_paid_brl"]
    ].fillna(0)

    # Calculate absolute difference
    reconciliation["payment_difference_brl"] = (
        reconciliation["total_payments_brl"]
        - reconciliation["item_gross"]
    ).abs()

    return reconciliation

def prepare_fact_order_review():
    datasets = load_all_datasets()

    reviews = datasets["reviews"]
    order_items = datasets["order_items"]

    # Keep only the latest review for each order
    cleaned_reviews = clean_order_reviews(reviews)

    # Attribute each review to every seller in that order
    result = attribute_reviews_to_sellers(
        order_items,
        cleaned_reviews
    )

    return result


if __name__ == "__main__":
    internal_data = get_clean_internal_data()

    commission_rates = internal_data["commission_rates"]
    category_overrides = internal_data["category_overrides"]
    translation_patch = internal_data["translation_patch"]
    campaigns = internal_data["campaigns"]
    internal_issues = internal_data["issues"]

    print("\nInternal files loaded successfully!")
    print("Commission rates:", len(commission_rates))
    print("Valid category overrides:", len(category_overrides))
    print("Translation patches:", len(translation_patch))
    print("Campaigns:", len(campaigns))
    print("Internal data-quality issues:", len(internal_issues))


    orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv")

    delivery_orders = prepare_delivery_metrics(orders)

    delivery_results = calculate_on_time_delivery(delivery_orders)

    lead_time_results = calculate_calendar_lead_days(delivery_orders)

    # R9: Build structured data-quality records.
    r9_data_quality = build_r9_data_quality_records(
        lead_time_results,
        run_id="marketplace-pipeline-run-001"
    )

    print("\nR9 — Structured Data-Quality Records")
    print("Total R9 issues:", len(r9_data_quality))
    print(r9_data_quality.head())

    weekday_results = calculate_weekday_lead_days(lead_time_results)
    print("\nR9: Calendar Lead-Time Preparation")
    print("Orders processed:", len(lead_time_results))
    print("Missing approval dates:", lead_time_results["approval_date"].isna().sum())
    print("Missing delivery dates:", lead_time_results["delivery_date"].isna().sum())
    print("Average calendar lead days:", round(
        lead_time_results["calendar_lead_days"].mean(), 2
    ))

    weekday_results = calculate_weekday_lead_days(lead_time_results)

    print("\nR9: Business-Day Lead-Time (excluding weekends and applicable holidays)")
    print(
        "Orders with valid approval and delivery dates:",
        weekday_results["weekday_lead_days"].notna().sum()
    )
    print(
        "Orders with missing lead time:",
        weekday_results["weekday_lead_days"].isna().sum()
    )
    print(
        "Average weekday lead days:",
        round(weekday_results["weekday_lead_days"].mean(), 2)
    )

    print("\nR10: On-Time Delivery")
    print("Orders evaluated:", len(delivery_results))
    print("On-time orders:", delivery_results["is_on_time"].sum())
    print("Late orders:", (~delivery_results["is_on_time"]).sum())
    print(
    "On-time delivery rate (%):",
    round(delivery_results["is_on_time"].mean() * 100, 2)
    )

    print("\nR3: Delivery Metrics Dataset")
    print("Delivered orders:", (orders["order_status"] == "delivered").sum())
    print("Orders included in delivery metrics:", len(delivery_orders))
    print(
        "Orders excluded due to missing delivery date:",
        (orders["order_status"].eq("delivered")
        & orders["order_delivered_customer_date"].isna()).sum()
    )

    
# R3: Find delivered orders with missing delivery timestamps.
    missing_delivery = orders[
        (orders["order_status"] == "delivered")
    & (orders["order_delivered_customer_date"].isna())
    ]

    print("\nR3: Delivered Orders with Missing Delivery Dates")
    print("Number of affected orders:", len(missing_delivery))

    # R3: Build structured data-quality records.
    r3_data_quality = build_r3_data_quality_records(
        missing_delivery,
        run_id="marketplace-pipeline-run-001"
    )

    print("\nR3 — Structured Data-Quality Records")
    print("Total R3 issues:", len(r3_data_quality))
    print(r3_data_quality.head())

    # Convert internal issues into the common data-quality schema.
    internal_data_quality = build_internal_data_quality_records(
    internal_issues,
    run_id="marketplace-pipeline-run-001"
    )

    print("\nInternal Data-Quality Records")
    print("Total internal issues:", len(internal_data_quality))
    print(internal_data_quality.head())

   # Combine R3, R9, and internal data-quality records.
    data_quality = pd.concat(
    [r3_data_quality, r9_data_quality, internal_data_quality],
    ignore_index=True
    )

    print("\nCombined Data-Quality Records")
    print("Total issues:", len(data_quality))

    print("\nIssues by rule:")
    print(data_quality["rule_id"].value_counts())

    print(
    "\nDuplicate issue IDs:",
    data_quality["issue_id"].duplicated().sum()
    )

    print("\nData-quality table preview:")
    print(data_quality.head())

    print("\nCombined Data-Quality Records")
    print("Total issues:", len(data_quality))

    # Save the combined data-quality table.
    from pathlib import Path

    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "data_quality_issues.csv"
    data_quality.to_csv(output_file, index=False)

    print(f"\nData-quality table saved to: {output_file.resolve()}")

    print("\nIssues by rule:")
    print(data_quality["rule_id"].value_counts())

    print(
        "\nDuplicate issue IDs:",
        data_quality["issue_id"].duplicated().sum()
    )

    print("\nData-quality table preview:")
    print(data_quality.head())

    customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")

    customer_dimension = build_customer_dimension(orders, customers)

    print("Customer dimension created successfully!")
    print("Unique customers:", len(customer_dimension))
    print("\nFirst 5 customers:")
    print(customer_dimension.head())

    print(
        "\nDuplicate customer IDs:",
        customer_dimension["customer_unique_id"].duplicated().sum()
    )
    processed_orders = apply_revenue_eligibility(orders)

    print("\nR2: Revenue Eligibility")
    print("Orders in source:", len(orders))
    print("Orders retained:", len(processed_orders))

    print("\nOrders excluded from revenue by status:")
    print(
   	processed_orders.loc[
        processed_orders["order_status"].isin(["canceled", "unavailable"]),
        "order_status"
    ].value_counts()
    )

    print("\nRevenue eligibility:")
    print(processed_orders["is_revenue_eligible"].value_counts())

    order_items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv")

    eligible_seller_revenue = calculate_eligible_seller_revenue(
        order_items, orders
    )

    print("\nEligible Seller Revenue:")
    print(eligible_seller_revenue.head())

    print(
        "\nNumber of sellers with eligible revenue:",
        eligible_seller_revenue["seller_id"].nunique()
    )

    print(
        "Total eligible item revenue:",
        eligible_seller_revenue["item_revenue"].sum()
    )

    print(
        "Total eligible freight:",
        round(eligible_seller_revenue["freight_total"].sum(),2)
    )

    seller_revenue = calculate_seller_revenue(order_items)

    print("\nSeller Revenue:")
    print(seller_revenue.head())

    print("\nNumber of sellers:", seller_revenue["seller_id"].nunique())
    print("Duplicate seller IDs:", seller_revenue["seller_id"].duplicated().sum())

    print("\nTotal seller item revenue:", seller_revenue["item_revenue"].sum())

    order_revenue = calculate_order_revenue(order_items, orders)

    print("\nOrder Revenue:")
    print(order_revenue.head())

    print("\nRevenue Summary:")
    print(order_revenue[["item_revenue", "freight_total", "total_order_value"]].sum())

    print("\nNumber of unique orders:", order_revenue["order_id"].nunique())
    print("Duplicate order IDs:", order_revenue["order_id"].duplicated().sum())

    order_summary = join_revenue_with_orders(order_revenue, orders)

    print("\nOrder Summary:")
    print(order_summary.head())

    print("\nOrder Status Counts:")
    print(order_summary["order_status"].value_counts())

    print(
        "\nMissing Order Status:",
        order_summary["order_status"].isnull().sum()
    )

    order_summary["is_revenue_eligible"] = (
	order_summary["order_status"] == "delivered"
    ).astype(int)

    print("\nOrder Summary with Revenue Eligibility:")
    print(order_summary.head())

    print("\nRevenue Eligibility Counts:")
    print(order_summary["is_revenue_eligible"].value_counts())

    print("\nRevenue by Eligibility:")
    print(
        order_summary.groupby("is_revenue_eligible")[
            ["item_revenue", "freight_total", "total_order_value"]
        ].sum()
    )
