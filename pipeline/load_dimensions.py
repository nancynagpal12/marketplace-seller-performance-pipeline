from sqlalchemy import text
from pipeline.db import engine
from pipeline.extract import load_all_datasets
from pipeline.transform import build_customer_dimension
from pipeline.internal_data import get_clean_internal_data
from pipeline.transform import resolve_item_categories


def prepare_customer_dimension():
    # Load source datasets
    data = load_all_datasets()

    orders = data["orders"]
    customers = data["customers"]

    # Build customer dimension using R1
    customer_dimension = build_customer_dimension(
        orders,
        customers
    )

    return customer_dimension

def prepare_seller_dimension():
    data = load_all_datasets()

    sellers = data["sellers"]

    seller_dimension = sellers[
        [
            "seller_id",
            "seller_zip_code_prefix",
            "seller_city",
            "seller_state"
        ]
    ].copy()

    seller_dimension = seller_dimension.drop_duplicates(
        subset="seller_id",
        keep="first"
    )

    return seller_dimension

def prepare_product_dimension():
    data = load_all_datasets()
    internal = get_clean_internal_data()

    products = data["products"]
    order_items = data["order_items"]
    kaggle_translation = data["category_translation"]
    translation_patch = internal["translation_patch"]

    # Apply R8 category translation
    item_data = resolve_item_categories(
        order_items,
        products,
        kaggle_translation,
        translation_patch
    )

    # Get one category result per product
    category_mapping = (
        item_data[
            ["product_id", "product_category_name",
             "product_category_name_english"]
        ]
        .drop_duplicates(subset="product_id")
    )

    # Build product dimension
    product_dimension = products.merge(
        category_mapping[
            ["product_id", "product_category_name_english"]
        ],
        on="product_id",
        how="left"
    )

    product_dimension["product_category_name_english"] = (
        product_dimension["product_category_name_english"]
        .fillna(
            product_dimension["product_category_name"]
            .isna()
            .map({True: "uncategorized", False: "unknown"})
        )
    )

    product_dimension = product_dimension.rename(
    columns={
        "product_name_lenght": "product_name_length",
        "product_description_lenght": "product_description_length",
        "product_category_name_english": "english_category"
    }
    )

    return product_dimension

def prepare_all_dimensions():
    customer_dimension = prepare_customer_dimension()
    seller_dimension = prepare_seller_dimension()
    product_dimension = prepare_product_dimension()

    return {
        "customers": customer_dimension,
        "sellers": seller_dimension,
        "products": product_dimension
    }

def load_dimension(table_name, dataframe, key_column):
    allowed_tables = {
        "dim_customer": "customer_unique_id",
        "dim_seller": "seller_id",
        "dim_product": "product_id"
    }

    if table_name not in allowed_tables:
        raise ValueError("Invalid dimension table")

    if allowed_tables[table_name] != key_column:
        raise ValueError("Invalid key column")

    columns = list(dataframe.columns)

    column_names = ", ".join(f"`{col}`" for col in columns)
    placeholders = ", ".join(f":{col}" for col in columns)

    update_columns = [
        col for col in columns if col != key_column
    ]

    updates = ", ".join(
        f"`{col}` = VALUES(`{col}`)"
        for col in update_columns
    )

    query = f"""
        INSERT INTO {table_name} ({column_names})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {updates}
    """

    cleaned = dataframe.astype(object).where(
    dataframe.notna(), None
    )

    records = cleaned.to_dict(orient="records")

    with engine.begin() as connection:
        if records:
            connection.execute(text(query), records)

    print(f"{table_name}: {len(records)} records processed")

if __name__ == "__main__":
    customers = prepare_customer_dimension()

    print("Customer dimension prepared successfully!")
    print("Total customers:", len(customers))
    print("\nSample records:")
    print(customers.head())

    print("\nMissing customer IDs:", customers["customer_unique_id"].isna().sum())
    print("Duplicate customer IDs:", customers["customer_unique_id"].duplicated().sum())