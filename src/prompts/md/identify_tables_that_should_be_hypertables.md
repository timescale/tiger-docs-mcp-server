---
name: identifyHypertableCandidates
title: PostgreSQL Hypertable Candidate Analysis
description: Analyze an existing PostgreSQL database to identify tables that would benefit from conversion to TimescaleDB hypertables
---

# PostgreSQL Hypertable Candidate Analysis Guide

You are tasked with analyzing an existing PostgreSQL database to identify tables that would benefit from conversion to TimescaleDB hypertables. This guide provides comprehensive analysis criteria and scoring methodology to identify optimal candidates for hypertable migration.

**Next Steps**: After identifying candidate tables with this document, use the companion "PostgreSQL to TimescaleDB Hypertable Migration Guide" to complete the optimal configuration, migration planning, and performance validation steps.

## Analysis Overview

TimescaleDB hypertables provide significant performance benefits including:

- **90%+ compression** for insert-heavy data using columnstore compression
- **Fast time-based queries** through automatic chunk exclusion
- **Improved insert performance** by partitioning large tables into smaller chunks
- **Efficient aggregations** over time windows with compressed data
- **Continuous aggregates** for pre-calculating and materializing complex time-based aggregations (dashboards, reports, analytics)
- **Automatic data management** with policies for compression and retention

These benefits are most effective for tables with:
- **Insert-heavy data patterns** where data is inserted but rarely changed, including:
  - Time-series data (sensors, metrics, system monitoring)
  - Event logs (user events, audit trails, application logs)
  - Transaction records (orders, payments, financial transactions)
  - Sequential data (records with auto-incrementing IDs and timestamps)
  - Append-only datasets (immutable records, historical data)
- Large data volumes (millions+ rows)
- Frequent time-based queries

## Step 1: Database Schema Analysis

### Option A: From Database Connection

```sql
-- Get all tables with their row counts and key statistics
WITH table_stats AS (
    SELECT 
        schemaname,
        tablename,
        n_tup_ins as total_inserts,
        n_tup_upd as total_updates,
        n_tup_del as total_deletes,
        n_live_tup as live_rows,
        n_dead_tup as dead_rows,
        last_vacuum,
        last_autovacuum,
        last_analyze,
        last_autoanalyze
    FROM pg_stat_user_tables
),
table_sizes AS (
    SELECT 
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
        pg_total_relation_size(schemaname||'.'||tablename) as total_size_bytes
    FROM pg_tables 
    WHERE schemaname NOT IN ('information_schema', 'pg_catalog')
)
SELECT 
    ts.schemaname,
    ts.tablename,
    ts.live_rows,
    tsize.total_size,
    tsize.total_size_bytes,
    ts.total_inserts,
    ts.total_updates,
    ts.total_deletes,
    ROUND(
        CASE 
            WHEN ts.live_rows > 0 
            THEN (ts.total_inserts::float / ts.live_rows) * 100 
            ELSE 0 
        END, 2
    ) as insert_ratio_pct
FROM table_stats ts
JOIN table_sizes tsize ON ts.schemaname = tsize.schemaname AND ts.tablename = tsize.tablename
ORDER BY tsize.total_size_bytes DESC;

-- Analyze index patterns to identify common query dimensions
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes 
WHERE schemaname NOT IN ('information_schema', 'pg_catalog')
ORDER BY tablename, indexname;

-- Look for patterns like:
-- - Multiple indexes containing timestamp/created_at columns (suggests time-based queries)
-- - Composite indexes with (entity_id, timestamp) pattern (good hypertable candidates)
-- - Time-only indexes (indicates time range filtering is common)

-- Also analyze actual query patterns if pg_stat_statements is available
SELECT EXISTS (
    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
) as has_pg_stat_statements;

-- If available, analyze most expensive queries for candidate tables
SELECT 
    query,
    calls,
    mean_exec_time,
    total_exec_time
FROM pg_stat_statements 
WHERE query ILIKE '%your_table_name%'
ORDER BY total_exec_time DESC
LIMIT 20;

-- What to look for in query patterns:
-- - Time-based WHERE clauses (WHERE timestamp >= ...) ✅ Good
-- - Entity-based filtering (WHERE device_id = ...) ✅ Good  
-- - Aggregation queries (GROUP BY time_bucket(...)) ✅ Good
-- - Range queries over time periods ✅ Good
-- - Non-time-based lookups (WHERE email = ...) ❌ Poor

-- Check all constraints for migration compatibility
SELECT 
    conname,
    contype,
    pg_get_constraintdef(oid) as definition
FROM pg_constraint 
WHERE conrelid = 'your_table_name'::regclass;

-- Migration compatibility notes:
-- - Primary keys (p): Must include partition column or get user permission to modify
-- - Foreign keys (f): Plain→Hypertable and Hypertable→Plain FKs are supported
--   Only Hypertable→Hypertable FKs are NOT supported - check if any target tables are also hypertables
-- - Unique constraints (u): Must include partition column or can be dropped
-- - Check constraints (c): Usually no issues
```

### Option B: From Code Analysis

When analyzing existing application code without database access, look for these patterns:

**✅ GOOD Hypertable Candidates - Code Patterns:**

```python
# PATTERN 1: Append-only logging/events
def log_user_event(user_id, event_type, metadata):
    db.execute("""
        INSERT INTO user_events (user_id, event_type, event_time, metadata)
        VALUES (%s, %s, NOW(), %s)
    """, [user_id, event_type, metadata])
    # ✅ Only INSERTs, no UPDATEs to historical records

# PATTERN 2: Sensor/metrics collection  
def record_sensor_reading(device_id, temperature, humidity):
    db.execute("""
        INSERT INTO sensor_readings (device_id, timestamp, temperature, humidity)
        VALUES (%s, %s, %s, %s)
    """, [device_id, datetime.now(), temperature, humidity])
    # ✅ Time-series data, chronological inserts

# PATTERN 3: Time-based queries dominate
def get_recent_metrics(device_id, hours=24):
    return db.query("""
        SELECT * FROM system_metrics 
        WHERE device_id = %s 
          AND timestamp >= NOW() - INTERVAL '%s hours'
        ORDER BY timestamp DESC
    """, [device_id, hours])
    # ✅ Queries filter by time ranges

# PATTERN 4: Aggregations over time windows
def daily_summary(start_date, end_date):
    return db.query("""
        SELECT 
            DATE_TRUNC('day', event_time) as day,
            COUNT(*) as events,
            COUNT(DISTINCT user_id) as unique_users
        FROM user_events
        WHERE event_time BETWEEN %s AND %s
        GROUP BY 1 ORDER BY 1
    """, [start_date, end_date])
    # ✅ Time-bucket aggregations
```

**❌ POOR Hypertable Candidates - Code Patterns:**

```python
# ANTI-PATTERN 1: Frequent UPDATEs to historical records
def update_user_profile(user_id, email, name):
    db.execute("""
        UPDATE users 
        SET email = %s, name = %s, updated_at = NOW()
        WHERE id = %s
    """, [email, name, user_id])
    # ❌ Updates historical records frequently

# ANTI-PATTERN 2: Non-time-based access patterns
def get_user_by_email(email):
    return db.query("SELECT * FROM users WHERE email = %s", [email])
    # ❌ Queries by email, not time ranges

# ANTI-PATTERN 3: Frequent updates to many fields
def update_user_preferences(user_id, theme, language, notifications):
    db.execute("""
        UPDATE user_settings 
        SET theme = %s, language = %s, notifications = %s, updated_at = NOW()
        WHERE user_id = %s
    """, [theme, language, notifications, user_id])
    # ❌ Frequent updates to multiple fields, not append-mostly pattern

# ANTI-PATTERN 4: Small reference data
def get_all_countries():
    return db.query("SELECT * FROM countries ORDER BY name")
    # ❌ Static reference data, small table
```

**Schema Definition Analysis:**

Look for these patterns in CREATE TABLE statements and index definitions:

```sql
-- ✅ GOOD: Time-series schema patterns
CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    event_type VARCHAR(50),
    timestamp TIMESTAMPTZ DEFAULT NOW(),  -- Time column
    session_id UUID,
    data JSONB                           -- Flexible payload
);
-- ✅ Has timestamp, likely append-only based on schema

-- ❌ POOR: Mutable entity schemas  
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE,           -- Queries by email
    password_hash VARCHAR(255),
    name VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active', -- Status changes
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW() -- Frequent updates
);
-- ❌ Profile data, accessed by email/id, not time

-- ❌ POOR: Frequently Updated Settings/Configuration
CREATE TABLE user_settings (
    user_id BIGINT PRIMARY KEY,
    theme VARCHAR(20),       -- Changes: light -> dark -> auto
    language VARCHAR(10),    -- Changes: en -> es -> fr
    notifications JSONB,     -- Frequent preference updates
    updated_at TIMESTAMPTZ
);
-- ❌ NO: Settings data frequently updated, accessed by user_id not time

-- ✅ GOOD: Index patterns indicating hypertable candidates
CREATE INDEX idx_events_user_time ON events (user_id, event_time DESC);
CREATE INDEX idx_events_time ON events (event_time DESC);
CREATE INDEX idx_events_type_time ON events (event_type, event_time DESC);
-- ✅ Multiple indexes contain event_time - suggests frequent time-based queries

-- ❌ POOR: Index patterns suggesting non-time-series access
CREATE INDEX idx_users_email ON users (email);
CREATE INDEX idx_users_name ON users (name);
CREATE INDEX idx_users_status ON users (status);
-- ❌ No time-based indexes - suggests lookup by attributes, not time ranges
```

**Index Analysis Guidelines:**

When examining CREATE INDEX statements in migrations or schema files:

- ✅ **Good hypertable indicators:**
  - Multiple indexes containing timestamp columns
  - Composite indexes with (entity_id, timestamp) patterns
  - Time-only indexes (e.g., `CREATE INDEX ... ON table (created_at DESC)`)
  - Range-based indexes (e.g., covering recent time periods)

- ❌ **Poor hypertable indicators:**
  - Most indexes are on non-time columns (email, name, status)
  - Unique indexes on non-time fields
  - Foreign key indexes pointing to reference tables
  - Complex multi-column indexes without time dimensions

**⚠️ SPECIAL CASE: ID-Based Tables with Time-Series Characteristics**

Some tables with sequential ID primary keys can still be good hypertable candidates if they exhibit insert-heavy patterns with time-correlated access:

```sql
-- ✅ POTENTIAL CANDIDATE: Sequential ID tables
CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,              -- Sequential ID
    user_id BIGINT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    total_amount DECIMAL(10,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),  -- Time column for partitioning
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_orders_created_at ON orders (created_at);     -- Time-based queries
CREATE INDEX idx_orders_user_recent ON orders (user_id, created_at DESC); -- Recent orders per user
```

**ID-Based Table Candidacy Criteria:**
- ✅ **Insert-mostly pattern**: Orders rarely updated after initial creation
- ✅ **Lookups mostly by ID**: `SELECT * FROM orders WHERE id = ?` dominates
- ✅ **Recency bias**: Recent orders accessed more than old ones
- ✅ **Time-based reporting**: Monthly/daily order summaries common
- ✅ **Sequential ID growth**: IDs correlate with time (newer records = higher IDs)

**Code patterns that suggest ID-based tables are good candidates:**

```python
# GOOD: Insert-heavy, query by ID, recency bias
def create_order(user_id, items):
    order_id = db.execute("""
        INSERT INTO orders (user_id, total_amount, created_at)
        VALUES (%s, %s, NOW()) RETURNING id
    """, [user_id, calculate_total(items)])
    # ✅ Mostly INSERTs

def get_order(order_id):
    return db.query("SELECT * FROM orders WHERE id = %s", [order_id])
    # ✅ Lookup by ID (can use both ID and time partitions)

def get_recent_orders(user_id, days=30):
    return db.query("""
        SELECT * FROM orders 
        WHERE user_id = %s AND created_at >= NOW() - INTERVAL '%s days'
        ORDER BY created_at DESC
    """, [user_id, days])
    # ✅ Recency bias - query recent data more often

def daily_order_stats(start_date, end_date):
    return db.query("""
        SELECT DATE_TRUNC('day', created_at) as day, 
               COUNT(*), SUM(total_amount)
        FROM orders 
        WHERE created_at BETWEEN %s AND %s
        GROUP BY 1
    """, [start_date, end_date])
    # ✅ Time-based aggregations
```

**Note**: For ID-based tables where ID correlates with time, you can partition by ID and use chunk skipping on the time column. See the migration guide for implementation details.

## Step 2: Hypertable Candidacy Assessment

### High Priority Candidates

Tables scoring 8+ points from this criteria:

**Time-Series Characteristics (Required - 5+ points needed)**
- ✅ **Has timestamp/timestamptz column** (3 points)
- ✅ **Data inserted chronologically** (2 points) 
- ✅ **Queries frequently filter by time** (2 points)
- ✅ **Time-based aggregations common** (2 points)

**Scale & Performance Benefits (3+ points recommended)**
- ✅ **Large table (1M+ rows or 100MB+)** (2 points)
- ✅ **High insert volume** (1 point)
- ✅ **Infrequent updates to historical data** (1 point)
- ✅ **Range queries common** (1 point)
- ✅ **Aggregation queries over time windows** (2 points)

**Data Patterns (Bonus points)**
- ✅ **Contains device/sensor/user ID for segmentation** (1 point)
- ✅ **Numeric measurements/values** (1 point)
- ✅ **Log/event data structure** (1 point)

### Common Candidate Table Types

```sql
-- PATTERN 1: Event/Log Tables
-- Examples: user_events, application_logs, audit_logs
CREATE TABLE user_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    event_type VARCHAR(50),
    event_time TIMESTAMPTZ DEFAULT NOW(),
    session_id UUID,
    metadata JSONB
);
-- ✅ HYPERTABLE CANDIDATE: id partition (correlated with event_time), user_id segment
-- Use: SELECT create_hypertable('user_events', 'id'); 
--      SELECT enable_chunk_skipping('user_events', 'event_time');

-- PATTERN 2: Sensor/IoT Data
-- Examples: sensor_readings, device_telemetry, measurements
CREATE TABLE sensor_readings (
    device_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,        -- ✅ PARTITION CANDIDATE  
    temperature DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    location POINT
);
-- ✅ HYPERTABLE CANDIDATE: timestamp partition, device_id segment

-- PATTERN 3: Financial/Trading Data
-- Examples: stock_prices, transactions, market_data
CREATE TABLE stock_prices (
    symbol VARCHAR(10) NOT NULL,
    price_time TIMESTAMPTZ NOT NULL,       -- ✅ PARTITION CANDIDATE
    open_price DECIMAL(10,2),
    close_price DECIMAL(10,2),
    volume BIGINT
);
-- ✅ HYPERTABLE CANDIDATE: price_time partition, symbol segment

-- PATTERN 4: Performance Metrics
-- Examples: system_metrics, application_metrics, monitoring_data
CREATE TABLE system_metrics (
    hostname VARCHAR(100),
    metric_time TIMESTAMPTZ NOT NULL,      -- ✅ PARTITION CANDIDATE
    cpu_usage DOUBLE PRECISION,
    memory_usage BIGINT,
    disk_io BIGINT
);
-- ✅ HYPERTABLE CANDIDATE: metric_time partition, hostname segment
```

### Tables to AVOID Converting

**❌ Poor Candidates (0-3 points)**
- Reference/lookup tables (countries, categories, settings)
- User profiles/account data (mostly static)
- Small tables (<100k rows, <10MB)
- Frequently updated historical records
- Tables without time-based access patterns
- Configuration/metadata tables

```sql
-- ANTI-PATTERN 1: Reference Tables
CREATE TABLE countries (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    code CHAR(2)
);
-- ❌ NO: Static reference data, no time component

-- ANTI-PATTERN 2: User Profiles  
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255),
    created_at TIMESTAMPTZ,  -- Has timestamp but...
    updated_at TIMESTAMPTZ   -- Frequently updated, not time-series access
);
-- ❌ NO: Profile data accessed by user_id, not time ranges

-- ANTI-PATTERN 3: Frequently Updated Settings/Configuration
CREATE TABLE user_settings (
    user_id BIGINT PRIMARY KEY,
    theme VARCHAR(20),       -- Changes: light -> dark -> auto
    language VARCHAR(10),    -- Changes: en -> es -> fr
    notifications JSONB,     -- Frequent preference updates
    updated_at TIMESTAMPTZ
);
-- ❌ NO: Settings data frequently updated, accessed by user_id not time
```

## Key Information to Highlight in Analysis

For each candidate table, ensure your analysis covers:

**Essential Scoring Information:**
- Candidacy score based on the criteria above (8+ points indicates strong candidate)
- Insert vs update patterns (append-only is ideal)
- Data access patterns (time-based queries vs entity lookups)
- Table size and growth rate
- Query types (time-range filters, aggregations, point lookups)

**Hypertable Suitability Assessment:**
- Time-series characteristics (timestamp columns, chronological data)
- Scale benefits (large tables with high insert volume)
- Query optimization potential (time-based filtering, aggregations)
- Data pattern alignment (sensor data, logs, events, sequential records)

Focus on tables with insert-heavy patterns (time-series, event logs, transaction records, sequential data), large data volumes, and time-based or sequential query access. Tables scoring 8+ points are strong candidates for hypertable conversion.