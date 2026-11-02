\# Marketplace Seller Performance Pipeline — Results



\## 1. Pipeline Execution Summary



The pipeline was successfully executed for the period \*\*2017-01-01 to 2018-08-31\*\*.



| Metric | Result |

|---|---:|

| Run ID | `15cc3962-b0cf-472b-b16a-724d30a31ed9` |

| Execution status | SUCCESS |

| Rows processed | 422,385 |

| Total orders in `fact\_order` | 98,207 |



\## 2. Order Eligibility (R2)



Order eligibility is determined using order status.



| Order status | Order count | Revenue eligible |

|---|---:|---|

| Delivered | 96,478 | Yes |

| Shipped | 1,107 | No |

| Invoiced | 314 | No |

| Processing | 301 | No |

| Created | 5 | No |

| Approved | 2 | No |

| \*\*Total\*\* | \*\*98,207\*\* | |



Summary:



\- Revenue-eligible orders: \*\*96,478\*\*

\- Revenue-ineligible orders: \*\*1,729\*\*



Non-delivered orders are retained in the order fact table but are marked as ineligible for revenue.



\## 3. Revenue Analysis



\### January 2018



| Metric | Result |

|---|---:|

| Eligible orders | 7,069 |

| Gross revenue (USD) | \*\*$335,341.91\*\* |



Gross revenue is calculated using eligible orders and the stored USD revenue values.



\## 4. Top 5 Sellers by Commission — March 2018



Sellers are ranked by total commission in USD.



| Rank | Seller ID | Commission (USD) |

|---:|---|---:|

| 1 | `7c67e1448b00f6e969d365cea6b010ab` | $1,008.39 |

| 2 | `7d13fca15225358621be4086e1eb0964` | $993.05 |

| 3 | `4869f7a5dfa277a7dca6462dcf3b52b2` | $911.26 |

| 4 | `5dceca129747e92ff8ef7a997dc4f8ca` | $771.21 |

| 5 | `1025f0e2d44d7041d6cf58b6550e0bfa` | $623.24 |



\## 5. Delivery Performance — 2018



| Metric | Result |

|---|---:|

| Delivered orders | 52,783 |

| On-time orders | 48,699 |

| Overall on-time delivery | \*\*92.26%\*\* |



\### Regional delivery performance



Regional percentages could not be calculated because the IBGE state-region enrichment API request timed out during the final pipeline execution.



The fallback mechanism preserved customer records but left region values NULL.



Therefore:



\- Overall on-time delivery is available.

\- Regional delivery percentages are unavailable.

\- Regional campaign attribution is also incomplete.



No regional mapping was hardcoded to replace the unavailable API response.



\## 6. Campaign Attribution



| Campaign ID | Attributed items |

|---|---:|

| C001 | 2,875 |

| C002 | 70 |

| C003 | 196 |

| C004 | 961 |

| C005 | 0 |

| \*\*Total\*\* | \*\*4,102\*\* |



C005 had no attributed items in the final execution.



\## 7. Data Quality Results



The following data quality issues were recorded for the successful pipeline run.



| Rule ID | Description | Issue count |

|---|---|---:|

| R3 | Missing delivery timestamp | 8 |

| R5 | Payment mismatch | 247 |

| R9 | Delivery business-day validation | 60 |

| R13 | Commission override validation | 3 |

| R16 | Missing delivery distance | 549 |

| \*\*Total\*\* | | \*\*867\*\* |



\### Payment mismatch details (R5)



Payment reconciliation identified the following:



| Metric | Count |

|---|---:|

| Initial payment mismatches | 1,022 |

| Canceled/unavailable orders excluded | 766 |

| Remaining mismatches in eligible statuses | 256 |

| Eligible mismatches within requested date range recorded as issues | 247 |

| Eligible mismatches outside requested date range | 9 |



The mismatch threshold is strictly greater than R$1.



\## 8. Internal File Validation



Internal configuration files were cleaned and validated before loading.



| Internal file | Validation result |

|---|---|

| `commission\_rates.csv` | 7 valid rows; 1 correction |

| `category\_commission\_overrides.csv` | 4 valid rows; 1 correction; 1 rejected row |

| `category\_translation\_patch.csv` | 3 patches loaded |

| `campaigns.json` | 5 campaigns loaded |



\### Corrections and rejection



\*\*Correction 1 — Commission rates\*\*



\- File: `commission\_rates.csv`

\- Row: 8

\- Original value: `gold`

\- Corrected value: `Gold`

\- Reason: Tier name capitalization normalization.



\*\*Correction 2 — Category commission overrides\*\*



\- File: `category\_commission\_overrides.csv`

\- Row: 4

\- Original value: `  Telephony `

\- Corrected value: `telephony`

\- Reason: Whitespace and capitalization normalization.



\*\*Rejected row — Category commission overrides\*\*



\- File: `category\_commission\_overrides.csv`

\- Row: 6

\- `effective\_from`: 2018-05-01

\- `effective\_to`: 2018-04-30

\- Reason: Effective start date is later than effective end date.



Summary:



\- Internal-file corrections: \*\*2\*\*

\- Rejected rows: \*\*1\*\*

\- Internal-data quality issues: \*\*3\*\*



\## 9. Automated Testing



The automated test suite completed successfully.



| Test result | Count |

|---|---:|

| Passed | 10 |

| Failed | 0 |

| Non-blocking warnings | 1 |



Tests covered:



\- Historical FX rate selection and prevention of future rates.

\- Business-day calculations and holidays.

\- Missing and invalid delivery dates.

\- Seller monthly tier assignment.

\- Commission override precedence.

\- Campaign priority and tie-breaking.

\- IBGE enrichment success and fallback behavior.



One non-blocking Pandas deprecation warning remains in `pipeline/transform.py`.



\## 10. Known Limitations



1\. \*\*IBGE connectivity:\*\* The API request timed out during the final run. Customer records were preserved, but region values remained NULL.

2\. \*\*Regional KPIs:\*\* Regional delivery performance and regional campaign attribution could not be calculated.

3\. \*\*Pandas warning:\*\* A non-blocking deprecation warning remains in the transformation module.



The overall revenue, commission, campaign, and delivery calculations remain available for the completed execution.



\## 11. Final Status



<escape>\*\*Pipeline execution: SUCCESSFUL\*\*



The pipeline processed 422,385 rows for the requested date range, populated the analytical warehouse, recorded 867 data quality issues, and passed all 10 automated tests.</escape>



The IBGE connectivity limitation is documented and handled through a fallback mechanism that preserves customer data without inventing regional values.





