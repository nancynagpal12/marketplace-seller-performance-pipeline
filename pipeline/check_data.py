from pathlib import Path
import pandas as pd

DATA_DIR = Path("data/input")

orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv")

print("Total rows:", len(orders))

print("Duplicate order IDs:", orders["order_id"].duplicated().sum())

print("Duplicate complete rows:", orders.duplicated().sum())

print("\nSample duplicate order IDs:")
duplicates = orders[orders["order_id"].duplicated(keep=False)]
print(duplicates.head(10))