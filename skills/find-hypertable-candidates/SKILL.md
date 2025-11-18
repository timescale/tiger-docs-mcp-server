---
name: find-hypertable-candidates
description: Analyze an existing PostgreSQL database to identify tables that would benefit from conversion to TimescaleDB hypertables
---

# PostgreSQL Hypertable Candidate Analysis

Identify tables that would benefit from TimescaleDB hypertable conversion. After identification, use the companion "migrate-postgres-tables-to-hypertables" skill for configuration and migration.

## TimescaleDB Benefits

**Performance gains:** 90%+ compression, fast time-based queries, improved insert performance, efficient aggregations, continuous aggregates for materialization (dashboards, reports, analytics), automatic data management (retention, compression).

**Best for insert-heavy patterns:**

- Time-series data (sensors, metrics, monitoring)
- Event logs (user events, audit trails, application logs)
- Transaction records (orders, payments, financial)
- Sequential data (auto-incrementing IDs with timestamps)
- Append-only datasets (immutable records, historical)

**Requirements:** Large volumes (1M+ rows), time-based queries, infrequent updates

## Step 1: Database Schema Analysis

### Option A: From Database Connection

#### Table statistics and size

```sql
-- Get all tables with row counts and insert/update patterns
WITH table_stats AS (
    SELECT
        schemaname, tablename,
        n_tup_ins as total_inserts,
        n_tup_upd as total_updates,
        n_tup_del as total_deletes,
        n_live_tup as live_rows,
        n_dead_tup as dead_rows
    FROM pg_stat_user_tables
),
table_sizes AS (
    SELECT
        schemaname, tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
        pg_total_relation_size(schemaname||'.'||tablename) as total_size_bytes
    FROM pg_tables
    WHERE schemaname NOT IN ('information_schema', 'pg_catalog')
)
SELECT
    ts.schemaname, ts.tablename, ts.live_rows,
    tsize.total_size, tsize.total_size_bytes,
    ts.total_inserts, ts.total_updates, ts.total_deletes,
    ROUND(CASE WHEN ts.live_rows > 0
          THEN (ts.total_inserts::float / ts.live_rows) * 100
          ELSE 0 END, 2) as insert_ratio_pct
FROM table_stats ts
JOIN table_sizes tsize ON ts.schemaname = tsize.schemaname AND ts.tablename = tsize.tablename
ORDER BY tsize.total_size_bytes DESC;
```

**Look for:**

- mostly insert-heavy patterns (less updates/deletes)
- big tables (1M+ rows or 100MB+)

#### Index patterns

```sql
-- Identify common query dimensions
SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname NOT IN ('information_schema', 'pg_catalog')
ORDER BY tablename, indexname;
```

**Look for:**

- Multiple indexes with timestamp/created_at columns → time-based queries
- Composite (entity_id, timestamp) indexes → good candidates
- Time-only indexes → time range filtering common

#### Query patterns (if pg_stat_statements available)

```sql
-- Check availability
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements');

-- Analyze expensive queries for candidate tables
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
WHERE query ILIKE '%your_table_name%'
ORDER BY total_exec_time DESC LIMIT 20;
```

**✅ Good patterns:** Time-based WHERE, entity filtering combined with time-based qualifiers, GROUP BY time_bucket, range queries over time
**❌ Poor patterns:** Non-time lookups with no time-based qualifiers in same query (WHERE email = ...)

#### Constraints

```sql
-- Check migration compatibility
SELECT conname, contype, pg_get_constraintdef(oid) as definition
FROM pg_constraint
WHERE conrelid = 'your_table_name'::regclass;
```

**Compatibility:**

- Primary keys (p): Must include partition column or ask user if can be modified
- Foreign keys (f): Plain→Hypertable and Hypertable→Plain OK, Hypertable→Hypertable NOT supported
- Unique constraints (u): Must include partition column or ask user if can be modified
- Check constraints (c): Usually OK

### Option B: From Code Analysis

#### ✅ GOOD Patterns

```python
# Append-only logging
INSERT INTO events (user_id, event_time, data) VALUES (...);
# Time-series collection
INSERT INTO metrics (device_id, timestamp, value) VALUES (...);
# Time-based queries
SELECT * FROM metrics WHERE timestamp >= NOW() - INTERVAL '24 hours';
# Time aggregations
SELECT DATE_TRUNC('day', timestamp), COUNT(*) GROUP BY 1;
```

#### ❌ POOR Patterns

```python
# Frequent updates to historical records
UPDATE users SET email = ..., updated_at = NOW() WHERE id = ...;
# Non-time lookups
SELECT * FROM users WHERE email = ...;
# Small reference tables
SELECT * FROM countries ORDER BY name;
```

#### Schema Indicators

**✅ GOOD:**

- Has timestamp/timestamptz column
- Multiple indexes with timestamp-based columns
- Composite (entity_id, timestamp) indexes

**❌ POOR:**

- Mostly indexes with non-time-based columns (on columns like email, name, status, etc.)
- Columns that you expect to be updated over time (updated_at, updated_by, status, etc.)
- Unique constraints on non-time fields
- Frequent updated_at modifications
- Small static tables

#### Special Case: ID-Based Tables

Sequential ID tables can be candidates if:

- Insert-mostly pattern / updates are either infrequent or only on recent records.
- If updates do happen, they occur on recent records (such as an order status being updated orderered->processing->delivered. Note once an order is delivered, it is unlikely to be updated again.)
- IDs correlate with time (as is the case for serial/auto-incrementing IDs/GENERATED ALWAYS AS IDENTITY)
- ID is the primary query dimension
- Recent data accessed more often (frequently the case in ecommerce, finance, etc.)
- Time-based reporting common (e.g. monthly, daily summaries/analytics)

```sql
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,           -- Can partition by ID
    user_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW() -- For sparse indexes
);
```

Note: For ID-based tables where there is also a time column (created_at, ordered_at, etc.),
you can partition by ID and use sparse indexes on the time column.
See the `migrate-postgres-tables-to-hypertables` skill for details.

## Step 2: Candidacy Scoring (8+ points = good candidate)

### Time-Series Characteristics (5+ points needed)

- Has timestamp/timestamptz column: **3 points**
- Data inserted chronologically: **2 points**
- Queries filter by time: **2 points**
- Time aggregations common: **2 points**

### Scale & Performance (3+ points recommended)

- Large table (1M+ rows or 100MB+): **2 points**
- High insert volume: **1 point**
- Infrequent updates to historical: **1 point**
- Range queries common: **1 point**
- Aggregation queries: **2 points**

### Data Patterns (bonus)

- Contains entity ID for segmentation (device_id, user_id, product_id, symbol, etc.): **1 point**
- Numeric measurements: **1 point**
- Log/event structure: **1 point**

## Common Patterns

### ✅ GOOD Candidates

**✅ Event/Log Tables** (user_events, audit_logs)

```sql
CREATE TABLE user_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    event_type TEXT,
    event_time TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB
);
-- Partition by id, segment by user_id, enable minmax sparse_index on event_time
```

**✅ Sensor/IoT Data** (sensor_readings, telemetry)

```sql
CREATE TABLE sensor_readings (
    device_id TEXT,
    timestamp TIMESTAMPTZ,
    temperature DOUBLE PRECISION,
    humidity DOUBLE PRECISION
);
-- Partition by timestamp, segment by device_id, minmax sparse indexes on temperature and humidity
```

**✅ Financial/Trading** (stock_prices, transactions)

```sql
CREATE TABLE stock_prices (
    symbol VARCHAR(10),
    price_time TIMESTAMPTZ,
    open_price DECIMAL,
    close_price DECIMAL,
    volume BIGINT
);
-- Partition by price_time, segment by symbol, minmax sparse indexes on open_price and close_price and volume
```

**✅ System Metrics** (monitoring_data)

```sql
CREATE TABLE system_metrics (
    hostname TEXT,
    metric_time TIMESTAMPTZ,
    cpu_usage DOUBLE PRECISION,
    memory_usage BIGINT
);
-- Partition by metric_time, segment by hostname, minmax sparse indexes on cpu_usage and memory_usage
```

### ❌ POOR Candidates

**❌ Reference Tables** (countries, categories)

```sql
CREATE TABLE countries (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    code CHAR(2)
);
-- Static data, no time component
```

**❌ User Profiles** (users, accounts)

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255),
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);
-- Accessed by ID, frequently updated, has timestamp but it's not the primary query dimension (the primary query dimension is id or email)
```

**❌ Settings/Config** (user_settings)

```sql
CREATE TABLE user_settings (
    user_id BIGINT PRIMARY KEY,
    theme VARCHAR(20),       -- Changes: light -> dark -> auto
    language VARCHAR(10),    -- Changes: en -> es -> fr
    notifications JSONB,     -- Frequent preference updates
    updated_at TIMESTAMPTZ
);
-- Accessed by user_id, frequently updated, has timestamp but it's not the primary query dimension (the primary query dimension is user_id)
```

## Analysis Output Requirements

For each candidate table provide:

- **Score:** Based on criteria (8+ = strong candidate)
- **Pattern:** Insert vs update ratio
- **Access:** Time-based vs entity lookups
- **Size:** Current size and growth rate
- **Queries:** Time-range, aggregations, point lookups

Focus on insert-heavy patterns with time-based or sequential access. Tables scoring 8+ points are strong candidates for conversion.
