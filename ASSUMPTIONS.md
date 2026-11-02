# Assumptions and Business Rules



## 1. General Processing Assumptions



- The pipeline processes records based on `order_purchase_timestamp`.

- The start date and end date supplied to the pipeline are both inclusive.

- Date filtering is applied to the parent order's purchase timestamp.

- Seller monthly revenue and seller tiers are calculated using the available order history before filtering the monthly results to the requested date range. This preserves the previous-month dependency required for seller-tier assignment.

- Raw source files are persisted separately from the transformed analytical tables.

- Original internal configuration files are not modified during cleaning. Cleaning operations work on copies of the loaded data.



## 2. Order Eligibility and Revenue



### R1 — Customer Dimension

- A customer is identified by `customer_unique_id`.

- If a customer has multiple order records, the earliest purchase record is used to determine the customer's home state.



### R2 — Revenue Eligibility

- Only orders with status `delivered` are eligible for revenue calculations.

- Orders with status `canceled` or `unavailable` are excluded from the fact tables where the implementation explicitly filters these statuses.

- Other non-delivered statuses may remain in `fact_order`, but their `revenue_eligible` flag is set to `0`.

- Delivered orders are marked as revenue eligible.



### R4 — Revenue Calculation

- Item revenue is calculated using item price.

- Freight is included in gross order and item revenue.

- Commission is calculated on item price only; freight is excluded from the commission base.

- Revenue calculations use delivered orders/items only.



### R5 — Payment Reconciliation

- Order payment values are compared with the gross order amount, including freight.

- Voucher payments are excluded from the net-cash calculation.

- A payment mismatch is recorded only when the absolute difference is strictly greater than R$1.



## 3. Currency Conversion



### R6 — BRL to USD Conversion

- The Frankfurter API is used to obtain BRL-to-USD exchange rates.

- The approval timestamp is preferred as the FX transaction date. If it is unavailable, the purchase timestamp is used.

- The conversion uses the most recent exchange rate on or before the transaction date.

- A future exchange rate is not used when no earlier rate is available.

- Invalid dates or unavailable matching rates result in a missing conversion value.

- API requests use timeouts, retries, and response validation.

- No hardcoded exchange-rate fallback is used.



## 4. Category Mapping and Commission



### R8 — Product Category Resolution

- Category translation patches are applied before the Kaggle category translation mapping.

- If a category cannot be resolved, it is classified according to the implementation's unknown/uncategorized handling.

- The original source category values are not overwritten in the source files.



### R13 — Commission Calculation

- Commission rates are selected using the seller tier and applicable category configuration.

- Active category-specific overrides take precedence over seller-tier commission rates.

- The category override effective dates are evaluated using the order purchase timestamp.

- The effective end date is treated as inclusive.

- Commission is calculated on item price, excluding freight.

- Commission and item gross revenue are converted using the same FX rate associated with the item's FX transaction date.

- Internal configuration corrections and rejected rows are recorded as data-quality issues.



## 5. Delivery Metrics



### R3 — Missing Delivery Timestamps

- Delivered orders without a customer delivery timestamp are retained where applicable but excluded from delivery metrics that require that timestamp.

- Missing delivery timestamps are recorded as data-quality issues.



### R9 — Delivery Lead Time

- Calendar lead time is calculated between approval and delivery dates.

- Business-day lead time excludes weekends and applicable Brazilian public holidays.

- Business-day counting starts on the day after approval and includes the delivery date.

- Missing approval dates, missing delivery dates, and delivery dates earlier than approval dates are treated as data-quality issues.

- Invalid or unavailable dates do not produce a valid lead-time result.



### R10 — On-Time Delivery

- On-time delivery is determined by comparing calendar dates rather than exact timestamps.

- Delivery is on time when the actual delivery date is on or before the estimated delivery date.



### R11 — Seller and Carrier Delivery Classification

- The earliest shipping limit date for an order is used when classifying seller delivery performance.

- If the seller misses the shipping limit, the order is classified as `seller_late`.

- If the seller is not late but the customer delivery date exceeds the estimated delivery date, the order is classified as `carrier_late`.

- Seller lateness takes precedence when both conditions apply.

- Records without sufficient delivery information may receive the default `on_time` classification under the current implementation. This is a known limitation of the classification logic.



## 6. Seller Performance



### R12 — Seller Monthly Revenue and Tier

- Seller monthly revenue is calculated using delivered item prices.

- Freight is excluded from seller monthly revenue for tier assignment.

- The previous calendar month's revenue determines the current month's seller tier.

- The implemented thresholds are:

   - Bronze: previous-month revenue below R$5,000.

   - Silver: previous-month revenue from R$5,000 through R$20,000, inclusive.

   - Gold: previous-month revenue greater than R$20,000.

- Sellers without previous-month revenue are assigned zero previous-month revenue and therefore receive the Bronze tier.



## 7. Reviews and Geolocation



### R14 — Review Attribution

- When multiple reviews exist for an order, the latest review is retained.

- The retained review is attributed to each seller associated with that order.

- Missing review scores may remain in the resulting fact data.



### R15 — Geolocation Cleaning

- Geolocation records are restricted to the configured geographic bounding box for Brazil.

- Coordinates are aggregated by ZIP-code prefix using the median latitude and longitude.



### R16 — Delivery Distance

- Delivery distance is calculated using the Haversine formula.

- The calculation uses customer and seller ZIP-code-prefix coordinates.

- Missing coordinates result in an unavailable distance and may generate a data-quality issue.

- The distance is expressed in kilometres.



## 8. Geographic Regions and Campaigns



### R17 — State-to-Region Mapping

- State-to-region mapping is obtained from the IBGE API.

- The mapping is validated before it is used.

- No hardcoded regional mapping is used as a fallback.

- If the IBGE API is unavailable, the current item preparation process fails rather than silently using incomplete or substituted region data.



### R18 — Campaign Attribution

- Campaign attribution uses the order purchase timestamp.

- UTC timestamps ending in `Z` are converted to the `America/Sao_Paulo` timezone before campaign matching.

- Date-only campaign end dates are extended through the end of that local day.

- Campaign eligibility considers the configured state or region targeting and category targeting. `ALL` is treated as a wildcard.

- When multiple campaigns match, the highest priority is selected. If priorities are equal, the campaign with the latest start date is selected.

- One campaign is assigned per eligible item under the current implementation.



## 9. Internal Configuration Files



- Commission rates, category commission overrides, category translation patches, and campaign configuration are loaded from the configured internal data directory.

- Commission tier names are stripped of surrounding whitespace and normalized to title case.

- Category override names are stripped of surrounding whitespace and normalized to lowercase.

- Category override dates are parsed before validation.

- An override is rejected when its effective start date is later than its effective end date.

- Translation patches and campaign records are currently loaded without equivalent cleaning and validation in the internal-data loading module.

- Internal configuration data-quality issues are associated with the source file and row where available.

- R13 internal configuration issues are loaded independently of the requested order date range because they relate to configuration files rather than individual orders.



## 10. External API Dependencies



| Service | Purpose | Current behavior |

|---|---|---|

| Frankfurter | BRL-to-USD exchange rates | Timeout, retries, response validation, and caching |

| Nager.Date | Brazilian public holidays | Timeout, retries, and in-memory yearly caching |

| IBGE | Brazilian state-to-region mapping | Timeout, retries, response validation, and caching |



- External API failures are not silently replaced with hardcoded values.

- If a required API remains unavailable after retries, the corresponding processing step raises an error.

- In the current development environment, the IBGE endpoint has been unreachable because the connection to its HTTPS endpoint times out. This prevents the current item fact preparation from completing.



## 11. Pipeline Execution and Reruns



- Each pipeline execution receives a unique run ID.

- A run is initially recorded with status `RUNNING`.

- The pipeline records `SUCCESS` after all processing and loading steps complete.

- Exceptions cause the run to be marked `FAILED`, with the error message recorded.

- Existing records for the requested date range are deleted before the fact tables are reloaded.

- The deletion of the five fact-table ranges is performed in one database transaction.

- Fact preparation takes place before this deletion step.

- Fact deletion and subsequent fact loading are not part of one shared transaction. A failure during loading can therefore leave the requested range partially populated until a successful rerun.

- Data-quality issue loading is performed after fact loading.

- The recorded `rows_processed` value represents the combined number of rows loaded into the five fact tables. It does not include dimension rows, campaign rows, or data-quality issue rows.



## 12. Known Limitations and Pending Validation



- IBGE connectivity must be restored or an approved alternative mapping source must be agreed upon before the full region-dependent item pipeline can complete.

- Region-based KPIs and region-targeted campaign attribution cannot be considered fully validated while the IBGE mapping is unavailable.

- Item fact preparation is repeated by the R6 and R16 data-quality loaders, which can cause unnecessary processing and repeated external API calls.

- The pipeline's fact deletion and fact loading steps do not share a single transaction.

- The current runner records one combined fact-row count rather than per-table row counts.

- The complete requested processing period must be successfully executed and its results validated before final assignment metrics are reported.

- The API's error handling, pagination limits, and all response cases require final validation.

- The database schema must be kept synchronized with the actual table definitions before a clean setup is considered reproducible.



