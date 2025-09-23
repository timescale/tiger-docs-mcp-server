---
title: TimescaleDB Complete Setup Guide
description: "Step-by-step instructions for designing table schemas and setting up TimescaleDB with hypertables, indexes, compression, retention policies, and continuous aggregates. Instructions for selecting: partition columns, segment_by columns, order_by columns, chunk time interval, real-time aggregation."
---

# TimescaleDB Complete Setup Guide for AI Coding Assistants

You are tasked with setting up a complete TimescaleDB database solution for insert-heavy data patterns. This guide provides step-by-step instructions for creating hypertables, configuring compression, setting up retention policies, and implementing continuous aggregates with their associated policies. Adapt the schema and configurations to your specific use case.

TimescaleDB hypertables are optimized for insert-heavy data patterns where data is inserted but rarely changed, including:
- **Time-series data** (sensors, metrics, system monitoring)
- **Event logs** (user events, audit trails, application logs)
- **Transaction records** (orders, payments, financial transactions)
- **Sequential data** (records with auto-incrementing IDs and timestamps)
- **Append-only datasets** (immutable records, historical data)

## Step 1: Create Base Table and Hypertable

Create a table schema appropriate for your insert-heavy data pattern, then convert it to a hypertable:



```sql
-- Create hypertable with compression settings directly using WITH clause
-- IMPORTANT: Choose segment_by column carefully (see guidance below)
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
    tsdb.enable_columnstore=true,
    tsdb.segmentby='entity_id',  -- Usually prefer single column - see selection guide below
    tsdb.orderby='timestamp DESC'
);
```

### Whether to Enable Columnstore Compression

**Enable compression by default** for insert-heavy data patterns. The exception is if your table has **vector type columns (pgvector)** because indexes on vector columns are not supported with columnstore compression - in this case, do not enable compression.

For tables with vector columns, create the hypertable without compression settings (tsdb.enable_columnstore=false, no segment_by or order_by columns) and rely on time-based partitioning benefits only.

### How to Choose Partition Column

The partition column determines how data is divided into chunks over time or sequence. For insert-heavy data patterns, choose based on your data characteristics:

**Requirements:**
- Must be a time-based column (TIMESTAMP, TIMESTAMPTZ, DATE) or integer (INT, BIGINT)
- Should represent when the event occurred, record was created, or sequential ordering  
- Must have good temporal/sequential distribution (not all the same value)

**Common patterns by data type:**
- **TIME-SERIES DATA**: `timestamp` (when measurement occurred), `event_time`, `measured_at`
- **EVENT LOGS**: `event_time` (when business event occurred), `created_at` (when record was created), `logged_at`
- **TRANSACTION RECORDS**: `created_at` (when record was created), `transaction_time`, `processed_at`
- **SEQUENTIAL DATA**: `id` (auto-increment, use when there is no timestamp), `sequence_number`, `created_at`
- **APPEND-ONLY DATASETS**: `created_at`, `inserted_at`, `id`

**⚠️ Less ideal choices:**
- `ingested_at` - when data entered the system (use only if it's your primary query dimension)

**Avoid using `updated_at` as partition column:**
- Records can be updated out of time order
- Creates uneven chunk distribution
- Breaks time-based query optimization

**Use `updated_at` only if:**
- It's your primary query dimension
- You rarely query by creation time
- Update patterns are predictable and time-ordered

### How to Choose Segment_By Column

The segment_by column determines how data is grouped during compression. **PREFER SINGLE COLUMN** - multi-column segment_by is rarely optimal.

Multi-column segment_by can work when columns are highly correlated (e.g., metric_name + metric_type where they always appear together), but requires careful analysis of row density patterns.

**Choose a column that:**
1. Is frequently used in WHERE clauses (your most common filter)
2. Has good row density per segment (>100 rows per segment_by value per chunk)
3. Represents the primary way you partition/group your data logically
4. Balances compression ratio with query performance

**Examples by use case:**
- **IoT/Sensors**: `device_id`
- **Finance/Trading**: `symbol`
- **Application Metrics**: `service_name`, `service_name + metric_type` (if sufficient row density), `metric_name + metric_type` (if sufficient row density)
- **User Analytics**: `user_id` if sufficient row density, otherwise `session_id`
- **E-commerce**: `product_id` if sufficient row density, otherwise `category_id`

**Row density guidelines:**
- Target >100 rows per segment_by value within each chunk
- Poor compression: segment_by values with <10 rows per chunk
- Good compression: segment_by values with 100-10,000+ rows per chunk
- If your entity_id only has 5-10 rows per chunk, choose a less granular column

**Query pattern analysis:**
Your most common query pattern should drive the choice:
```sql
SELECT * FROM table WHERE entity_id = 'X' AND timestamp > ...
```
↳ Good segment_by: `entity_id` (if entity_id has >100 rows per chunk)

**Bad choices for segment_by:**
- Timestamp columns (already time-partitioned)
- Unique identifiers (transaction_id, uuid fields)
- Columns with low row density (<100 rows per value per chunk)
- Columns rarely used in filtering
- Multiple columns (creates too many small segments)

### How to Choose Order_By Column

The order_by column should create a natural time-series progression when combined with segment_by. This ensures adjacent rows have similar values, which compress well.

The combination (segment_by, order_by) should form a sequence where values change gradually between consecutive rows.

**Examples:**
- `segment_by='device_id', order_by='timestamp DESC'` ↳ Forms natural progression: device readings over time
- `segment_by='symbol', order_by='timestamp DESC'` ↳ Forms natural progression: stock prices over time  
- `segment_by='user_id', order_by='session_timestamp DESC'` ↳ Forms natural progression: user events over time

**Most common pattern:** `timestamp DESC` (newest data first). This works well because time-series data naturally has temporal correlation.

**Alternative patterns when timestamp isn't the natural ordering:**
- `sequence_id DESC` for event streams with sequence numbers
- `timestamp DESC, event_order DESC` for sub-ordering within time

**Important:** When a column can't be used in segment_by due to low row density, consider prepending it to order_by to preserve natural progression:

Example: metric_name has only 20 rows per chunk (too low for segment_by)
- `segment_by='service_name'` (has >100 rows per chunk)  
- `order_by='metric_name, timestamp DESC'`

This creates natural progression within each service: all temperature readings together, then all pressure readings, etc. Values are more similar when grouped by metric type, improving compression.

**Advanced:** Append columns that benefit from min/max indexing for query optimization. After the natural progression columns, you can append additional columns that:
- Are frequently used in WHERE clauses for filtering
- Have some correlation with the main progression  
- Can help exclude compressed chunks during queries

Example: `created_at DESC, updated_at DESC`
- created_at provides the main natural progression
- updated_at is appended because it often correlates and is used for filtering
- TimescaleDB tracks min/max of updated_at per compressed chunk
- Queries like "WHERE updated_at > '2024-01-01'" can exclude entire compressed batches

Other examples:
- `timestamp DESC, price DESC` (for financial data where price filters are common)
- `timestamp DESC, severity DESC` (for logs where severity filtering is frequent)

**Bad choices for order_by:**
- Random columns that break natural progression
- Columns that create high variance between adjacent rows
- Columns unrelated to the segment_by grouping

**NOTE:** You can also configure compression later using ALTER TABLE:
```sql
ALTER TABLE your_table_name SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id, category',
    timescaledb.orderby = 'timestamp DESC'
);
```

### Configure Chunk Time Interval

Optionally adjust the chunk time interval based on your data volume. The default is 7 days. If you have no information about the data volume, use the default or ask the user.

**Adjust based on data volume:**
- 1 hour to 1 day for high frequency
- 1 day to 1 week for medium frequency  
- 1 week to 1 month for low frequency

```sql
SELECT set_chunk_time_interval('your_table_name', INTERVAL '1 day');
```

### Create Indexes

Create indexes for your common query patterns:

```sql
CREATE INDEX idx_entity_timestamp ON your_table_name (entity_id, timestamp DESC);
CREATE INDEX idx_category_timestamp ON your_table_name (category, timestamp DESC);
```

#### Primary Key Considerations for Hypertables

Any primary key or unique index **MUST include the partitioning column**. Single-column primary keys (like `id SERIAL PRIMARY KEY`) don't work well with hypertables UNLESS the primary key column is also the partitioning column.

**Options for primary keys:**

1. **If using timestamp partitioning, use composite primary key:**
   ```sql
   ALTER TABLE your_table_name ADD PRIMARY KEY (entity_id, timestamp);
   ```

2. **If using integer partitioning, single-column PK works:**
   ```sql
   -- Example: CREATE TABLE ... (id SERIAL PRIMARY KEY, ...) WITH (tsdb.hypertable, tsdb.partition_column='id');
   ```

3. **Use unique constraints for business logic uniqueness (must include partition column):**
   ```sql
   ALTER TABLE your_table_name ADD CONSTRAINT unique_entity_time UNIQUE (entity_id, timestamp);
   ```

4. **No primary key (often acceptable for time-series/insert-heavy data):**
   Many insert-heavy use cases don't require strict uniqueness constraints

## Step 2: Configure Compression Policy

Add automatic compression policy (compression settings were configured in Step 1).

**Compress when BOTH criteria are typically met:**
- Most data will not be updated again (some updates/backfill is ok but not regular)
- You no longer need fine-grained B-tree indexes for queries (less common criterion)

**Important:** Adjust the `after` interval based on your update patterns so that most data is updated before it is converted to columnstore.

```sql
-- Adjust 'after' interval based on your update patterns
SELECT add_columnstore_policy('your_table_name', after => INTERVAL '1 day');
```

## Step 3: Set Up Data Retention Policy

Configure automatic data retention based on your specific requirements.

**Important:** Don't guess retention periods - either:
1. Look for user specifications/requirements in the project
2. Ask the user about their data retention needs

If you aren't sure of the data retention period, include the `add_retention_policy` call but you **MUST comment it out**.

**Common patterns (for reference only):**
- **High-frequency IoT data**: 30-90 days to 1 year
- **Financial data**: 7+ years for regulatory compliance  
- **Application metrics**: 30-180 days
- **User analytics**: 1-2 years
- **Log data**: 30-90 days

```sql
-- Example (replace with actual requirements):
SELECT add_retention_policy('your_table_name', INTERVAL '365 days');
```

## Step 4: Create Continuous Aggregates

Set up continuous aggregates for different time granularities:

### Short-term Aggregates (Minutes/Hours)

For high-frequency data (IoT sensors, trading data, application metrics):

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
    STDDEV(value_1) as stddev_value_1,
    SUM(value_2) as sum_value_2,    -- useful for volumes, counts
    AVG(value_3) as avg_value_3
FROM your_table_name
GROUP BY bucket, entity_id, category;
```

### Long-term Aggregates (Days/Weeks)

For trend analysis and reporting:

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
    STDDEV(value_1) as stddev_value_1,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY value_1) as median_value_1,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY value_1) as p95_value_1,
    SUM(value_2) as sum_value_2,
    AVG(value_3) as avg_value_3
FROM your_table_name
GROUP BY bucket, entity_id, category;
```

## Step 5: Configure Continuous Aggregate Policies

Set up refresh policies based on your data freshness requirements.

**Most common case:** No start_offset (refreshes all data as needed)

**Hourly aggregates** - refresh frequently for near real-time dashboards:

```sql
SELECT add_continuous_aggregate_policy('your_table_hourly',
    end_offset => INTERVAL '15 minutes',     -- lag from real-time
    schedule_interval => INTERVAL '15 minutes'); -- how often to refresh
```

**Daily aggregates** - refresh less frequently for reports:

```sql
SELECT add_continuous_aggregate_policy('your_table_daily',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');
```

**Alternative:** Use start_offset only if you don't care about refreshing old data. Example: Only refresh the last 7 days for a high-volume system where users don't care about query result accuracy on older data:

```sql
-- use a start_offset if you don't care about refreshing old data
-- SELECT add_continuous_aggregate_policy('your_table_hourly',
--     start_offset => INTERVAL '7 days',    -- only refresh last 7 days
--     end_offset => INTERVAL '15 minutes',
--     schedule_interval => INTERVAL '15 minutes');
```

## Step 6: Configure Real-Time Aggregation (Optional)

Real-time aggregates combine materialized data with recent raw data at query time. This provides up-to-date results but with slightly higher query cost.

**Note:** In TimescaleDB v2.13+, real-time aggregates are **DISABLED by default**. In earlier versions, they were ENABLED by default.

**Enable real-time aggregation** for more current results:

```sql
ALTER MATERIALIZED VIEW your_table_hourly SET (timescaledb.materialized_only = false);
ALTER MATERIALIZED VIEW your_table_daily SET (timescaledb.materialized_only = false);
```

**Disable real-time aggregation** (materialized data only) for better query performance, at the
cost of not seeing the aggregates for the most recent data:

```sql
-- ALTER MATERIALIZED VIEW your_table_hourly SET (timescaledb.materialized_only = true);
-- ALTER MATERIALIZED VIEW your_table_daily SET (timescaledb.materialized_only = true);
```

**When to use real-time aggregation:**
- Need to query data newer than your refresh policy's end_offset/lag time
- Need up-to-the-minute results in dashboards
- Can tolerate slightly higher query latency
- Want to include the most recent raw data that hasn't been materialized yet

**When to disable real-time aggregation:**
- Performance is more important than data freshness
- Refresh policies provide sufficient data currency
- High query volume where every millisecond matters

## Step 7: Enable Compression on Continuous Aggregates

Compress aggregated data for storage efficiency.

**Rule of thumb:**
- `segment_by` = all GROUP BY columns except time_bucket
- `order_by` = time_bucket DESC

**Compress hourly aggregates:**

```sql
ALTER MATERIALIZED VIEW your_table_hourly SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id, category',  -- all non-time GROUP BY columns
    timescaledb.orderby = 'bucket DESC'             -- time_bucket column
);
SELECT add_columnstore_policy('your_table_hourly', after => INTERVAL '3 days');
```

**Compress daily aggregates:**

```sql
ALTER MATERIALIZED VIEW your_table_daily SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id, category',  -- all non-time GROUP BY columns
    timescaledb.orderby = 'bucket DESC'             -- time_bucket column
);
SELECT add_columnstore_policy('your_table_daily', after => INTERVAL '7 days');
```

## Step 8: Set Retention Policies for Aggregates

Keep aggregates longer than raw data for historical analysis.

**Important:** Base retention periods on user requirements, not guesses. Aggregates are typically kept longer than raw data for historical analysis.

**Common approach:** Aggregates retained 2-5x longer than raw data. Ask user about long-term analytical needs before setting these.

If you aren't sure of the data retention period, include the `add_retention_policy` call but you **MUST comment it out**.

```sql
-- Keep hourly aggregates (example - replace with actual requirements or comment out if you aren't sure)
SELECT add_retention_policy('your_table_hourly', INTERVAL '2 years');

-- Keep daily aggregates for longer-term trends (example - replace with actual requirements or comment out if you aren't sure)  
SELECT add_retention_policy('your_table_daily', INTERVAL '5 years');
```

## Step 9: Create Performance Indexes

Add indexes based on your actual query patterns.

**How to figure out what indexes to create:**
1. Analyze your most common queries against the continuous aggregates
2. Look for WHERE clause patterns in your application code  
3. Create indexes that match your query filters + time ordering

**Common pattern:** `(filter_column, time_bucket DESC)`

This supports queries like: `SELECT ... WHERE entity_id = 'X' AND bucket >= '...' ORDER BY bucket DESC`

**Example indexes on continuous aggregates** (replace with your actual query patterns):

```sql
CREATE INDEX idx_hourly_entity_bucket ON your_table_hourly (entity_id, bucket DESC);
CREATE INDEX idx_hourly_category_bucket ON your_table_hourly (category, bucket DESC);
CREATE INDEX idx_daily_entity_bucket ON your_table_daily (entity_id, bucket DESC);
CREATE INDEX idx_daily_category_bucket ON your_table_daily (category, bucket DESC);
```

**For multi-column filters, create composite indexes:**

Example: if you query `WHERE entity_id = 'X' AND category = 'Y'`
```sql
CREATE INDEX idx_hourly_entity_category_bucket ON your_table_hourly (entity_id, category, bucket DESC);
```

**Important:** Don't create indexes blindly - each index has maintenance overhead. Only create indexes you'll actually use in queries.

## Step 10: Optional Performance Enhancements

### Enable Chunk Skipping for Compressed Data

Enable chunk skipping on compressed chunks to skip entire chunks during queries. This creates min/max indexes that help exclude chunks based on column ranges.

**When to use chunk skipping (in order of importance):**
1. Column values have correlation/ordering within chunks (MOST IMPORTANT)
2. Column is frequently used in WHERE clauses with range queries (>, <, =)

**Best candidates:**
- `updated_at` (when created_at is the partitioning column - they often correlate)
- Sequential IDs or counters
- Any column that tends to have similar values within the same time period

**Example 1:** created_at is the partitioning column, enable chunk skipping on updated_at
```sql
-- This works because records created around the same time often have similar update times
SELECT enable_chunk_skipping('your_table_name', 'updated_at');
```
This allows efficient chunk exclusion: `"WHERE updated_at > '2024-01-01'"` skips chunks where max(updated_at) < '2024-01-01'

**Example 2:** id (serial) is the partitioning column, enable chunk skipping on created_at
```sql
-- This works because sequential IDs are often created around the same time
SELECT enable_chunk_skipping('your_table_name', 'created_at');
```
This allows efficient chunk exclusion: `"WHERE created_at > '2024-01-01'"` skips chunks where max(created_at) < '2024-01-01'

### Add Space-Partitioning (NOT RECOMMENDED)

Space partitioning is generally **NOT RECOMMENDED** for most use cases. It adds complexity and can hurt performance more than it helps.

**Only consider space partitioning if:**
- You have very specific query patterns that ALWAYS filter by the space dimension
- You have expert-level TimescaleDB knowledge
- You've measured that it actually improves your specific workload

**For most users:** stick with time-only partitioning

```sql
-- Example (NOT recommended for typical use):
-- SELECT add_dimension('your_table_name', 'entity_id', number_partitions => 4);
```

## Step 11: Verify Configuration

```sql
-- Check hypertable configuration
SELECT * FROM timescaledb_information.hypertables 
WHERE hypertable_name = 'your_table_name';

-- Verify compression settings
SELECT * FROM timescaledb_information.columnstore_settings 
WHERE hypertable_name LIKE 'your_table%';

-- Check continuous aggregates
SELECT * FROM timescaledb_information.continuous_aggregates;

-- Review all automated policies
SELECT * FROM timescaledb_information.jobs ORDER BY job_id;

-- Monitor chunk information
SELECT chunk_name, table_size, compressed_heap_size, compressed_index_size
FROM timescaledb_information.chunks 
WHERE hypertable_name = 'your_table_name';
```

## Use Case Specific Adaptations

### IoT/Sensor Data
- entity_id → device_id
- category → sensor_type  
- Short chunk intervals (1 hour - 1 day)
- Frequent compression (1-7 days)

### Financial/Trading Data
- entity_id → symbol/instrument
- category → exchange/market
- Very short chunk intervals (1-6 hours)
- Longer retention for compliance
- More percentile aggregations

### Application Metrics/DevOps
- entity_id → service_name/hostname
- category → metric_type
- Medium chunk intervals (1-7 days)
- Focus on percentiles and error rates

### User Analytics
- entity_id → user_id/session_id
- category → event_type
- Variable chunk intervals based on traffic
- Privacy-compliant retention periods

## Performance Guidelines

- **Chunk Size**: Size chunks so that the indexes of all recent hypertable chunks fit within 25% of machine RAM
- **Compression Ratio**: Expect 90%+ compression (10x or better reduction) with properly configured columnstore
- **Query Performance**: Use continuous aggregates for common queries spanning lots of historical data, often used to support user-facing dashboards
- **Memory Usage**: Run `timescaledb-tune` if self-hosting (automatically configured on cloud)

This configuration provides a robust foundation for insert-heavy/analytical workloads with automatic maintenance, optimal query performance, and efficient storage management.

## Schema Design Best Practices

### Column Types and Naming
**❌ Don't use `timestamp` (without time zone)** - Use `timestamptz` instead:
```sql
-- Bad: Stores local time without timezone context
CREATE TABLE sensors (time timestamp, ...); 

-- Good: Stores point-in-time with timezone awareness  
CREATE TABLE sensors (time timestamptz, ...);
```
`timestamptz` records a single moment in time and handles timezone conversions properly. `timestamp` without timezone can cause incorrect arithmetic across time zones and DST changes.

**❌ Don't use `BETWEEN` with timestamps** - Use `>=` and `<` instead:
```sql
-- Bad: Includes exact midnight of end date, may double-count
SELECT * FROM sensors WHERE time BETWEEN '2024-06-01' AND '2024-06-08';

-- Good: Clear exclusive upper bound
SELECT * FROM sensors WHERE time >= '2024-06-01' AND time < '2024-06-08';
```

**❌ Don't use `char(n)` or `varchar(n)` by default** - Use `text` with constraints:
```sql
-- Bad: Fixed padding, arbitrary length limits
device_id char(10), category varchar(50)

-- Good: Flexible length with meaningful constraints  
device_id text CHECK (length(device_id) BETWEEN 3 AND 20),
category text CHECK (category IN ('temperature', 'humidity', 'pressure'))
```

**❌ Don't use uppercase in table/column names** - Use `snake_case`:
```sql
-- Bad: Requires double quotes everywhere
CREATE TABLE DeviceReadings (DeviceId text, ReadingValue float);

-- Good: Natural PostgreSQL style
CREATE TABLE device_readings (device_id text, reading_value float);
```

**❌ Don't use `serial` types** - Use `identity` columns for PostgreSQL 10+:
```sql
-- Bad: Creates hidden sequences with complex dependencies
CREATE TABLE events (id serial primary key, ...);

-- Good: Built-in identity column with bigint (recommended default)
CREATE TABLE events (id bigint generated always as identity primary key, ...);
```

**💡 Use `bigint` for ID columns by default** - Even if you don't expect billions of records:
- `bigint` has no performance penalty over `int` 
- Prevents future migration pain when you exceed 2.1 billion rows
- Time-series and insert-heavy data can accumulate very quickly (millions of IoT readings per day)

**💡 Use `double precision` for floating-point values by default** - Instead of `real` or `float`:
- `double precision` provides 15-17 decimal digits vs 6-7 for `real`
- No significant storage or performance cost for most use cases
- Critical for scientific measurements, financial calculations, and accumulated values
- Time-series aggregations (sums, averages) benefit from higher precision

**❌ Don't use `money` type** - Use `numeric` for monetary values:
```sql
-- Bad: Fixed to database locale, limited precision
price money

-- Good: Precise decimal arithmetic, store currency separately
price numeric(10,2), 
currency text default 'USD'
```

### Query Patterns
**❌ Don't use `NOT IN`** - Use `NOT EXISTS` instead:
```sql
-- Bad: Returns 0 rows if any NULL values present
SELECT * FROM devices WHERE device_id NOT IN (SELECT device_id FROM offline_devices);

-- Good: Handles NULLs correctly and optimizes better
SELECT * FROM devices d 
WHERE NOT EXISTS (SELECT 1 FROM offline_devices o WHERE o.device_id = d.device_id);
```

**❌ Don't use precision specifications like `timestamp(0)`** - Use `date_trunc()` or `time_bucket()`:
```sql
-- Bad: Rounds fractional seconds (can be .5s in future)
time_rounded timestamp(0)  

-- Good: Truncates to desired precision with PostgreSQL date_trunc()
date_trunc('second', timestamp_col) AS time_rounded,

-- Better for TimescaleDB: Use time_bucket() for time-series aggregations
time_bucket(INTERVAL '5 minutes', timestamp_col) AS five_min_bucket,
```

## Using the latest TimescaleDB APIs

This guide uses the NEW TimescaleDB API. Here is a mapping from the old API to the new API:

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

# Questions to ask the user

Ask the following questions if the answers haven't been provided:

- What kind of data will you be storing?
- How do you expect to use the data?
- What kind of queries will you be running?
- How long do you expect to keep the data?
- If the types of column are not clear, ask the user to provide the types of the columns.
