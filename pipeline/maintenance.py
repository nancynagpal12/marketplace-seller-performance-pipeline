from sqlalchemy import text
from pipeline.db import engine


def delete_existing_range(start_date, end_date):
    """
    Delete existing fact records for the requested date range.
    Child records are deleted before parent orders.
    """

    start_month = start_date.replace(day=1)
    end_month = end_date.replace(day=1)

    end_exclusive = end_date + __import__("datetime").timedelta(days=1)

    queries = {
        "fact_order_item": """
            DELETE item
            FROM fact_order_item AS item
            JOIN fact_order AS orders
                ON item.order_id = orders.order_id
            WHERE orders.order_purchase_timestamp >= :start_date
              AND orders.order_purchase_timestamp < :end_date
        """,

        "fact_seller_order_delivery": """
            DELETE delivery
            FROM fact_seller_order_delivery AS delivery
            JOIN fact_order AS orders
                ON delivery.order_id = orders.order_id
            WHERE orders.order_purchase_timestamp >= :start_date
              AND orders.order_purchase_timestamp < :end_date
        """,

        "fact_order_review": """
            DELETE review
            FROM fact_order_review AS review
            JOIN fact_order AS orders
                ON review.order_id = orders.order_id
            WHERE orders.order_purchase_timestamp >= :start_date
              AND orders.order_purchase_timestamp < :end_date
        """,

        "fact_order": """
            DELETE FROM fact_order
            WHERE order_purchase_timestamp >= :start_date
              AND order_purchase_timestamp < :end_date
        """,

        "fact_seller_monthly": """
            DELETE FROM fact_seller_monthly
            WHERE order_month >= :start_month
              AND order_month <= :end_month
        """
    }

    with engine.begin() as connection:

        for table_name, query in queries.items():

            if table_name == "fact_seller_monthly":
                result = connection.execute(
                    text(query),
                    {
                        "start_month": start_month,
                        "end_month": end_month
                    }
                )
            else:
                result = connection.execute(
                    text(query),
                    {
                        "start_date": start_date,
                        "end_date": end_exclusive
                    }
                )

            print(
                f"{table_name}: "
                f"{result.rowcount} existing records deleted"
            )