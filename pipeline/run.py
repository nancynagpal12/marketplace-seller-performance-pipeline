
import argparse
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import text

from pipeline.db import engine
from pipeline.extract import (
    set_input_directory,
    persist_raw_datasets,
)
from pipeline.internal_data import set_internal_directory

from pipeline.load_dimensions import (
    prepare_all_dimensions,
    load_dimension,
)

from pipeline.load_campaigns import load_campaigns

from pipeline.load_facts import (
    prepare_fact_order,
    load_fact_order,
    prepare_fact_order_item,
    load_fact_order_item,
    prepare_fact_seller_monthly,
    load_fact_seller_monthly,
    prepare_fact_seller_order_delivery,
    load_fact_seller_order_delivery,
    prepare_fact_order_review,
    load_fact_order_review,
    load_payment_mismatch_issues,
    load_r3_missing_delivery_issues,
    load_r6_missing_fx_issues,
    load_r13_internal_data_issues,
    load_r9_lead_time_issues,
    load_r16_geolocation_issues,
)

from pipeline.maintenance import delete_existing_range


def create_pipeline_run(run_id, start_date, end_date):
    query = text("""
        INSERT INTO pipeline_run (
            run_id,
            start_date,
            end_date,
            status
        )
        VALUES (
            :run_id,
            :start_date,
            :end_date,
            'RUNNING'
        )
    """)

    with engine.begin() as connection:
        connection.execute(
            query,
            {
                "run_id": run_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        )


def update_pipeline_run(run_id, status, rows_processed=0, error=None):
    query = text("""
        UPDATE pipeline_run
        SET
            status = :status,
            rows_processed = :rows_processed,
            error_message = :error,
            completed_at = CURRENT_TIMESTAMP
        WHERE run_id = :run_id
    """)

    with engine.begin() as connection:
        connection.execute(
            query,
            {
                "run_id": run_id,
                "status": status,
                "rows_processed": rows_processed,
                "error": str(error) if error else None,
            }
        )


def run_pipeline(start_date, end_date, input_dir, raw_dir, internal_dir):

    if start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    run_id = str(uuid.uuid4())
    rows_processed = 0

    print("\n===================================")
    print("MARKETPLACE SELLER PERFORMANCE PIPELINE")
    print("===================================")
    print("Run ID:", run_id)
    print("Start date:", start_date)
    print("End date:", end_date)

    create_pipeline_run(run_id, start_date, end_date)

    try:
        # STEP 1: Configure directories
        print("\nSTEP 1: Configuring directories...")

        set_input_directory(input_dir)
        set_internal_directory(internal_dir)

        # STEP 2: Persist raw source files
        print("\nSTEP 2: Persisting raw datasets...")

        persist_raw_datasets(
            input_dir=input_dir,
            raw_dir=raw_dir
        )

        # STEP 3: Load dimensions
        print("\nSTEP 3: Loading dimensions...")

        dimensions = prepare_all_dimensions()

        load_dimension(
            "dim_customer",
            dimensions["customers"],
            "customer_unique_id"
        )

        load_dimension(
            "dim_seller",
            dimensions["sellers"],
            "seller_id"
        )

        load_dimension(
            "dim_product",
            dimensions["products"],
            "product_id"
        )

        # STEP 4: Load campaigns
        print("\nSTEP 4: Loading campaigns...")

        load_campaigns()

        # STEP 5: Prepare fact data
        # Prepare everything before deleting existing records.
        print("\nSTEP 5: Preparing fact tables...")

        fact_orders = prepare_fact_order(
            start_date,
            end_date
        )

        fact_items = prepare_fact_order_item(
            start_date,
            end_date
        )

        fact_monthly = prepare_fact_seller_monthly(
            start_date,
            end_date
        )

        fact_delivery = prepare_fact_seller_order_delivery(
            start_date,
            end_date
        )

        fact_reviews = prepare_fact_order_review(
            start_date,
            end_date
        )

        # STEP 6: Replace existing date-range data
        print("\nSTEP 6: Replacing existing date-range records...")

        delete_existing_range(start_date, end_date)

        # STEP 7: Load fact tables
        print("\nSTEP 7: Loading fact tables...")

        load_fact_order(fact_orders)
        rows_processed += len(fact_orders)

        load_fact_order_item(fact_items)
        rows_processed += len(fact_items)

        load_fact_seller_monthly(fact_monthly)
        rows_processed += len(fact_monthly)

        load_fact_seller_order_delivery(fact_delivery)
        rows_processed += len(fact_delivery)

        load_fact_order_review(fact_reviews)
        rows_processed += len(fact_reviews)

        # STEP 8: Load data-quality issues
        print("\nSTEP 8: Loading data-quality issues...")

        load_payment_mismatch_issues(
            run_id, start_date, end_date
        )

        load_r3_missing_delivery_issues(
            run_id, start_date, end_date
        )

        load_r6_missing_fx_issues(
            run_id, start_date, end_date
        )

        load_r13_internal_data_issues(run_id)

        load_r9_lead_time_issues(
            run_id, start_date, end_date
        )

        load_r16_geolocation_issues(
            run_id, start_date, end_date
        )

        # STEP 9: Mark successful
        update_pipeline_run(
            run_id,
            "SUCCESS",
            rows_processed
        )

        print("\n===================================")
        print("PIPELINE COMPLETED SUCCESSFULLY")
        print("Run ID:", run_id)
        print("Rows processed:", rows_processed)
        print("===================================")

    except Exception as error:

        update_pipeline_run(
            run_id,
            "FAILED",
            rows_processed,
            error
        )

        print("\nPIPELINE FAILED:", error)

        raise


def main():

    parser = argparse.ArgumentParser(
        description="Marketplace Seller Performance Pipeline"
    )

    parser.add_argument(
        "--start-date",
        required=True,
        type=date.fromisoformat
    )

    parser.add_argument(
        "--end-date",
        required=True,
        type=date.fromisoformat
    )

    parser.add_argument(
        "--input-dir",
        default="data/input",
        type=Path
    )

    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        type=Path
    )

    parser.add_argument(
        "--internal-dir",
        default="data/internal",
        type=Path
    )

    args = parser.parse_args()

    run_pipeline(
        args.start_date,
        args.end_date,
        args.input_dir,
        args.raw_dir,
        args.internal_dir
    )


if __name__ == "__main__":
    main()
