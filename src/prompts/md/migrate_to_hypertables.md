---
title: PostgreSQL to TimescaleDB Hypertable Migration
description: Comprehensive guide for migrating PostgreSQL tables to TimescaleDB hypertables with optimal configuration and performance validation
---

# PostgreSQL to TimescaleDB Hypertable Migration Guide

A comprehensive scaffold for migrating identified PostgreSQL tables to TimescaleDB hypertables, including optimal configuration, migration planning, and performance validation.

**Prerequisites**: This guide assumes you have already identified which tables should be converted to hypertables. You can use our companion document "Identify Tables That Should Be Hypertables" to help with this analysis, or use any other method to determine suitable candidates before proceeding with this migration guide.

## Step 1: Optimal Configuration

### Partition Column Selection

#### Analyze potential partition columns

```sql
SELECT 
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'your_table_name'
AND data_type IN ('timestamp', 'timestamptz', 'bigint', 'integer', 'date')
ORDER BY ordinal_position;
```

**How to choose partition column:**

The partition column determines how data is divided into chunks over time. This is almost always a timestamp column in time-series workloads.

**Requirements:**
- Must be a time-based column (TIMESTAMP, TIMESTAMPTZ, DATE) or integer (INT, BIGINT)
- Should represent when the event actually occurred or sequential ordering
- Must have good temporal/sequential distribution (not all the same value)

**Common patterns:**
- `timestamp` - when the measurement/event happened
- `created_at` - when the record was created
- `event_time` - when the business event occurred
- `ingested_at` - when data entered the system (less ideal)
- `id` - autoincrement integer key (for sequential data without timestamps)
- `sequence_number` - monotonically increasing integer

**⚠️ Avoid using `updated_at` as partition column:**
- Records can be updated out of time order
- Creates uneven chunk distribution
- Breaks time-based query optimization

**Use `updated_at` only if:**
- It's your primary query dimension
- You rarely query by creation time
- Update patterns are predictable and time-ordered

**Special case: Tables with both ID primary key AND time column**

When you have a table with both sequential ID and timestamp where they're correlated:
1. partition by ID
2. enable chunk skipping on the time column

```sql
-- Example: Convert table with ID PK + timestamp to hypertable partitioned by ID
SELECT create_hypertable(
    'orders', 
    'id',                           -- Partition by ID (primary key)
    chunk_time_interval => 1000000  -- Number of IDs per chunk
);

-- Enable chunk skipping on the time column for time-based query optimization
SELECT enable_chunk_skipping('orders', 'created_at');
```

**How the chunk skipping works:**
- This tracks min/max created_at values per chunk, allowing TimescaleDB to skip chunks that don't contain data in the queried time range
- ID and created_at are correlated - newer IDs have newer timestamps
- Time-based queries can now skip chunks efficiently even though partitioned by ID

**Use this approach when:**
- Table has both sequential ID primary key AND timestamp column
- ID values correlate with time (newer records have higher IDs)
- You need to maintain existing ID-based lookups
- Time-based queries are also common

### Chunk Interval Selection

#### Estimate optimal chunk interval

```sql
-- First, ensure table statistics are up to date
ANALYZE your_table_name;

-- Estimate index size per hour (assumes uniform distribution, no full table scan)
WITH time_range AS (
    SELECT 
        MIN(timestamp_column) as min_time,
        MAX(timestamp_column) as max_time,
        EXTRACT(EPOCH FROM (MAX(timestamp_column) - MIN(timestamp_column)))/3600 as total_hours
    FROM your_table_name 
),
total_index_size AS (
    SELECT 
        SUM(pg_relation_size(indexname::regclass)) as total_index_bytes
    FROM pg_stat_user_indexes 
    WHERE schemaname||'.'||tablename = 'your_schema.your_table_name'
)
SELECT 
    pg_size_pretty(tis.total_index_bytes / tr.total_hours) as estimated_index_size_per_hour
FROM time_range tr, total_index_size tis;
```

**Chunk interval selection guidelines:**

**Target:** Size chunks so that the indexes of all recent hypertable chunks fit within 25% of machine RAM

**Constraints:** Never go below 1 hour or above 30 days

**⚠️ Important:** If you don't have access to the database, can't run the analysis above, or don't have reliable information about RAM/data patterns, keep the default chunk size (7 days). The default is well-tested and works for most use cases.

**Example calculation (only if you have good data):**
- If you have 32GB RAM, target 8GB for recent chunk indexes (25% of 32GB)
- If estimated_index_size_per_hour = 200MB, then:
  - 1 hour chunks: ~200MB per chunk (40 recent chunks = 8GB) ✓
  - 6 hour chunks: ~1.2GB per chunk (7 recent chunks = 8.4GB) ✓
  - 1 day chunks: ~4.8GB per chunk (2 recent chunks = 9.6GB) ⚠️
- Choose the largest interval that keeps recent indexes under your RAM target
- If RAM allows for >30 day chunks, cap at 30 days (too large creates maintenance issues)
- If RAM requires <1 hour chunks, use 1 hour minimum (smaller chunks create overhead)

### Primary Key Considerations

#### Check primary key compatibility

```sql
-- Check existing primary key constraints
SELECT 
    conname,
    pg_get_constraintdef(oid) as definition
FROM pg_constraint 
WHERE conrelid = 'your_table_name'::regclass 
AND contype = 'p';
```

**⚠️ Important: Primary Key Rules for Hypertable Migration**

Any existing primary key or unique index **MUST include the partitioning column**.

**Migration strategy:**

1. **If table has NO primary key:** Don't add one (many time-series use cases don't need PKs)

2. **If existing PK INCLUDES the partitioning column:** No changes needed
   - Example: PK(id) and partitioning by 'id' ✓
   - Example: PK(entity_id, timestamp) and partitioning by 'timestamp' ✓

3. **If existing PK does NOT include partitioning column:** **REQUIRES USER PERMISSION**
   - Example: PK(id) but partitioning by 'timestamp' ❌
   
   **⚠️ ASK USER:** "The existing primary key (id) doesn't include the partitioning column (timestamp). To convert to hypertable, I need to modify the primary key to include both columns: PRIMARY KEY (id, timestamp). This may break existing application code. Is this acceptable?"
   
   - **If YES:** Modify PK to include partitioning column
     ```sql
     -- DROP CONSTRAINT existing_pk_name;
     -- ALTER TABLE your_table_name ADD PRIMARY KEY (existing_columns, partition_column);
     ```
   
   - **If NO:** Cannot convert to hypertable. Consider using a different partitioning column that's already in the PK, or removing the PK constraint if business logic allows.

**❌ DO NOT modify primary keys without explicit user permission.**

### Compression Configuration

#### Segment-by Column Selection

```sql
-- Analyze cardinality of potential segment columns
SELECT 
    'entity_id' as column_name,
    COUNT(DISTINCT entity_id) as unique_values,
    COUNT(*) as total_rows,
    ROUND(COUNT(*)::float / COUNT(DISTINCT entity_id), 2) as avg_rows_per_value
FROM your_table_name
UNION ALL
SELECT 
    'category',
    COUNT(DISTINCT category),
    COUNT(*),
    ROUND(COUNT(*)::float / COUNT(DISTINCT category), 2)
FROM your_table_name;
```

**How to choose segment_by column:**

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

**❌ Bad choices for segment_by:**
- Timestamp columns (already time-partitioned)
- Unique identifiers (transaction_id, uuid fields)
- Columns with low row density (<100 rows per value per chunk)
- Columns rarely used in filtering
- Multiple columns (creates too many small segments)

#### Order-by Column Selection

**How to choose order_by column:**

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

**⚠️ Important:** When a column can't be used in segment_by due to low row density, consider prepending it to order_by to preserve natural progression:

**Example:** metric_name has only 20 rows per chunk (too low for segment_by)
- `segment_by='service_name'` (has >100 rows per chunk)
- `order_by='metric_name, timestamp DESC'`

This creates natural progression within each service: all temperature readings together, then all pressure readings, etc. Values are more similar when grouped by metric type, improving compression.

**Advanced:** Append columns that benefit from min/max indexing for query optimization. After the natural progression columns, you can append additional columns that:
- Are frequently used in WHERE clauses for filtering
- Have some correlation with the main progression
- Can help exclude compressed chunks during queries

**Example:** `created_at DESC, updated_at DESC`
- created_at provides the main natural progression
- updated_at is appended because it often correlates and is used for filtering
- TimescaleDB tracks min/max of updated_at per compressed chunk
- Queries like "WHERE updated_at > '2024-01-01'" can exclude entire compressed batches

**Other examples:**
- `timestamp DESC, price DESC` (for financial data where price filters are common)
- `timestamp DESC, severity DESC` (for logs where severity filtering is frequent)

**❌ Bad choices for order_by:**
- Random columns that break natural progression
- Columns that create high variance between adjacent rows
- Columns unrelated to the segment_by grouping

#### Apply Compression Settings

```sql
-- Configure compression settings for optimal performance
ALTER TABLE your_table_name SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id',     -- Use analysis results above
    timescaledb.orderby = 'timestamp DESC'   -- Use guidance above
);
```

#### Add Compression Policy

**Compress when BOTH criteria are typically met:**
- Most data will not be updated again (some updates/backfill is ok but not regular)
- You no longer need fine-grained B-tree indexes for queries (less common criterion)

**⚠️ Important:** Adjust the `after` interval based on your update patterns so that most data is updated before it is converted to columnstore.

```sql
-- Adjust 'after' interval based on your update patterns
SELECT add_columnstore_policy(
    'your_table_name', 
    after => INTERVAL '7 days'  -- Adjust based on how often you update existing data
);
```

## Step 2: Migration Planning

### Pre-Migration Checklist

**Before proceeding with migration, ensure you've completed the analysis from previous sections:**

- [ ] **Prerequisites**: Analyzed database schema and identified candidate tables (from companion analysis document)
- [ ] **Prerequisites**: Scored table candidacy (8+ points recommended) (from companion analysis document) 
- [ ] **Step 1**: Determined optimal configuration:
  - [ ] Selected partition column
  - [ ] Calculated chunk interval based on RAM constraints
  - [ ] Verified primary key compatibility (or got user permission for changes)
  - [ ] Analyzed segment_by and order_by columns for compression

**Migration Readiness Check:**
- [ ] Primary key includes partition column OR table has no primary key OR user approved PK modification
- [ ] No Hypertable→Hypertable foreign key constraints (other FK types are supported)
- [ ] Unique constraints include partition column OR can be dropped
- [ ] Application can handle any required constraint changes
- [ ] Have a rollback plan and maintenance window scheduled

### Migration Strategy Options

#### Option 1: In-Place Conversion (Small Tables < 1GB)

```sql
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Convert existing table to hypertable
-- WARNING: This locks the table during conversion
SELECT create_hypertable(
    'your_table_name', 
    'timestamp_column',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Add compression settings (optional)
ALTER TABLE your_table_name SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id_column',
    timescaledb.orderby = 'timestamp DESC'
);
```

**Add compression policy:**

**Compress when BOTH criteria are typically met:**
- (a) Most data will not be updated again (some updates/backfill is ok but not regular)
- (b) You no longer need fine-grained B-tree indexes for queries (less common criterion)

**⚠️ Important:** Adjust the `after` interval based on your update patterns so that most data is updated before it is converted to columnstore.

```sql
-- Adjust 'after' interval based on your update patterns
SELECT add_columnstore_policy('your_table_name', after => INTERVAL '1 days');
```

#### Option 2: Blue-Green Migration (Large Tables > 1GB)

```sql
-- 1. Create new hypertable with same schema
CREATE TABLE your_table_name_new (
    -- Copy exact schema from original table
);

-- 2. Convert to hypertable
SELECT create_hypertable(
    'your_table_name_new', 
    'timestamp_column',
    chunk_time_interval => INTERVAL '1 day'
);

-- 3. Configure compression
ALTER TABLE your_table_name_new SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id',
    timescaledb.orderby = 'timestamp DESC'
);

SELECT add_columnstore_policy('your_table_name_new', after => INTERVAL '1 days');

-- 4. Migrate data in chunks (adjust date ranges)
INSERT INTO your_table_name_new
SELECT * FROM your_table_name
WHERE timestamp_column >= '2024-01-01' 
AND timestamp_column < '2024-02-01';

-- Repeat for each month/chunk...

-- 5. Switch tables during maintenance window
BEGIN;
ALTER TABLE your_table_name RENAME TO your_table_name_old;
ALTER TABLE your_table_name_new RENAME TO your_table_name;
COMMIT;

-- 6. Update application and drop old table after validation
-- DROP TABLE your_table_name_old; -- Only after confirming everything works
```

### Common Migration Issues and Solutions

#### Issue 1: Foreign Key Constraints

```sql
-- Check existing foreign keys
SELECT 
    conname,
    confrelid::regclass as referenced_table,
    conrelid::regclass as referencing_table,
    pg_get_constraintdef(oid) as definition
FROM pg_constraint 
WHERE (conrelid = 'your_table_name'::regclass 
    OR confrelid = 'your_table_name'::regclass)
AND contype = 'f';
```

**Foreign key support patterns:**
- ✅ **Plain table → Hypertable** (supported)
- ✅ **Hypertable → Plain table** (supported)
- ❌ **Hypertable → Hypertable** (NOT supported)

**If you have Hypertable→Hypertable FKs, you must:**
1. Drop the FK constraint before migration
2. Enforce referential integrity at application level
3. Consider denormalizing if the relationship is critical

#### Issue 2: Unique Constraints

```sql
-- Check unique constraints that don't include partition column
SELECT 
    conname,
    pg_get_constraintdef(oid) as definition
FROM pg_constraint 
WHERE conrelid = 'your_table_name'::regclass 
AND contype = 'u'
AND NOT EXISTS (
    -- Check if partition column is part of unique constraint
    SELECT 1 FROM pg_attribute pa 
    WHERE pa.attrelid = conrelid 
    AND pa.attname = 'partition_column_name'
    AND pa.attnum = ANY(conkey)
);

-- SOLUTION: Add partition column to unique constraints
ALTER TABLE your_table_name 
DROP CONSTRAINT constraint_name,
ADD CONSTRAINT constraint_name_new 
UNIQUE (existing_columns, partition_column);
```

#### Issue 3: Table Size and Downtime

```sql
-- Estimate migration time (rough calculation)
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
    n_live_tup as estimated_rows,
    -- Very rough estimate: 50k-100k rows per second for hypertable conversion
    ROUND(n_live_tup / 75000.0 / 60, 1) as estimated_minutes
FROM pg_stat_user_tables 
WHERE tablename = 'your_table_name';
```

**Solutions for large tables (>1GB or >10M rows):**
1. Use blue-green migration (Option 2 above)
2. Migrate data in chunks during off-peak hours
3. Consider read replicas to minimize read downtime
4. Test migration on a copy/subset first

## Step 3: Performance Validation

### Post-Migration Monitoring

#### Chunk and Compression Analysis

```sql
-- View hypertable chunk information
SELECT 
    chunk_schema,
    chunk_name,
    pg_size_pretty(total_bytes) as size,
    pg_size_pretty(compressed_total_bytes) as compressed_size,
    ROUND(
        (total_bytes - compressed_total_bytes::numeric) / total_bytes * 100, 1
    ) as compression_ratio_pct,
    range_start,
    range_end
FROM timescaledb_information.chunks 
WHERE hypertable_name = 'your_table_name'
ORDER BY range_start DESC
LIMIT 10;
```

**What to look for:**
1. Chunk sizes should be relatively consistent (within 2x of each other)
2. Compression ratios should be 90%+ for typical time-series workloads
3. Recent chunks should be uncompressed, older chunks compressed
4. Chunk indexes should fit within your RAM constraints (target 25% of machine RAM for recent chunks)

#### Query Performance Testing

**Test common query patterns and compare performance:**

**1. Time-range queries (should be fast with chunk exclusion):**
```sql
EXPLAIN (ANALYZE, BUFFERS) 
SELECT COUNT(*), AVG(value_column) 
FROM your_table_name 
WHERE timestamp_column >= NOW() - INTERVAL '1 day';
```

**2. Segment-filtered queries (should benefit from compression segment_by):**
```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM your_table_name 
WHERE entity_id = 'specific_entity' 
AND timestamp_column >= NOW() - INTERVAL '1 week';
```

**3. Aggregation queries (should benefit from columnstore compression):**
```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT 
    DATE_TRUNC('hour', timestamp_column) as hour,
    entity_id,
    COUNT(*), 
    AVG(value_column)
FROM your_table_name 
WHERE timestamp_column >= NOW() - INTERVAL '1 month'
GROUP BY 1, 2
ORDER BY 1 DESC;
```

**Performance indicators:**
- ✅ "Chunks excluded during startup" message in EXPLAIN output
- ✅ Lower "Buffers: shared read" values compared to pre-migration
- ✅ "Custom Scan (ColumnarScan)" for compressed data access
- ✅ Execution time improvements for time-range and aggregation queries
- ❌ "Seq Scan" on large chunks (indicates poor chunk exclusion)
- ❌ Higher execution times than before migration

#### Storage and Compression Metrics

```sql
-- Monitor compression effectiveness over time
SELECT 
    hypertable_schema,
    hypertable_name,
    pg_size_pretty(total_bytes) as total_size,
    pg_size_pretty(compressed_total_bytes) as compressed_size,
    pg_size_pretty(uncompressed_total_bytes) as uncompressed_size,
    ROUND(
        compressed_total_bytes::numeric / total_bytes * 100, 1
    ) as compressed_pct_of_total,
    ROUND(
        (uncompressed_total_bytes - compressed_total_bytes::numeric) / 
        uncompressed_total_bytes * 100, 1
    ) as compression_ratio_pct
FROM timescaledb_information.hypertables h
LEFT JOIN timescaledb_information.compression_settings cs ON h.hypertable_name = cs.hypertable_name
WHERE h.hypertable_name = 'your_table_name';
```

**What to monitor:**
- `compression_ratio_pct` should be 90%+ for typical time-series workloads
- `compressed_pct_of_total` should grow over time as data ages and gets compressed
- Total size growth should slow significantly compared to pre-hypertable
- Watch for `compression_ratio_pct` decreasing (may indicate poor segment_by choice)

### Performance Optimization

#### Troubleshooting Poor Performance

**1. Check if chunks are being excluded properly (when queries are too slow):**

Look for "Chunks excluded during startup: X" in query plans:
```sql
EXPLAIN (ANALYZE, BUFFERS) 
SELECT * FROM your_table_name 
WHERE timestamp_column >= '2024-01-01' 
AND timestamp_column < '2024-01-02';
```

**2. Analyze segment_by column distribution in a compressed chunk (when compression ratio is poor):**

First, get the newest compressed chunk name:
```sql
SELECT chunk_name, range_start, range_end 
FROM timescaledb_information.chunks 
WHERE hypertable_name = 'your_table_name' 
AND compressed_total_bytes IS NOT NULL  -- Only compressed chunks
ORDER BY range_start DESC 
LIMIT 1;
```

Then analyze segment distribution in that specific compressed chunk:
```sql
SELECT 
    segment_by_column,
    COUNT(*) as rows_in_chunk
FROM _timescaledb_internal._hyper_X_Y_chunk  -- Replace with actual chunk name from above
GROUP BY 1 
ORDER BY 2 DESC;
```

**What to look for:**
- segment_by values should have substantial row counts (>100 rows per value is good)
- Very low row counts indicate poor compression potential
- Very high row counts from single values may indicate good compression candidates

**3. Check index usage patterns (when inserts are slow - unused indexes should be dropped):**
```sql
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_tup_read,
    idx_tup_fetch,
    idx_scan
FROM pg_stat_user_indexes 
WHERE tablename LIKE '%your_table_name%'
ORDER BY idx_scan DESC;
```

**Optimization actions:**
- If compression ratio is <90%: Review segment_by and order_by choices
- If chunk exclusion isn't working: Check time-based WHERE clauses
- If queries are slow: Consider additional indexes on frequently filtered columns
- If inserts are slow: Check chunk_time_interval size (may be too large)

#### Ongoing Monitoring

```sql
-- Monitor chunk compression status
CREATE OR REPLACE VIEW hypertable_compression_status AS
SELECT 
    h.hypertable_name,
    COUNT(c.chunk_name) as total_chunks,
    COUNT(c.chunk_name) FILTER (WHERE c.compressed_total_bytes IS NOT NULL) as compressed_chunks,
    ROUND(
        COUNT(c.chunk_name) FILTER (WHERE c.compressed_total_bytes IS NOT NULL)::numeric / 
        COUNT(c.chunk_name) * 100, 1
    ) as compression_coverage_pct,
    pg_size_pretty(SUM(c.total_bytes)) as total_size,
    pg_size_pretty(SUM(c.compressed_total_bytes)) as compressed_size
FROM timescaledb_information.hypertables h
LEFT JOIN timescaledb_information.chunks c ON h.hypertable_name = c.hypertable_name
GROUP BY h.hypertable_name;

-- Query this view regularly to monitor compression progress
SELECT * FROM hypertable_compression_status 
WHERE hypertable_name = 'your_table_name';
```

### Migration Success Criteria

**Consider the migration successful when:**

- [ ] **Functional**: All application queries work correctly with same results
- [ ] **Performance**: Query performance is equal or better than pre-migration
- [ ] **Storage**: Compression is achieving expected ratios (90%+ for time-series)
- [ ] **Chunk Management**: Chunks are appropriately sized and distributed
- [ ] **Monitoring**: Can track compression progress and query performance over time

**Red flags requiring investigation:**
- [ ] Query performance regression >20%
- [ ] Compression ratios <80%
- [ ] Chunk exclusion not working for time-based queries
- [ ] Insert performance significantly slower
- [ ] Error rates increased post-migration

Focus on tables with clear insert-heavy patterns, substantial data volumes, and time-based query access patterns. The investment in converting to hypertables pays off most when you have genuine high-volume workloads at scale with time-correlated access patterns.