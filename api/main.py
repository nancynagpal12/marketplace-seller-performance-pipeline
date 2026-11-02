from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from pipeline.db import engine


app = FastAPI(
    title="Marketplace Seller Performance API",
    description="Read-only API for marketplace seller performance analytics",
    version="1.0.0"
)


# -------------------------
# Pydantic response models
# -------------------------

class HealthResponse(BaseModel):
    status: str
    database: str


class OrderItemResponse(BaseModel):
    order_id: str
    order_item_id: int
    product_id: Optional[str] = None
    seller_id: Optional[str] = None
    category_name: Optional[str] = None
    price_brl: Optional[Decimal] = None
    freight_value_brl: Optional[Decimal] = None
    item_gross_brl: Optional[Decimal] = None
    item_gross_usd: Optional[Decimal] = None
    commission_brl: Optional[Decimal] = None
    commission_usd: Optional[Decimal] = None
    campaign_id: Optional[str] = None


class OrderResponse(BaseModel):
    order_id: str
    customer_unique_id: Optional[str] = None
    order_status: Optional[str] = None
    order_purchase_timestamp: Optional[datetime] = None
    revenue_eligible: bool
    order_revenue_brl: Optional[Decimal] = None
    order_revenue_usd: Optional[Decimal] = None
    on_time_delivery: Optional[bool] = None
    items: list[OrderItemResponse]


class SellerScorecardResponse(BaseModel):
    seller_id: str
    month: str
    seller_tier: Optional[str] = None
    eligible_revenue_brl: Optional[Decimal] = None
    commission_usd: Optional[Decimal] = None
    on_time_rate: Optional[float] = None
    avg_review: Optional[float] = None
    delivered_orders: int
    reviewed_orders: int


class SellerTopResponse(BaseModel):
    seller_id: str
    metric_value: Optional[float] = None


class MonthlyKPIResponse(BaseModel):
    month: str
    region: Optional[str] = None
    total_orders: int
    eligible_orders: int
    revenue_brl: Optional[Decimal] = None
    revenue_usd: Optional[Decimal] = None
    commission_usd: Optional[Decimal] = None
    on_time_rate: Optional[float] = None


class CampaignPerformanceResponse(BaseModel):
    campaign_id: str
    campaign_name: Optional[str] = None
    item_count: int
    order_count: int
    seller_count: int
    gross_revenue_usd: Optional[Decimal] = None
    commission_usd: Optional[Decimal] = None


class DataQualitySummaryResponse(BaseModel):
    run_id: str
    total_issues: int
    issues_by_rule: list[dict]


# -------------------------
# Health
# -------------------------

@app.get("/health", response_model=HealthResponse)
def health():
    try:
        with engine.connect() as connection:
            database = connection.execute(
                text("SELECT DATABASE()")
            ).scalar_one()

        return {
            "status": "healthy",
            "database": database
        }
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {str(error)}"
        )


# -------------------------
# Order details
# -------------------------

@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str):
    order_query = text("""
        SELECT
            order_id,
            customer_unique_id,
            order_status,
            order_purchase_timestamp,
            revenue_eligible,
            order_revenue_brl,
            order_revenue_usd,
            on_time_delivery
        FROM fact_order
        WHERE order_id = :order_id
    """)

    items_query = text("""
        SELECT
            order_id,
            order_item_id,
            product_id,
            seller_id,
            category_name,
            price_brl,
            freight_value_brl,
            item_gross_brl,
            item_gross_usd,
            commission_brl,
            commission_usd,
            campaign_id
        FROM fact_order_item
        WHERE order_id = :order_id
        ORDER BY order_item_id
    """)

    with engine.connect() as connection:
        order = connection.execute(
            order_query, {"order_id": order_id}
        ).mappings().first()

        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")

        items = connection.execute(
            items_query, {"order_id": order_id}
        ).mappings().all()

    return {
        **dict(order),
        "items": [dict(item) for item in items]
    }


# -------------------------
# Seller monthly scorecard
# -------------------------

@app.get(
    "/sellers/{seller_id}/scorecard",
    response_model=SellerScorecardResponse
)
def seller_scorecard(
    seller_id: str,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$")
):
    query = text("""
        SELECT
            s.seller_id,
            :month AS month,
            m.seller_tier,
            m.eligible_revenue_brl,

            COALESCE(c.commission_usd, 0) AS commission_usd,

            d.on_time_rate,
            r.avg_review,

            COALESCE(d.delivered_orders, 0) AS delivered_orders,
            COALESCE(r.reviewed_orders, 0) AS reviewed_orders

        FROM dim_seller s

        LEFT JOIN fact_seller_monthly m
            ON m.seller_id = s.seller_id
            AND m.order_month = STR_TO_DATE(
                CONCAT(:month, '-01'), '%Y-%m-%d'
            )

        LEFT JOIN (
            SELECT
                i.seller_id,
                DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month,
                SUM(i.commission_usd) AS commission_usd
            FROM fact_order_item i
            JOIN fact_order o ON o.order_id = i.order_id
            WHERE DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') = :month
            GROUP BY i.seller_id, DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')
        ) c ON c.seller_id = s.seller_id

        LEFT JOIN (
            SELECT
                d.seller_id,
                COUNT(*) AS delivered_orders,
                AVG(
                    CASE
                        WHEN d.delivery_responsibility = 'on_time'
                        THEN 1.0 ELSE 0.0
                    END
                ) AS on_time_rate
            FROM fact_seller_order_delivery d
            JOIN fact_order o ON o.order_id = d.order_id
            WHERE DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') = :month
            GROUP BY d.seller_id
        ) d ON d.seller_id = s.seller_id

        LEFT JOIN (
            SELECT
                r.seller_id,
                AVG(r.review_score) AS avg_review,
                COUNT(r.review_score) AS reviewed_orders
            FROM fact_order_review r
            JOIN fact_order o ON o.order_id = r.order_id
            WHERE DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') = :month
            GROUP BY r.seller_id
        ) r ON r.seller_id = s.seller_id

        WHERE s.seller_id = :seller_id
    """)

    with engine.connect() as connection:
        result = connection.execute(
            query,
            {"seller_id": seller_id, "month": month}
        ).mappings().first()

    if result is None:
        raise HTTPException(status_code=404, detail="Seller not found")

    return dict(result)


# -------------------------
# Top sellers
# -------------------------

@app.get("/sellers/top", response_model=list[SellerTopResponse])
def top_sellers(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    metric: str = Query(
        "commission_usd",
        pattern=r"^(commission_usd|on_time_rate|avg_review)$"
    ),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    # Metric expressions are selected only from this whitelist.
    metric_queries = {
        "commission_usd": """
            SELECT i.seller_id, SUM(i.commission_usd) AS metric_value
            FROM fact_order_item i
            JOIN fact_order o ON o.order_id = i.order_id
            WHERE DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') = :month
            GROUP BY i.seller_id
        """,
        "on_time_rate": """
            SELECT
                d.seller_id,
                AVG(
                    CASE WHEN d.delivery_responsibility = 'on_time'
                    THEN 1.0 ELSE 0.0 END
                ) AS metric_value
            FROM fact_seller_order_delivery d
            JOIN fact_order o ON o.order_id = d.order_id
            WHERE DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') = :month
            GROUP BY d.seller_id
        """,
        "avg_review": """
            SELECT r.seller_id, AVG(r.review_score) AS metric_value
            FROM fact_order_review r
            JOIN fact_order o ON o.order_id = r.order_id
            WHERE DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') = :month
              AND r.review_score IS NOT NULL
            GROUP BY r.seller_id
        """
    }

    query = text(f"""
        SELECT seller_id, metric_value
        FROM ({metric_queries[metric]}) ranked
        ORDER BY metric_value DESC, seller_id
        LIMIT :limit OFFSET :offset
    """)

    with engine.connect() as connection:
        rows = connection.execute(
            query,
            {
                "month": month,
                "limit": limit,
                "offset": offset
            }
        ).mappings().all()

    return [dict(row) for row in rows]


# -------------------------
# Monthly KPIs
# -------------------------

@app.get("/kpis/monthly", response_model=list[MonthlyKPIResponse])
def monthly_kpis(
    start: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    end: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    region: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    if start > end:
        raise HTTPException(
            status_code=422,
            detail="Start month cannot be after end month"
        )

    query = text("""
        SELECT
            DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month,
            c.region,
            COUNT(*) AS total_orders,
            SUM(o.revenue_eligible = 1) AS eligible_orders,

            SUM(
                CASE WHEN o.revenue_eligible = 1
                THEN o.order_revenue_brl ELSE 0 END
            ) AS revenue_brl,

            SUM(
                CASE WHEN o.revenue_eligible = 1
                THEN o.order_revenue_usd ELSE 0 END
            ) AS revenue_usd,

            COALESCE(comm.commission_usd, 0) AS commission_usd,

            AVG(
                CASE WHEN o.revenue_eligible = 1
                THEN o.on_time_delivery ELSE NULL END
            ) AS on_time_rate

        FROM fact_order o
        LEFT JOIN dim_customer c
            ON c.customer_unique_id = o.customer_unique_id

        LEFT JOIN (
            SELECT
                DATE_FORMAT(fo.order_purchase_timestamp, '%Y-%m') AS month,
                dc.region,
                SUM(fi.commission_usd) AS commission_usd
            FROM fact_order_item fi
            JOIN fact_order fo ON fo.order_id = fi.order_id
            LEFT JOIN dim_customer dc
                ON dc.customer_unique_id = fo.customer_unique_id
            GROUP BY
                DATE_FORMAT(fo.order_purchase_timestamp, '%Y-%m'),
                dc.region
        ) comm
            ON comm.month = DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')
            AND comm.region <=> c.region

        WHERE o.order_purchase_timestamp >= STR_TO_DATE(
                CONCAT(:start, '-01'), '%Y-%m-%d'
              )
          AND o.order_purchase_timestamp < DATE_ADD(
                STR_TO_DATE(CONCAT(:end, '-01'), '%Y-%m-%d'),
                INTERVAL 1 MONTH
              )
          AND (:region IS NULL OR c.region = :region)

        GROUP BY
            DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m'),
            c.region,
            comm.commission_usd

        ORDER BY month, c.region
        LIMIT :limit OFFSET :offset
    """)

    with engine.connect() as connection:
        rows = connection.execute(
            query,
            {
                "start": start,
                "end": end,
                "region": region,
                "limit": limit,
                "offset": offset
            }
        ).mappings().all()

    return [dict(row) for row in rows]


# -------------------------
# Campaign performance
# -------------------------

@app.get(
    "/campaigns/{campaign_id}/performance",
    response_model=CampaignPerformanceResponse
)
def campaign_performance(campaign_id: str):
    query = text("""
        SELECT
            c.campaign_id,
            c.campaign_name,
            COUNT(i.order_id) AS item_count,
            COUNT(DISTINCT i.order_id) AS order_count,
            COUNT(DISTINCT i.seller_id) AS seller_count,
            COALESCE(SUM(i.item_gross_usd), 0) AS gross_revenue_usd,
            COALESCE(SUM(i.commission_usd), 0) AS commission_usd

        FROM dim_campaign c
        LEFT JOIN fact_order_item i
            ON i.campaign_id = c.campaign_id

        WHERE c.campaign_id = :campaign_id
        GROUP BY c.campaign_id, c.campaign_name
    """)

    with engine.connect() as connection:
        result = connection.execute(
            query,
            {"campaign_id": campaign_id}
        ).mappings().first()

    if result is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return dict(result)


# -------------------------
# Data quality summary
# -------------------------

@app.get(
    "/data-quality/summary",
    response_model=DataQualitySummaryResponse
)
def data_quality_summary(run_id: str):
    query = text("""
        SELECT
            rule_id,
            issue_type,
            COUNT(*) AS issue_count
        FROM data_quality_issue
        WHERE run_id = :run_id
        GROUP BY rule_id, issue_type
        ORDER BY rule_id, issue_type
    """)

    with engine.connect() as connection:
        run_exists = connection.execute(
            text("SELECT 1 FROM pipeline_run WHERE run_id = :run_id"),
            {"run_id": run_id}
        ).first()

        if run_exists is None:
            raise HTTPException(status_code=404, detail="Pipeline run not found")

        rows = connection.execute(
            query, {"run_id": run_id}
        ).mappings().all()

    issues = [dict(row) for row in rows]

    return {
        "run_id": run_id,
        "total_issues": sum(row["issue_count"] for row in issues),
        "issues_by_rule": issues
    }
