---
name: setup-timescaledb-hypertables
description: 'Step-by-step instructions for designing table schemas and setting up TimescaleDB with hypertables, indexes, compression, retention policies, and continuous aggregates. Instructions for selecting: partition columns, segment_by columns, order_by columns, chunk time interval, real-time aggregation.'
---

# TimescaleDB Complete Setup

Instructions for insert-heavy data patterns where data is inserted but rarely changed:

- **Time-series data** (sensors, metrics, system monitoring)
- **Event logs** (user events, audit trails, application logs)
- **Transaction records** (orders, payments, financial transactions)
- **Sequential data** (records with auto-incrementing IDs and timestamps)
- **Append-only datasets** (immutable records, historical data)

## Step 1: Create Hypertable

```sql
CREATE TABLE your_table_name (
    timestamp TIMESTAMPTZ NOT NULL,
    entity_id TEXT NOT NULL,          -- device_id, user_id, symbol, etc.
    category TEXT,                    -- sensor_type, event_type, asset_class, etc.
    value_1 DOUBLE PRECISION,         -- price, temperature, latency, etc.
    value_2 DOUBLE PRECISION,         -- volume, humidity, throughput, etc.
    value_3 INTEGER,                  -- count, status, level, etc.
    metadata JSONB                    -- flexible additional data
) WITH (
    tsdb.hypertable,
    tsdb.partition_column='timestamp',
    tsdb.enable_columnstore=true,     -- Disable if table has vector columns
    tsdb.segmentby='entity_id',       -- See selection guide below
    tsdb.orderby='timestamp DESC',     -- See selection guide below
    tsdb.sparse_index='minmax(value_1),minmax(value_2),minmax(value_3)' -- see selection guide below
);
```

### Compression Decision

- **Enable by default** for insert-heavy patterns
- **Disable** if table has vector type columns (pgvector) - indexes on vector columns incompatible with columnstore

### Partition Column Selection

Must be time-based (TIMESTAMP/TIMESTAMPTZ/DATE) or integer (INT/BIGINT) with good temporal/sequential distribution.

**Common patterns:**

- TIME-SERIES: `timestamp`, `event_time`, `measured_at`
- EVENT LOGS: `event_time`, `created_at`, `logged_at`
- TRANSACTIONS: `created_at`, `transaction_time`, `processed_at`
- SEQUENTIAL: `id` (auto-increment when no timestamp), `sequence_number`
- APPEND-ONLY: `created_at`, `inserted_at`, `id`

**Less ideal:** `ingested_at` (when data entered system - use only if it's your primary query dimension)
**Avoid:** `updated_at` (breaks time ordering unless it's primary query dimension)

### Segment_By Column Selection

**PREFER SINGLE COLUMN** - multi-column rarely optimal. Multi-column can only work for highly correlated columns (e.g., metric_name + metric_type) with sufficient row density.

**Requirements:**

- Frequently used in WHERE clauses (most common filter)
- Good row density (>100 rows per value per chunk)
- Primary logical partition/grouping

**Examples:**

- IoT: `device_id`
- Finance: `symbol`
- Metrics: `service_name`, `service_name, metric_type` (if sufficient row density), `metric_name, metric_type` (if sufficient row density)
- Analytics: `user_id` if sufficient row density, otherwise `session_id`
- E-commerce: `product_id` if sufficient row density, otherwise `category_id`

**Row density guidelines:**

- Target: >100 rows per segment_by value within each chunk.
- Poor: <10 rows per segment_by value per chunk → choose less granular column
- What to do with low-density columns: prepend to order_by column list.

**Query pattern drives choice:**

```sql
SELECT * FROM table WHERE entity_id = 'X' AND timestamp > ...
-- ↳ segment_by: entity_id (if >100 rows per chunk)
```

**Avoid:** timestamps, unique IDs, low-density columns (<100 rows/value/chunk), columns rarely used in filtering

### Order_By Column Selection

Creates natural time-series progression when combined with segment_by for optimal compression.

**Most common:** `timestamp DESC`

**Examples:**

- IoT/Finance/E-commerce: `timestamp DESC`
- Metrics: `metric_name, timestamp DESC` (if metric_name has too low density for segment_by)
- Analytics: `user_id, timestamp DESC` (user_id has too low density for segment_by)

**Alternative patterns:**

- `sequence_id DESC` for event streams with sequence numbers
- `timestamp DESC, event_order DESC` for sub-ordering within same timestamp

**Low-density column handling:**
If a column has <100 rows per chunk (too low for segment_by), prepend it to order_by:

- Example: `metric_name` has 20 rows/chunk → use `segment_by='service_name'`, `order_by='metric_name, timestamp DESC'`
- Groups similar values together (all temperature readings, then pressure readings) for better compression

**Good test:** ordering created by `(segment_by_column, order_by_column)` should form a natural time-series progression. Values close to each other in the progression should be similar.

**Avoid in order_by:** random columns, columns with high variance between adjacent rows, columns unrelated to segment_by

### Compression Sparse Index Selection

**Sparse indexes** enable query filtering on compressed data without decompression. Store metadata per batch (~1000 rows) to eliminate batches that don't match query predicates.

**Types:**

- **minmax:** Min/max values per batch - for range queries (>, <, BETWEEN) on numeric/temporal columns

**Use minmax for:** price, temperature, measurement, timestamp (range filtering)

**Use for:**

- minmax for outlier detection (temperature > 90).
- minmax for fields that are highly correlated with segmentby and orderby columns (e.g. if orderby includes `created_at`, minmax on `updated_at` is useful).

**Avoid:** rarely filtered columns.

IMPORTANT: NEVER index columns in segmentby or orderby. Orderby columns will always have minmax indexes without any configuration.

**Configuration:**
The format is a comma-separated list of type_of_index(column_name).

```sql
ALTER TABLE table_name SET (
    timescaledb.sparse_index = 'minmax(value_1),minmax(value_2)'
);
```

Explicit configuration available since v2.22.0 (was auto-created since v2.16.0).

### Chunk Time Interval (Optional)

Default: 7 days (use if volume unknown, or ask user). Adjust based on volume:

- High frequency: 1 hour - 1 day
- Medium: 1 day - 1 week
- Low: 1 week - 1 month

```sql
SELECT set_chunk_time_interval('your_table_name', INTERVAL '1 day');
```

**Good test:** recent chunk indexes should fit in less than 25% of RAM.

### Indexes & Primary Keys

Common index patterns - composite indexes on an id and timestamp:

```sql
CREATE INDEX idx_entity_timestamp ON your_table_name (entity_id, timestamp DESC);
```

**Important:** Only create indexes you'll actually use - each has maintenance overhead.

**Primary key and unique constraints rules:** Must include partition column.

**Option 1: Composite PK with partition column**

```sql
ALTER TABLE your_table_name ADD PRIMARY KEY (entity_id, timestamp);
```

**Option 2: Single-column PK (only if it's the partition column)**

```sql
CREATE TABLE ... (id BIGINT PRIMARY KEY, ...) WITH (tsdb.partition_column='id');
```

**Option 3: No PK**: strict uniqueness is often not required for insert-heavy patterns.

## Step 2: Compression Policy

Set `after` interval for when: data becomes mostly immutable (some updates/backfill OK) AND B-tree indexes aren't needed for queries (less common criterion).

```sql
-- Adjust 'after' based on update patterns
CALL add_columnstore_policy('your_table_name', after => INTERVAL '1 day');
```

## Step 3: Retention Policy

IMPORTANT: Don't guess - ask user or comment out if unknown.

```sql
-- Example - replace with requirements or comment out
SELECT add_retention_policy('your_table_name', INTERVAL '365 days');
```

## Step 4: Create Continuous Aggregates

Use different aggregation intervals for different uses.

### Short-term (Minutes/Hours)

For up-to-the-minute dashboards on high-frequency data.

```sql
CREATE MATERIALIZED VIEW your_table_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', timestamp) AS bucket,
    entity_id,
    category,
    COUNT(*) as record_count,
    AVG(value_1) as avg_value_1,
    MIN(value_1) as min_value_1,
    MAX(value_1) as max_value_1,
    SUM(value_2) as sum_value_2
FROM your_table_name
GROUP BY bucket, entity_id, category;
```

### Long-term (Days/Weeks/Months)

For long-term reporting and analytics.

```sql
CREATE MATERIALIZED VIEW your_table_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 day', timestamp) AS bucket,
    entity_id,
    category,
    COUNT(*) as record_count,
    AVG(value_1) as avg_value_1,
    MIN(value_1) as min_value_1,
    MAX(value_1) as max_value_1,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY value_1) as median_value_1,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value_1) as p95_value_1,
    SUM(value_2) as sum_value_2
FROM your_table_name
GROUP BY bucket, entity_id, category;
```

## Step 5: Aggregate Refresh Policies

Set up refresh policies based on your data freshness requirements.

**start_offset:** Usually omit (refreshes all). Exception: If you don't care about refreshing data older than X (see below). With retention policy on raw data: match the retention policy.

**end_offset:** Set beyond active update window (e.g., 15 min if data usually arrives within 10 min). Data newer than end_offset won't appear in queries without real-time aggregation. If you don't know your update window, use the size of the time_bucket in the query, but not less than 5 minutes.

**schedule_interval:** Set to the same value as the end_offset but not more than 1 hour.

**Hourly - frequent refresh for dashboards:**

```sql
SELECT add_continuous_aggregate_policy('your_table_hourly',
    end_offset => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes');
```

**Daily - less frequent for reports:**

```sql
SELECT add_continuous_aggregate_policy('your_table_daily',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
```

**Use start_offset only if you don't care about refreshing old data**
Use for high-volume systems where query accuracy on older data doesn't matter:

```sql
-- the following aggregate can be stale for data older than 7 days
-- SELECT add_continuous_aggregate_policy('aggregate_for_last_7_days',
--     start_offset => INTERVAL '7 days',    -- only refresh last 7 days
--     end_offset => INTERVAL '15 minutes',
--     schedule_interval => INTERVAL '15 minutes');
```

IMPORTANT: you MUST set a start_offset to be less than the retention policy on raw data. By default, set the start_offset equal to the retention policy.
If the retention policy is commented out, comment out the start_offset as well. like this:

```sql
SELECT add_continuous_aggregate_policy('your_table_daily',
--  start_offset => INTERVAL '<retention period here>',    -- uncomment if retention policy is enabled on the raw data table
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
```

## Step 6: Real-Time Aggregation (Optional)

Real-time combines materialized + recent raw data at query time. Provides up-to-date results at the cost of higher query latency.

More useful for fine-grained aggregates (e.g., minutely) than coarse ones (e.g., daily/monthly) since large buckets will be mostly incomplete with recent data anyway.

Disabled by default in v2.13+, before that it was enabled by default.

**Use when:** Need data newer than end_offset, up-to-minute dashboards, can tolerate higher query latency
**Disable when:** Performance critical, refresh policies sufficient, high query volume, missing and stale data for recent data is acceptable

**Enable for current results (higher query cost):**

```sql
ALTER MATERIALIZED VIEW your_table_hourly SET (timescaledb.materialized_only = false);
```

**Disable for performance (but with stale results):**

```sql
ALTER MATERIALIZED VIEW your_table_hourly SET (timescaledb.materialized_only = true);
```

## Step 7: Compress Aggregates

Rule: segment_by = ALL GROUP BY columns except time_bucket, order_by = time_bucket DESC

```sql
-- Hourly
ALTER MATERIALIZED VIEW your_table_hourly SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id, category',
    timescaledb.orderby = 'bucket DESC'
);
CALL add_columnstore_policy('your_table_hourly', after => INTERVAL '3 days');

-- Daily
ALTER MATERIALIZED VIEW your_table_daily SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id, category',
    timescaledb.orderby = 'bucket DESC'
);
CALL add_columnstore_policy('your_table_daily', after => INTERVAL '7 days');
```

## Step 8: Aggregate Retention

Aggregates are typically kept longer than raw data.
IMPORTANT: Don't guess - ask user or you **MUST comment out if unknown**.

```sql
-- Example - replace or comment out
SELECT add_retention_policy('your_table_hourly', INTERVAL '2 years');
SELECT add_retention_policy('your_table_daily', INTERVAL '5 years');
```

## Step 9: Performance Indexes on Continuous Aggregates

**Index strategy:** Analyze WHERE clauses in common queries → Create indexes matching filter columns + time ordering

**Pattern:** `(filter_column, bucket DESC)` supports `WHERE filter_column = X AND bucket >= Y ORDER BY bucket DESC`

Examples:

```sql
CREATE INDEX idx_hourly_entity_bucket ON your_table_hourly (entity_id, bucket DESC);
CREATE INDEX idx_hourly_category_bucket ON your_table_hourly (category, bucket DESC);
```

**Multi-column filters:** Create composite indexes for `WHERE entity_id = X AND category = Y`:

```sql
CREATE INDEX idx_hourly_entity_category_bucket ON your_table_hourly (entity_id, category, bucket DESC);
```

**Important:** Only create indexes you'll actually use - each has maintenance overhead.

## Step 10: Optional Enhancements

### Space Partitioning (NOT RECOMMENDED)

Only for query patterns where you ALWAYS filter by the space-partition column with expert knowledge and extensive benchmarking. STRONGLY prefer time-only partitioning.

## Step 11: Verify Configuration

```sql
-- Check hypertable
SELECT * FROM timescaledb_information.hypertables
WHERE hypertable_name = 'your_table_name';

-- Check compression
SELECT * FROM timescaledb_information.columnstore_settings
WHERE hypertable_name LIKE 'your_table_name';

-- Check aggregates
SELECT * FROM timescaledb_information.continuous_aggregates;

-- Check policies
SELECT * FROM timescaledb_information.jobs ORDER BY job_id;

-- Monitor chunk information
SELECT chunk_name, table_size, compressed_heap_size, compressed_index_size
FROM timescaledb_information.chunks
WHERE hypertable_name = 'your_table_name';
```

## Performance Guidelines

- **Chunk size:** Recent chunk indexes should fit in less than 25% of RAM
- **Compression:** Expect 90%+ reduction (10x) with proper columnstore config
- **Query optimization:** Use continuous aggregates for historical queries and dashboards
- **Memory:** Run `timescaledb-tune` for self-hosting (auto-configured on cloud)

## Schema Best Practices

### Do's and Don'ts

- ✅ Use `TIMESTAMPTZ` NOT `timestamp`
- ✅ Use `>=` and `<` NOT `BETWEEN` for timestamps
- ✅ Use `TEXT` with constraints NOT `char(n)`/`varchar(n)`
- ✅ Use `snake_case` NOT `CamelCase`
- ✅ Use `BIGINT GENERATED ALWAYS AS IDENTITY` NOT `SERIAL`
- ✅ Use `BIGINT` for IDs by default over `INTEGER` or `SMALLINT`
- ✅ Use `DOUBLE PRECISION` by default over `REAL`/`FLOAT`
- ✅ Use `NUMERIC` NOT `MONEY`
- ✅ Use `NOT EXISTS` NOT `NOT IN`
- ✅ Use `time_bucket()` or `date_trunc()` NOT `timestamp(0)` for truncation

## API Reference (Current vs Deprecated)

**Deprecated Parameters → New Parameters:**

- `timescaledb.compress` → `timescaledb.enable_columnstore`
- `timescaledb.compress_segmentby` → `timescaledb.segmentby`
- `timescaledb.compress_orderby` → `timescaledb.orderby`

**Deprecated Functions → New Functions:**

- `add_compression_policy()` → `add_columnstore_policy()`
- `remove_compression_policy()` → `remove_columnstore_policy()`
- `compress_chunk()` → `convert_to_columnstore()`
- `decompress_chunk()` → `convert_to_rowstore()`

**Deprecated Views → New Views:**

- `compression_settings` → `columnstore_settings`
- `hypertable_compression_settings` → `hypertable_columnstore_settings`
- `chunk_compression_settings` → `chunk_columnstore_settings`

**Deprecated Stats Functions → New Stats Functions:**

- `hypertable_compression_stats()` → `hypertable_columnstore_stats()`
- `chunk_compression_stats()` → `chunk_columnstore_stats()`

## Questions to Ask User

1. What kind of data will you be storing?
2. How do you expect to use the data?
3. What queries will you run?
4. How long to keep the data?
5. Column types if unclear
