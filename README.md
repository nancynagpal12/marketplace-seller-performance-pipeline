

# Marketplace Seller Performance Pipeline



## 1. Project Overview



This project implements an end-to-end data engineering pipeline for a Brazilian e-commerce marketplace using the Olist dataset.



The pipeline extracts transactional and reference data, integrates external APIs, applies 18 business rules, transforms the data into analytical datasets, and loads the results into a MySQL dimensional database.



A FastAPI service provides read-only access to seller performance, order details, monthly KPIs, campaign performance, and data quality metrics.



## 2. Technology Stack



- Python 3

- Pandas and NumPy

- MySQL 8.0

- SQLAlchemy and PyMySQL

- FastAPI

- Pydantic

- Requests

- Pytest



## 3. Project Structure



```text

marketplace-seller-pipeline/

│

├── api/

│   └── main.py

│

├── data/

│   ├── input/

│   ├── raw/

│   └── internal/

│

├── outputs/

│

├── pipeline/

│   ├── extract.py

│   ├── internal_data.py

│   ├── load_campaigns.py

│   ├── holidays.py

│   ├── external_apis.py

│   ├── transform.py

│   ├── load_facts.py

│   ├── maintenance.py

│   ├── run.py

│   └── db.py

│

├── sql/

│   └── schema.sql

│

├── tests/

│   └── test_business_rules.py

│

├── README.md

├── ASSUMPTIONS.md

├── RESULTS.md

└── requirements.txt

```



## 4. Data Sources



### Primary Dataset

Brazilian E-Commerce Public Dataset by Olist.



The project uses nine datasets covering:

- Orders

- Order items

- Payments

- Reviews

- Customers

- Sellers

- Products

- Geolocation

- Product category translations



### External APIs

- Frankfurter API – BRL to USD currency conversion.

- Nager.Date API – Brazilian public holidays.

- IBGE API – Brazilian state and geographic region mapping.



### Internal Reference Files

- commission_rates.csv

- category_commission_overrides.csv

- category_translation_patch.csv

- campaigns.json



## 5. Business Rules



The pipeline implements 18 business rules covering:



- Customer identity and revenue eligibility.

- Payment reconciliation and currency conversion.

- Category resolution and commission calculation.

- Business-day delivery performance.

- Seller tiers and commission rates.

- Review deduplication.

- Geolocation and delivery distance.

- State-region mapping.

- Campaign attribution.



Detailed decisions and assumptions are documented in ASSUMPTIONS.md.



## 6. Database Design



The project uses a MySQL dimensional model.



Main tables include:



- dim_customer

- dim_seller

- dim_product

- dim_campaign

- fact_order

- fact_order_item

- fact_seller_monthly

- fact_seller_order_delivery

- fact_order_review

- data_quality_issue

- pipeline_run



The schema is provided in sql/schema.sql.



## 7. Installation and Setup



### Prerequisites



- Python 3.10+

- MySQL 8.x

- Git



### Create a virtual environment



```bash

python -m venv .venv

```



Activate it on Windows CMD:



```cmd

.venv\Scripts\activate

```



### Install dependencies



```bash

pip install -r requirements.txt

```



### Configure the database



Create the MySQL database:



```sql

CREATE DATABASE marketplace_seller_pipeline;

```



Configure database connection credentials before running the application.



Ensure the database schema matches the supplied SQL DDL.



### Input data



Place the nine Olist CSV files inside:



```text

data/input/

```



Place the internal reference files inside:



```text

data/internal/

```



## 8. Running the Pipeline



Execute the pipeline using:



```bash

python -m pipeline.run --start-date 2017-01-01 --end-date 2018-08-31

```



The pipeline performs extraction, raw data persistence, dimension loading, transformations, fact loading, and data quality tracking.



Only orders whose purchase timestamps fall within the requested date range are processed.



The pipeline supports configurable input, raw, and internal data directories.



## 9. Running the FastAPI Service



Start the API using:



```bash

uvicorn api.main:app --reload

```



API documentation:



```text

http://127.0.0.1:8000/docs

```



Alternative documentation:



```text

http://127.0.0.1:8000/redoc

```



## 10. API Endpoints



| Method | Endpoint | Description |

|---|---|---|

| GET | /health | Service and database health |

| GET | /orders/{order_id} | Order details |

| GET | /sellers/{seller_id}/scorecard | Monthly seller scorecard |

| GET | /sellers/top | Seller rankings |

| GET | /kpis/monthly | Monthly marketplace KPIs |

| GET | /campaigns/{campaign_id}/performance | Campaign performance |

| GET | /data-quality/summary | Data quality summary |



## 11. Testing



Run unit tests:



```bash

python -m pytest tests/test_business_rules.py -v

```



The tests cover important business rules including:



- R6 – Currency conversion.

- R9 – Business-day lead time.

- R12 – Seller tiers.

- R13 – Commission calculation.

- R18 – Campaign attribution.



## 12. Current Implementation Status



The following components have been substantially implemented:



- Data extraction and raw persistence.

- Frankfurter currency integration.

- Nager.Date holiday integration.

- Business rules R1–R18.

- MySQL dimensions and fact tables.

- Data quality tracking.

- Pipeline orchestration.

- Seven FastAPI endpoints.

- Unit tests for critical business rules.



**Known limitation:** The IBGE endpoint is currently unreachable from the development network. Consequently, state-region enrichment and region-dependent campaign attribution remain incomplete.



The complete requested processing period has not yet been successfully executed.



See RESULTS.md for verified development results and outstanding limitations.



## 13. Scalability: Handling 100× Data Volume



If the data volume increased by 100× and the pipeline needed to run daily, the following improvements would be considered:



1. Replace full CSV processing with incremental extraction and loading.

2. Introduce Apache Airflow for scheduling and orchestration.

3. Use Apache Spark for large-scale distributed processing.

4. Partition fact tables by purchase date.

5. Implement incremental transformations rather than recalculating historical data.

6. Introduce cloud object storage for raw and processed datasets.

7. Add monitoring, alerting, logging, and automated data quality checks.

8. Optimize MySQL indexes and query performance.

9. Cache external API responses and avoid unnecessary API calls.

10. Use transactional loading and reliable retry mechanisms.



These improvements would support higher data volumes, daily execution, and better pipeline reliability.



## 14. Project Status



This is an ongoing take-home assignment implementation. Final results will be documented after successful execution and validation of the complete requested date range.



