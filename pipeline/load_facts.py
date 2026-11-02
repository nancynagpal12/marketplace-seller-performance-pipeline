import pandas as pd

from functools import lru_cache
from sqlalchemy import text
from pipeline.db import engine
from pipeline.extract import load_all_datasets

from pipeline.transform import (
    calculate_order_revenue,
    join_revenue_with_orders,
    add_usd_revenue,
    calculate_on_time_delivery,
    calculate_seller_monthly_revenue,
    assign_seller_tiers,
    resolve_item_categories,
    calculate_item_commission,
    calculate_delivery_distance,
    clean_geolocation,
    get_clean_internal_data,
    classify_seller_delivery,
    clean_order_reviews,
    attribute_reviews_to_sellers,
    calculate_payment_reconciliation,
    build_r6_issues,
    calculate_calendar_lead_days,
    build_r9_data_quality_records,
    build_r16_issues,
    attribute_campaigns,
    enrich_state_region,
)

from pipeline.external_apis import (
    get_brl_usd_rates,
    get_state_region_mapping
)

@lru_cache(maxsize=1)
def get_ibge_enrichment_status():
    try:
        state_mapping = get_state_region_mapping()
        return state_mapping, True
    except RuntimeError as error:
        print("\nWARNING: IBGE enrichment unavailable.")
        print("Regional campaign attribution cannot be completed.")
        print("Reason:", error)
        return None, False

def enrich_customers_with_ibge(customers):
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

    customers = customers.copy()
    customers["region"] = None

    return customers, False
def prepare_fact_order(start_date=None, end_date=None):
    # Step 1: Load source datasets
    data = load_all_datasets()

    orders = data["orders"]
    order_items = data["order_items"]
    customers = data["customers"]

    order_payments = data["order_payments"]

    # Calculate R5 payment reconciliation
    payment_reconciliation = calculate_payment_reconciliation(
        order_items,
        order_payments
    )

    print("\nPayment reconciliation completed!")
    print("Reconciliation records:", len(payment_reconciliation))
    print(
        "Payment mismatches:",
        (payment_reconciliation["payment_difference_brl"] > 1).sum()
    ) 

    print("Source datasets loaded successfully!")
    print("Orders:", len(orders))
    print("Order items:", len(order_items))
    print("Customers:", len(customers))

    # Step 2: Calculate revenue for delivered orders
    order_revenue = calculate_order_revenue(
        order_items,
        orders
    )

    print("\nOrder revenue calculated!")
    print("Revenue records:", len(order_revenue))
    print(order_revenue.head())

    # Step 3: Join revenue with order details
    order_summary = join_revenue_with_orders(
        order_revenue,
        orders
    )

    print("\nRevenue joined with order details!")
    print("Records:", len(order_summary))
    print(order_summary.head())
    print("\nMissing FX dates:", order_summary["fx_date"].isna().sum())

    # Step 4: Convert BRL revenue into USD
    order_summary = add_usd_revenue(order_summary)

    print("\nUSD conversion completed!")
    print(
        order_summary[
            [
                "order_id",
                "item_revenue",
                "item_revenue_usd",
                "freight_total",
                "freight_total_usd",
                "total_order_value_usd",
                "rate",
                "rate_date"
            ]
        ].head()
    )

    print("\nMissing USD values:",
          order_summary["total_order_value_usd"].isna().sum())

    print("Missing exchange rates:",
          order_summary["rate"].isna().sum())

    print("Missing exchange rate dates:",
          order_summary["rate_date"].isna().sum())

    # Step 5: Calculate on-time delivery
    delivery_data = calculate_on_time_delivery(
        orders.copy()
    )

    print("\nDelivery calculation completed!")
    print(
        delivery_data["is_on_time"].value_counts(
            dropna=False
        )
    )

    # Step 6: Merge revenue and delivery information
    order_summary = order_summary.merge(
        delivery_data[
            ["order_id", "is_on_time"]
        ],
        on="order_id",
        how="left"
    )

    print("\nRevenue and delivery data merged!")
    print("Total records:", len(order_summary))
    print("Duplicate order IDs:",
          order_summary["order_id"].duplicated().sum())
    print("Missing on-time values:",
          order_summary["is_on_time"].isna().sum())

    # Step 7: Add customer information
    order_summary = order_summary.merge(
        orders[["order_id", "customer_id"]],
        on="order_id",
        how="left"
    )

    order_summary = order_summary.merge(
        customers[["customer_id", "customer_unique_id"]],
        on="customer_id",
        how="left"
    )

    print("\nCustomer information added!")
    print("Records:", len(order_summary))
    print("Missing customer IDs:",
          order_summary["customer_unique_id"].isna().sum())
    print("Duplicate order IDs:",
          order_summary["order_id"].duplicated().sum())

    # Step 8: Create base orders
    fact_orders = orders[
        ~orders["order_status"].isin(["canceled", "unavailable"])
    ].copy()

    # Add customer unique ID
    fact_orders = fact_orders.merge(
        customers[["customer_id", "customer_unique_id"]],
        on="customer_id",
        how="left"
    )

    # Add R5 payment reconciliation information
    payment_columns = [
        "order_id",
        "total_payments_brl",
        "net_cash_paid_brl",
        "payment_difference_brl"
    ]

    fact_orders = fact_orders.merge(
        payment_reconciliation[payment_columns],
        on="order_id",
        how="left"
    )

    print("\nPayment reconciliation merged!")
    print("Records:", len(fact_orders))
    print(
        "Missing total payments:",
        fact_orders["total_payments_brl"].isna().sum()
    )
    print(
        "Payment mismatches:",
        (fact_orders["payment_difference_brl"] > 1).sum()
    )

    # Add revenue information
    revenue_columns = [
        "order_id",
        "item_revenue",
        "freight_total",
        "total_order_value",
        "item_revenue_usd",
        "freight_total_usd",
        "total_order_value_usd",
        "rate",
        "rate_date"
    ]

    fact_orders = fact_orders.merge(
        order_summary[revenue_columns],
        on="order_id",
        how="left"
    )

    # Revenue eligibility
    fact_orders["revenue_eligible"] = (
        fact_orders["order_status"] == "delivered"
    ).astype(int)

    # Add on-time delivery information
    fact_orders = fact_orders.merge(
        delivery_data[["order_id", "is_on_time"]],
        on="order_id",
        how="left"
    )

    print("\nFinal fact_order base created!")
    print("Total records:", len(fact_orders))
    print("Duplicate order IDs:",
          fact_orders["order_id"].duplicated().sum())
    print("Missing customer IDs:",
          fact_orders["customer_unique_id"].isna().sum())
    print("\nOrder status counts:")
    print(fact_orders["order_status"].value_counts())
    print("\nRevenue eligibility:")
    print(fact_orders["revenue_eligible"].value_counts())

    # Step 9: Prepare final fact_order columns

    fact_orders["order_revenue_brl"] = (
        fact_orders["total_order_value"]
    )

    fact_orders["order_revenue_usd"] = (
        fact_orders["total_order_value_usd"]
    )

    final_columns = [
        "order_id",
        "customer_unique_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
        "revenue_eligible",
        "order_revenue_brl",
        "order_revenue_usd",
        "total_payments_brl",
        "net_cash_paid_brl",
        "payment_difference_brl",
        "is_on_time"
    ]

    fact_orders = fact_orders[final_columns].copy()

    fact_orders = fact_orders.rename(
        columns={
            "is_on_time": "on_time_delivery"
        }
    )
    # Filter orders by requested purchase date range
    if start_date is not None and end_date is not None:
        fact_orders["order_purchase_timestamp"] = pd.to_datetime(
            fact_orders["order_purchase_timestamp"]
        )

        start_date = pd.Timestamp(start_date)
        end_date = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        fact_orders = fact_orders[
            (fact_orders["order_purchase_timestamp"] >= start_date) &
            (fact_orders["order_purchase_timestamp"] < end_date)
        ].copy()

    print("\nFinal fact_order columns prepared!")
    print(fact_orders.head())

    print("\nFinal shape:", fact_orders.shape)

    print("\nMissing values:")
    print(fact_orders.isna().sum())

    return fact_orders


# Step 10: Load fact_order into MySQL

def load_fact_order(fact_orders):

    # Convert pandas NaN and NaT into Python None
    cleaned = fact_orders.astype(object).where(
        fact_orders.notna(), None
    )

    records = cleaned.to_dict(orient="records")

    query = text("""
        INSERT INTO fact_order (
            order_id,
            customer_unique_id,
            order_status,
            order_purchase_timestamp,
            order_approved_at,
            order_delivered_carrier_date,
            order_delivered_customer_date,
            order_estimated_delivery_date,
            revenue_eligible,
            order_revenue_brl,
            order_revenue_usd,
            total_payments_brl,
            net_cash_paid_brl,
            payment_difference_brl,
            on_time_delivery
        )
        VALUES (
            :order_id,
            :customer_unique_id,
            :order_status,
            :order_purchase_timestamp,
            :order_approved_at,
            :order_delivered_carrier_date,
            :order_delivered_customer_date,
            :order_estimated_delivery_date,
            :revenue_eligible,
            :order_revenue_brl,
            :order_revenue_usd,
            :total_payments_brl,
            :net_cash_paid_brl,
            :payment_difference_brl,
            :on_time_delivery
        )
        ON DUPLICATE KEY UPDATE
            customer_unique_id = VALUES(customer_unique_id),
            order_status = VALUES(order_status),
            order_purchase_timestamp = VALUES(order_purchase_timestamp),
            order_approved_at = VALUES(order_approved_at),
            order_delivered_carrier_date = VALUES(order_delivered_carrier_date),
            order_delivered_customer_date = VALUES(order_delivered_customer_date),
            order_estimated_delivery_date = VALUES(order_estimated_delivery_date),
            revenue_eligible = VALUES(revenue_eligible),
            order_revenue_brl = VALUES(order_revenue_brl),
            order_revenue_usd = VALUES(order_revenue_usd),
            total_payments_brl = VALUES(total_payments_brl),
            net_cash_paid_brl = VALUES(net_cash_paid_brl),
            payment_difference_brl = VALUES(payment_difference_brl),
            on_time_delivery = VALUES(on_time_delivery)
    """)

    with engine.begin() as connection:
        connection.execute(query, records)

    print("\nfact_order loaded successfully!")
    print("Records processed:", len(records))

def prepare_fact_order_item(start_date=None, end_date=None):

    # Step 1: Load source datasets
    data = load_all_datasets()

    orders = data["orders"]
    order_items = data["order_items"]
    products = data["products"]
    customers = data["customers"]
    sellers = data["sellers"]

    # R17: Attempt IBGE state-region enrichment.
    customers, ibge_available = enrich_customers_with_ibge(customers)
    geolocation = data["geolocation"]
    kaggle_translation = data["category_translation"]

    print("Source datasets loaded successfully!")

    # Step 2: Create base item dataset
    fact_items = order_items.merge(
        orders[[
            "order_id",
            "order_status",
            "order_purchase_timestamp"
        ]],        
        on="order_id",
        how="left",
        validate="many_to_one"
    )

    # Exclude canceled and unavailable orders
    fact_items = fact_items[
        ~fact_items["order_status"].isin(
            ["canceled", "unavailable"]
        )
    ].copy()

    print("\nBase item dataset created!")
    print("Total item records:", len(fact_items))
    print("\nOrder status counts:")
    print(fact_items["order_status"].value_counts())

    # Step 3: Resolve product categories (R8)
    internal = get_clean_internal_data()

    fact_items = resolve_item_categories(
        fact_items,
        products,
        kaggle_translation,
        internal["translation_patch"]
    )

    fact_items["category_name"] = (
        fact_items["product_category_name_english"]
    )

    print("\nCategory translation completed!")
    print(
        fact_items["category_name"]
        .value_counts()
        .head(10)
    )

    print(
        "\nMissing categories:",
        fact_items["category_name"].isna().sum()
    )

    # Step 4: Calculate seller monthly revenue and tiers
    monthly_revenue = calculate_seller_monthly_revenue(
        order_items,
        orders
    )

    seller_tiers = assign_seller_tiers(monthly_revenue)

    print("\nSeller tiers calculated!")
    print(seller_tiers["seller_tier"].value_counts())

    # Step 5: Fetch historical BRL to USD rates
    fx_rates = get_brl_usd_rates(
        "2016-09-01",
        "2018-10-31"
    )

    print("\nFX rates retrieved:", len(fx_rates))

    # Step 6: Calculate item commission and USD values
    financial_data = calculate_item_commission(
        order_items,
        orders,
        products,
        seller_tiers,
        internal["commission_rates"],
        internal["category_overrides"],
        fx_rates
    )

    print("\nFinancial calculations completed!")
    print("Financial records:", len(financial_data))

    # Step 7: Merge financial data into base item dataset

    financial_columns = [
        "order_id",
        "order_item_id",
        "item_gross_brl",
        "item_gross_usd",
        "fx_rate",
        "fx_rate_date",
        "fx_transaction_date",
        "commission_rate",
        "commission_brl",
        "commission_usd"
    ]

    fact_items = fact_items.merge(
        financial_data[financial_columns],
        on=["order_id", "order_item_id"],
        how="left",
        validate="one_to_one"
    )

    print("\nFinancial data merged!")

    print("Final item records:", len(fact_items))

    print(
        "Financial records with gross BRL:",
        fact_items["item_gross_brl"].notna().sum()
    )

    print(
        "Non-delivered items with financial values:",
        fact_items.loc[
            fact_items["order_status"] != "delivered",
            "item_gross_brl"
        ].notna().sum()
    )

    # Step 8: Clean geolocation data (R15)
    clean_geo = clean_geolocation(geolocation)

    print("\nGeolocation cleaned!")
    print("ZIP prefixes:", len(clean_geo))

    # Step 9: Calculate delivery distance (R16)
    distance_data = calculate_delivery_distance(
        order_items,
        orders,
        customers,
        sellers,
        clean_geo
    )

    # Keep only the required columns
    distance_columns = [
        "order_id",
        "order_item_id",
        "distance_km"
    ]

    distance_data = distance_data[distance_columns]

    # Merge delivery distance into fact items
    fact_items = fact_items.merge(
        distance_data,
        on=["order_id", "order_item_id"],
        how="left",
        validate="one_to_one"
    )

    print("\nDelivery distance merged!")
    print("Total item records:", len(fact_items))
    print("Missing distances:", fact_items["distance_km"].isna().sum())

    # Step 10: Prepare final fact_order_item columns

    fact_items["price_brl"] = fact_items["price"]
    fact_items["freight_value_brl"] = fact_items["freight_value"]

    final_columns = [
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "category_name",
        "price_brl",
        "freight_value_brl",
        "item_gross_brl",
        "item_gross_usd",
        "fx_rate",
        "fx_rate_date",
        "fx_transaction_date",
        "commission_rate",
        "commission_brl",
        "commission_usd",
        "distance_km",
    ]

    fact_items = fact_items[final_columns].copy()

    # Campaign attribution is pending R17 region enrichment.
    # Step 10: Campaign attribution (R18)

    campaigns = internal["campaigns"]

    fact_items = attribute_campaigns(
        fact_items,
        orders,
        customers,
        campaigns
    )

    print("\nCampaign attribution completed!")
    print("Attributed items:", fact_items["campaign_id"].notna().sum())
    print("Unattributed items:", fact_items["campaign_id"].isna().sum())

    # Filter items using their parent order's purchase date
    if start_date is not None and end_date is not None:
        fact_items["order_purchase_timestamp"] = pd.to_datetime(
            fact_items["order_purchase_timestamp"]
        )

        start_timestamp = pd.Timestamp(start_date)
        end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        fact_items = fact_items[
            (fact_items["order_purchase_timestamp"] >= start_timestamp) &
            (fact_items["order_purchase_timestamp"] < end_timestamp)
        ].copy()

    # Remove temporary purchase timestamp
    fact_items = fact_items.drop(
        columns=["order_purchase_timestamp"]
    )

    print("\nFinal fact_order_item prepared!")
    print("Shape:", fact_items.shape)
    print("\nColumns:", list(fact_items.columns))
    print("\nMissing values:")
    print(fact_items.isna().sum())

    return fact_items

def load_fact_order_item(fact_items):

    # Convert pandas NaN and NaT into Python None
    cleaned = fact_items.astype(object).where(
        fact_items.notna(), None
    )

    records = cleaned.to_dict(orient="records")

    query = text("""
        INSERT INTO fact_order_item (
            order_id,
            order_item_id,
            product_id,
            seller_id,
            category_name,
            price_brl,
            freight_value_brl,
            item_gross_brl,
            item_gross_usd,
            fx_rate,
            fx_rate_date,
            fx_transaction_date,
            commission_rate,
            commission_brl,
            commission_usd,
            distance_km,
            campaign_id
        )
        VALUES (
            :order_id,
            :order_item_id,
            :product_id,
            :seller_id,
            :category_name,
            :price_brl,
            :freight_value_brl,
            :item_gross_brl,
            :item_gross_usd,
            :fx_rate,
            :fx_rate_date,
            :fx_transaction_date,
            :commission_rate,
            :commission_brl,
            :commission_usd,
            :distance_km,
            :campaign_id
        )
        ON DUPLICATE KEY UPDATE
            product_id = VALUES(product_id),
            seller_id = VALUES(seller_id),
            category_name = VALUES(category_name),
            price_brl = VALUES(price_brl),
            freight_value_brl = VALUES(freight_value_brl),
            item_gross_brl = VALUES(item_gross_brl),
            item_gross_usd = VALUES(item_gross_usd),
            fx_rate = VALUES(fx_rate),
            fx_rate_date = VALUES(fx_rate_date),
            fx_transaction_date = VALUES(fx_transaction_date),
            commission_rate = VALUES(commission_rate),
            commission_brl = VALUES(commission_brl),
            commission_usd = VALUES(commission_usd),
            distance_km = VALUES(distance_km),
            campaign_id = VALUES(campaign_id)
    """)

    # Load in batches of 1,000 records
    batch_size = 1000

    with engine.begin() as connection:

        for start in range(0, len(records), batch_size):

            batch = records[start:start + batch_size]

            connection.execute(query, batch)

            print(
                f"Loaded {min(start + batch_size, len(records))}"
                f"/{len(records)} records"
            )

    print("\nfact_order_item loaded successfully!")
    print("Total records processed:", len(records))

def prepare_fact_seller_monthly(start_date=None, end_date=None):

    # Load source datasets
    datasets = load_all_datasets()

    order_items = datasets["order_items"]
    orders = datasets["orders"]

    # Calculate monthly eligible revenue
    monthly_revenue = calculate_seller_monthly_revenue(
        order_items,
        orders
    )

    print("\nMonthly seller revenue calculated!")
    print("Seller-month records:", len(monthly_revenue))

    # Assign tiers using previous month's revenue
    seller_tiers = assign_seller_tiers(monthly_revenue)

    # Combine revenue and seller tiers
    fact_seller_monthly = monthly_revenue.merge(
        seller_tiers[
            ["seller_id", "order_month", "seller_tier"]
        ],
        on=["seller_id", "order_month"],
        how="left",
        validate="one_to_one"
    )

    # Rename revenue column to match MySQL schema
    fact_seller_monthly.rename(
        columns={
            "monthly_revenue": "eligible_revenue_brl"
        },
        inplace=True
    )

    # Convert monthly Period to SQL-compatible date
    fact_seller_monthly["order_month"] = (
        fact_seller_monthly["order_month"]
        .dt.to_timestamp()
        .dt.date
    )

    # Filter only after calculating historical seller tiers (R12)
    if start_date is not None and end_date is not None:
        start_month = pd.Timestamp(start_date).to_period("M")
        end_month = pd.Timestamp(end_date).to_period("M")

        fact_seller_monthly = fact_seller_monthly[
            fact_seller_monthly["order_month"].apply(
                lambda d: start_month <= pd.Timestamp(d).to_period("M") <= end_month
            )
        ].copy()

    # Keep only database columns
    fact_seller_monthly = fact_seller_monthly[
        [
            "seller_id",
            "order_month",
            "eligible_revenue_brl",
            "seller_tier"
        ]
    ]

    print("\nFinal fact_seller_monthly prepared!")
    print("Shape:", fact_seller_monthly.shape)

    print("\nSeller tier counts:")
    print(fact_seller_monthly["seller_tier"].value_counts())

    print("\nMissing values:")
    print(fact_seller_monthly.isnull().sum())

    print(
        "\nDuplicate seller-month keys:",
        fact_seller_monthly.duplicated(
            ["seller_id", "order_month"]
        ).sum()
    )

    return fact_seller_monthly

def load_fact_seller_monthly(fact_seller_monthly):

    # Convert missing values to None
    cleaned = fact_seller_monthly.astype(object).where(
        fact_seller_monthly.notna(), None
    )

    records = cleaned.to_dict(orient="records")

    query = text("""
        INSERT INTO fact_seller_monthly (
            seller_id,
            order_month,
            eligible_revenue_brl,
            seller_tier
        )
        VALUES (
            :seller_id,
            :order_month,
            :eligible_revenue_brl,
            :seller_tier
        )
        ON DUPLICATE KEY UPDATE
            eligible_revenue_brl = VALUES(eligible_revenue_brl),
            seller_tier = VALUES(seller_tier)
    """)

    batch_size = 1000

    with engine.begin() as connection:

        for start in range(0, len(records), batch_size):

            batch = records[start:start + batch_size]

            connection.execute(query, batch)

            print(
                f"Loaded {min(start + batch_size, len(records))}"
                f"/{len(records)} records"
            )

    print("\nfact_seller_monthly loaded successfully!")
    print("Total records processed:", len(records))

def prepare_fact_seller_order_delivery(start_date=None, end_date=None):

    # Load source datasets
    datasets = load_all_datasets()

    order_items = datasets["order_items"]
    orders = datasets["orders"]

    # Apply R11 seller delivery classification
    delivery_data = classify_seller_delivery(
        order_items,
        orders
    )

    # Filter delivery records by parent order purchase date
    if start_date is not None and end_date is not None:
        orders["order_purchase_timestamp"] = pd.to_datetime(
            orders["order_purchase_timestamp"]
        )

        start_timestamp = pd.Timestamp(start_date)
        end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        selected_order_ids = orders.loc[
            (orders["order_purchase_timestamp"] >= start_timestamp) &
            (orders["order_purchase_timestamp"] < end_timestamp),
            "order_id"
        ]

        delivery_data = delivery_data[
            delivery_data["order_id"].isin(selected_order_ids)
        ].copy()

    print("\nSeller delivery classification completed!")
    print("Total records:", len(delivery_data))

    # Rename columns to match MySQL schema
    delivery_data.rename(
        columns={
            "earliest_shipping_limit": "earliest_shipping_limit_date",
            "order_delivered_carrier_date": "carrier_handoff_date",
            "order_delivered_customer_date": "delivered_customer_date",
            "order_estimated_delivery_date": "estimated_delivery_date"
        },
        inplace=True
    )

    # Select database columns
    fact_delivery = delivery_data[
        [
            "order_id",
            "seller_id",
            "earliest_shipping_limit_date",
            "carrier_handoff_date",
            "delivered_customer_date",
            "estimated_delivery_date",
            "delivery_responsibility"
        ]
    ].copy()

    print("\nDelivery responsibility counts:")
    print(fact_delivery["delivery_responsibility"].value_counts())

    print("\nMissing values:")
    print(fact_delivery.isnull().sum())

    print(
        "\nDuplicate order-seller keys:",
        fact_delivery.duplicated(
            ["order_id", "seller_id"]
        ).sum()
    )

    print("\nFinal fact_seller_order_delivery prepared!")
    print("Shape:", fact_delivery.shape)

    return fact_delivery

def load_fact_seller_order_delivery(fact_delivery):

    cleaned = fact_delivery.astype(object).where(
        fact_delivery.notna(), None
    )

    records = cleaned.to_dict(orient="records")

    query = text("""
        INSERT INTO fact_seller_order_delivery (
            order_id,
            seller_id,
            earliest_shipping_limit_date,
            carrier_handoff_date,
            delivered_customer_date,
            estimated_delivery_date,
            delivery_responsibility
        )
        VALUES (
            :order_id,
            :seller_id,
            :earliest_shipping_limit_date,
            :carrier_handoff_date,
            :delivered_customer_date,
            :estimated_delivery_date,
            :delivery_responsibility
        )
        ON DUPLICATE KEY UPDATE
            earliest_shipping_limit_date = VALUES(earliest_shipping_limit_date),
            carrier_handoff_date = VALUES(carrier_handoff_date),
            delivered_customer_date = VALUES(delivered_customer_date),
            estimated_delivery_date = VALUES(estimated_delivery_date),
            delivery_responsibility = VALUES(delivery_responsibility)
    """)

    batch_size = 1000

    with engine.begin() as connection:

        for start in range(0, len(records), batch_size):

            batch = records[start:start + batch_size]

            connection.execute(query, batch)

            print(
                f"Loaded {min(start + batch_size, len(records))}"
                f"/{len(records)} records"
            )

    print("\nfact_seller_order_delivery loaded successfully!")
    print("Total records processed:", len(records))

def prepare_fact_order_review(start_date=None, end_date=None):
    datasets = load_all_datasets()

    reviews = datasets["order_reviews"]
    order_items = datasets["order_items"]
    orders = datasets["orders"]

    # Keep only delivered and other eligible orders
    eligible_orders = orders[
        ~orders["order_status"].isin(
            ["canceled", "unavailable"]
        )
    ]

    # Filter eligible orders by purchase date
    if start_date is not None and end_date is not None:
        eligible_orders["order_purchase_timestamp"] = pd.to_datetime(
            eligible_orders["order_purchase_timestamp"]
        )

        start_timestamp = pd.Timestamp(start_date)
        end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        eligible_orders = eligible_orders[
            (eligible_orders["order_purchase_timestamp"] >= start_timestamp) &
            (eligible_orders["order_purchase_timestamp"] < end_timestamp)
        ].copy()

    eligible_order_ids = eligible_orders["order_id"]

    eligible_items = order_items[
        order_items["order_id"].isin(eligible_order_ids)
    ]

    # Keep the latest review for each order
    cleaned_reviews = clean_order_reviews(reviews)

    # Attribute reviews to every eligible seller
    result = attribute_reviews_to_sellers(
        eligible_items,
        cleaned_reviews
    )

    return result
def load_fact_order_review(df):
    cleaned = df.astype(object).where(
        df.notna(), None
    )

    records = cleaned.to_dict(orient="records")

    query = text("""
        INSERT INTO fact_order_review (
            order_id,
            seller_id,
            review_score,
            review_answer_timestamp
        )
        VALUES (
            :order_id,
            :seller_id,
            :review_score,
            :review_answer_timestamp
        )
        ON DUPLICATE KEY UPDATE
            review_score = VALUES(review_score),
            review_answer_timestamp = VALUES(review_answer_timestamp)
    """)

    batch_size = 1000

    with engine.begin() as connection:
        for i in range(0, len(records), batch_size):
            connection.execute(
                query,
                records[i:i + batch_size]
            )

    print(f"Loaded {len(records)} records into fact_order_review")

def load_payment_mismatch_issues(run_id, start_date=None, end_date=None):

    data = load_all_datasets()

    # Calculate payment reconciliation
    reconciliation = calculate_payment_reconciliation(
        data["order_items"],
        data["order_payments"]
    )

    # Exclude canceled and unavailable orders
    eligible_orders = data["orders"][
        ~data["orders"]["order_status"].isin(
            ["canceled", "unavailable"]
        )
    ].copy()

    if start_date is not None and end_date is not None:
        eligible_orders["order_purchase_timestamp"] = pd.to_datetime(
            eligible_orders["order_purchase_timestamp"]
        )

        start_timestamp = pd.Timestamp(start_date)
        end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        eligible_orders = eligible_orders[
            (eligible_orders["order_purchase_timestamp"] >= start_timestamp) &
            (eligible_orders["order_purchase_timestamp"] < end_timestamp)
        ]

    eligible_orders = eligible_orders[
        ["order_id", "order_status"]
    ]

    reconciliation = reconciliation.merge(
        eligible_orders,
        on="order_id",
        how="inner"
    )

    # Select mismatches greater than R$1
    mismatches = reconciliation[
        reconciliation["payment_difference_brl"] > 1
    ].copy()

    # Check existing R5 issues to prevent duplicates
    with engine.begin() as connection:

        existing = connection.execute(
            text("""
                SELECT order_id
                FROM data_quality_issue
                WHERE run_id = :run_id
                  AND rule_id = 'R5'
                  AND issue_type = 'payment_mismatch'
            """),
            {"run_id": run_id}
        ).fetchall()

        existing_ids = {row[0] for row in existing}

        records = []

        for _, row in mismatches.iterrows():

            if row["order_id"] in existing_ids:
                continue

            description = (
                f"Item gross: R${row['item_gross']:.2f}; "
                f"total payments: R${row['total_payments_brl']:.2f}; "
                f"net cash paid: R${row['net_cash_paid_brl']:.2f}; "
                f"absolute difference: "
                f"R${row['payment_difference_brl']:.2f}; "
                f"order status: {row['order_status']}."
            )

            if row["item_gross"] == 0:
                description += " No order-item records found."

            if row["total_payments_brl"] == 0:
                description += " No payment records found."

            records.append({
                "run_id": run_id,
                "rule_id": "R5",
                "order_id": row["order_id"],
                "issue_type": "payment_mismatch",
                "description": description
            })

        if records:
            connection.execute(
                text("""
                    INSERT INTO data_quality_issue (
                        run_id,
                        rule_id,
                        order_id,
                        issue_type,
                        description
                    )
                    VALUES (
                        :run_id,
                        :rule_id,
                        :order_id,
                        :issue_type,
                        :description
                    )
                """),
                records
            )

    print("R5 mismatches detected:", len(mismatches))
    print("New DQ issues inserted:", len(records))
    print("Existing issues skipped:", len(existing_ids))

def load_r3_missing_delivery_issues(run_id, start_date=None, end_date=None):

    import pandas as pd

    data = load_all_datasets()
    orders = data["orders"].copy()

    if start_date is not None and end_date is not None:
        orders["order_purchase_timestamp"] = pd.to_datetime(
            orders["order_purchase_timestamp"]
        )

        start_timestamp = pd.Timestamp(start_date)
        end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        orders = orders[
            (orders["order_purchase_timestamp"] >= start_timestamp) &
            (orders["order_purchase_timestamp"] < end_timestamp)
        ].copy()

    orders["order_delivered_customer_date"] = pd.to_datetime(
        orders["order_delivered_customer_date"],
        errors="coerce"
    )

    # Find delivered orders with missing delivery timestamps
    missing = orders[
        (orders["order_status"] == "delivered")
        & (orders["order_delivered_customer_date"].isna())
    ]

    with engine.begin() as connection:

        # Prevent duplicate issues for the same run
        existing = connection.execute(
            text("""
                SELECT order_id
                FROM data_quality_issue
                WHERE run_id = :run_id
                  AND rule_id = 'R3'
                  AND issue_type = 'missing_delivery_timestamp'
            """),
            {"run_id": run_id}
        ).fetchall()

        existing_ids = {row[0] for row in existing}

        records = []

        for _, row in missing.iterrows():

            if row["order_id"] in existing_ids:
                continue

            records.append({
                "run_id": run_id,
                "rule_id": "R3",
                "order_id": row["order_id"],
                "issue_type": "missing_delivery_timestamp",
                "description": (
                    "Order is marked delivered but the "
                    "customer delivery timestamp is missing."
                )
            })

        if records:
            connection.execute(
                text("""
                    INSERT INTO data_quality_issue (
                        run_id,
                        rule_id,
                        order_id,
                        issue_type,
                        description
                    )
                    VALUES (
                        :run_id,
                        :rule_id,
                        :order_id,
                        :issue_type,
                        :description
                    )
                """),
                records
            )

    print("R3 missing delivery timestamps:", len(missing))
    print("New DQ issues inserted:", len(records))
    print("Existing issues skipped:", len(existing_ids))

def load_r6_missing_fx_issues(run_id, start_date=None, end_date=None):

    # Prepare item data with FX rates
    item_data = prepare_fact_order_item(
        start_date,
        end_date
    )

    # Detect missing FX rates
    issues = build_r6_issues(item_data)

    records = []

    with engine.begin() as connection:

        # Check existing R6 issues for this run
        existing = connection.execute(
            text("""
                SELECT order_id, order_item_id
                FROM data_quality_issue
                WHERE run_id = :run_id
                  AND rule_id = 'R6'
                  AND issue_type = 'missing_fx_rate'
            """),
            {"run_id": run_id}
        ).fetchall()

        existing_keys = {
            (row[0], row[1]) for row in existing
        }

        for _, row in issues.iterrows():

            key = (
                row["order_id"],
                int(row["order_item_id"])
            )

            if key in existing_keys:
                continue

            records.append({
                "run_id": run_id,
                "rule_id": "R6",
                "order_id": row["order_id"],
                "order_item_id": int(row["order_item_id"]),
                "issue_type": row["issue_type"],
                "description": row["description"]
            })

        if records:
            connection.execute(
                text("""
                    INSERT INTO data_quality_issue (
                        run_id,
                        rule_id,
                        order_id,
                        order_item_id,
                        issue_type,
                        description
                    )
                    VALUES (
                        :run_id,
                        :rule_id,
                        :order_id,
                        :order_item_id,
                        :issue_type,
                        :description
                    )
                """),
                records
            )

    print("R6 missing FX rate issues:", len(issues))
    print("New DQ issues inserted:", len(records))
    print("Existing issues skipped:", len(existing))

def load_r13_internal_data_issues(run_id):

    internal = get_clean_internal_data()

    issues = internal["issues"]

    records = []

    with engine.begin() as connection:

        existing = connection.execute(
            text("""
                SELECT description
                FROM data_quality_issue
                WHERE run_id = :run_id
                  AND rule_id = 'R13'
            """),
            {"run_id": run_id}
        ).fetchall()

        existing_descriptions = {
            row[0] for row in existing
        }

        for issue in issues:

            description = (
                f"File: {issue['source_file']}; "
                f"Row: {issue['row_number']}; "
                f"Original: {issue['original_value']}; "
                f"Corrected: {issue['corrected_value']}; "
                f"Reason: {issue['reason']}"
            )

            if description in existing_descriptions:
                continue

            records.append({
                "run_id": run_id,
                "rule_id": "R13",
                "issue_type": "internal_commission_configuration",
                "description": description
            })

        if records:
            connection.execute(
                text("""
                    INSERT INTO data_quality_issue (
                        run_id,
                        rule_id,
                        issue_type,
                        description
                    )
                    VALUES (
                        :run_id,
                        :rule_id,
                        :issue_type,
                        :description
                    )
                """),
                records
            )

    print("R13 internal issues detected:", len(issues))
    print("New DQ issues inserted:", len(records))
    print("Existing issues skipped:", len(existing_descriptions))

def load_r9_lead_time_issues(run_id, start_date=None, end_date=None):

    data = load_all_datasets()

    orders = data["orders"]
    customers = data["customers"]

    # Select delivered orders
    delivery_orders = orders[
        orders["order_status"] == "delivered"
    ].copy()

    if start_date is not None and end_date is not None:
        delivery_orders["order_purchase_timestamp"] = pd.to_datetime(
            delivery_orders["order_purchase_timestamp"]
        )

        start_timestamp = pd.Timestamp(start_date)
        end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        delivery_orders = delivery_orders[
            (delivery_orders["order_purchase_timestamp"] >= start_timestamp) &
            (delivery_orders["order_purchase_timestamp"] < end_timestamp)
        ].copy()

    # Add customer state
    delivery_orders = delivery_orders.merge(
        customers[["customer_id", "customer_state"]],
        on="customer_id",
        how="left"
    )

    # Identify lead-time issues
    lead_time_results = calculate_calendar_lead_days(
        delivery_orders
    )

    issues = build_r9_data_quality_records(
        lead_time_results,
        run_id
    )

    records = []

    with engine.begin() as connection:

        existing = connection.execute(
            text("""
                SELECT order_id, issue_type
                FROM data_quality_issue
                WHERE run_id = :run_id
                  AND rule_id = 'R9'
            """),
            {"run_id": run_id}
        ).fetchall()

        existing_keys = {
            (row[0], row[1]) for row in existing
        }

        for _, row in issues.iterrows():

            key = (row["entity_id"], row["issue_type"])

            if key in existing_keys:
                continue

            records.append({
                "run_id": run_id,
                "rule_id": "R9",
                "order_id": row["entity_id"],
                "issue_type": row["issue_type"],
                "description": row["details"]
            })

        if records:
            connection.execute(
                text("""
                    INSERT INTO data_quality_issue (
                        run_id,
                        rule_id,
                        order_id,
                        issue_type,
                        description
                    )
                    VALUES (
                        :run_id,
                        :rule_id,
                        :order_id,
                        :issue_type,
                        :description
                    )
                """),
                records
            )

    print("R9 issues detected:", len(issues))
    print("New DQ issues inserted:", len(records))
    print("Existing issues skipped:", len(existing_keys))

def load_r16_geolocation_issues(run_id, start_date=None, end_date=None):
    distance_data = prepare_fact_order_item(
        start_date,
        end_date
    )
    issues = build_r16_issues(distance_data)

    records = []

    with engine.begin() as connection:
        existing = connection.execute(text("""
            SELECT order_id
            FROM data_quality_issue
            WHERE run_id = :run_id
              AND rule_id = 'R16'
        """), {"run_id": run_id}).fetchall()

        existing_keys = {row[0] for row in existing}

        for _, row in issues.iterrows():
            key = row["order_id"]

            if key in existing_keys:
                continue

            records.append({
                "run_id": run_id,
                "rule_id": "R16",
                "order_id": row["order_id"],
                "issue_type": row["issue_type"],
                "description": row["description"]
            })

        if records:
            connection.execute(text("""
                INSERT INTO data_quality_issue
                (run_id, rule_id, order_id, issue_type, description)
                VALUES
                (:run_id, :rule_id, :order_id, :issue_type, :description)
            """), records)

    print("R16 issues detected:", len(issues))
    print("New DQ issues inserted:", len(records))
    print("Existing issues skipped:", len(existing_keys))
