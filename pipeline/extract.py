
from pathlib import Path
import shutil
import pandas as pd


DEFAULT_INPUT_DIR = Path("data/input")
DEFAULT_RAW_DIR = Path("data/raw")

DATASETS = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

def set_input_directory(input_dir):
    global DEFAULT_INPUT_DIR
    DEFAULT_INPUT_DIR = Path(input_dir)

def load_dataset(filename, input_dir=None):
    """Load a CSV file from the configured input directory."""
    if input_dir is None:
        input_dir = DEFAULT_INPUT_DIR

    file_path = Path(input_dir) / filename

    if not file_path.exists():
        raise FileNotFoundError(f"Dataset not found: {file_path}")

    return pd.read_csv(file_path)

def load_all_datasets(input_dir=None):
    """Load all nine datasets from the configured input directory."""
    if input_dir is None:
        input_dir = DEFAULT_INPUT_DIR

    datasets = {}

    for name, filename in DATASETS.items():
        datasets[name] = load_dataset(filename, input_dir)

    return datasets

def persist_raw_datasets(
    input_dir=DEFAULT_INPUT_DIR,
    raw_dir=DEFAULT_RAW_DIR,
):
    """Copy original CSV files into the raw layer before transformation."""
    input_dir = Path(input_dir)
    raw_dir = Path(raw_dir)

    raw_dir.mkdir(parents=True, exist_ok=True)

    for filename in DATASETS.values():
        source = input_dir / filename

        if not source.exists():
            raise FileNotFoundError(f"Dataset not found: {source}")

        destination = raw_dir / filename
        shutil.copy2(source, destination)

        print(f"Raw file saved: {destination}")


if __name__ == "__main__":
    persist_raw_datasets()

    datasets = load_all_datasets()

    print("\nAll datasets loaded successfully!\n")

    for name, df in datasets.items():
        print(f"{name}: {df.shape[0]} rows, {df.shape[1]} columns")
