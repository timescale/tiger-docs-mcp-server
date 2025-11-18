---
name: migrate-postgres-tables-to-hypertables
description: Comprehensive guide for migrating PostgreSQL tables to TimescaleDB hypertables with optimal configuration and performance validation
---

# PostgreSQL to TimescaleDB Hypertable Migration

Migrate identified PostgreSQL tables to TimescaleDB hypertables with optimal configuration, migration planning and validation.

**Prerequisites**: Tables already identified as hypertable candidates (use companion "find-hypertable-candidates" skill if needed).

## Step 1: Optimal Configuration

### Partition Column Selection

```sql
-- Find potential partition columns
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'your_table_name'
  AND data_type IN ('timestamp', 'timestamptz', 'bigint', 'integer', 'date')
ORDER BY ordinal_position;
```

**Requirements:** Time-based (TIMESTAMP/TIMESTAMPTZ/DATE) or sequential integer (INT/BIGINT)

Should represent when the event actually occurred or sequential ordering.

**Common choices:**

- `timestamp`, `created_at`, `event_time` - when event occurred
- `id`, `sequence_number` - auto-increment (for sequential data without timestamps)
- `ingested_at` - less ideal, only if primary query dimension
- `updated_at` - AVOID (records updated out of order, breaks chunk distribution) unless primary query dimension

#### Special Case: table with BOTH ID AND Timestamp

When table has sequential ID (PK) AND timestamp that correlate:

```sql
-- Partition by ID, enable minmax sparse indexes on timestamp
SELECT create_hypertable('orders', 'id', chunk_time_interval => 1000000);
ALTER TABLE orders SET (
    timescaledb.sparse_index = 'minmax(created_at),...'
);
```

Sparse indexes on time column enable skipping compressed blocks outside queried time ranges.

Use when: ID correlates with time (newer records have higher IDs), need ID-based lookups, time queries also common

### Chunk Interval Selection

```sql
-- Ensure statistics are current
ANALYZE your_table_name;

-- Estimate index size per time unit
WITH time_range AS (
    SELECT
        MIN(timestamp_column) as min_time,
        MAX(timestamp_column) as max_time,
        EXTRACT(EPOCH FROM (MAX(timestamp_column) - MIN(timestamp_column)))/3600 as total_hours
    FROM your_table_name
),
total_index_size AS (
    SELECT SUM(pg_relation_size(indexname::regclass)) as total_index_bytes
    FROM pg_stat_user_indexes
    WHERE schemaname||'.'||tablename = 'your_schema.your_table_name'
)
SELECT
    pg_size_pretty(tis.total_index_bytes / tr.total_hours) as index_size_per_hour
FROM time_range tr, total_index_size tis;
```

**Target:** Indexes of recent chunks < 25% of RAM
**Default:** IMPORTANT: Keep default of 7 days if unsure
**Range:** 1 hour minimum, 30 days maximum

**Example:** 32GB RAM → target 8GB for recent indexes. If index_size_per_hour = 200MB:

- 1 hour chunks: 200MB chunk index size × 40 recent = 8GB ✓
- 6 hour chunks: 1.2GB chunk index size × 7 recent = 8.4GB ✓
- 1 day chunks: 4.8GB chunk index size × 2 recent = 9.6GB ⚠️
  Choose largest interval keeping 2+ recent chunk indexes under target.

### Primary Key/ Unique Constraints Compatibility

```sql
-- Check existing primary key/ unique constraints
SELECT conname, pg_get_constraintdef(oid) as definition
FROM pg_constraint
WHERE conrelid = 'your_table_name'::regclass AND contype = 'p' OR contype = 'u';
```

**Rules:** PK/UNIQUE must include partition column

**Actions:**

1. **No PK/UNIQUE:** No changes needed
2. **PK/UNIQUE includes partition column:** No changes needed
3. **PK/UNIQUE excludes partition column:** ⚠️ **ASK USER PERMISSION** to modify PK/UNIQUE

**Example: user prompt if needed:**

> "Primary key (id) doesn't include partition column (timestamp). Must modify to PRIMARY KEY (id, timestamp) to convert to hypertable. This may break application code. Is this acceptable?"
> "Unique constraint (id) doesn't include partition column (timestamp). Must modify to UNIQUE (id, timestamp) to convert to hypertable. This may break application code. Is this acceptable?"

If the user accepts, modify the constraint:

```sql
BEGIN;
ALTER TABLE your_table_name DROP CONSTRAINT existing_pk_name;
ALTER TABLE your_table_name ADD PRIMARY KEY (existing_columns, partition_column);
COMMIT;
```

If the user does not accept, you should NOT migrate the table.

IMPORTANT: DO NOT modify the primary key/unique constraint without user permission.

### Compression Configuration

For detailed segment_by and order_by selection, see "setup-timescaledb-hypertables" skill. Quick reference:

**segment_by:** Most common WHERE filter with >100 rows per value per chunk

- IoT: `device_id`
- Finance: `symbol`
- Analytics: `user_id` or `session_id`

```sql
-- Analyze cardinality for segment_by selection
SELECT column_name, COUNT(DISTINCT column_name) as unique_values,
       ROUND(COUNT(*)::float / COUNT(DISTINCT column_name), 2) as avg_rows_per_value
FROM your_table_name GROUP BY column_name;
```

**order_by:** Usually `timestamp DESC`. The (segment_by, order_by) combination should form a natural time-series progression.

- If column has <100 rows/chunk (too low for segment_by), prepend to order_by: `order_by='low_density_col, timestamp DESC'`

**sparse indexes:** add minmax on the columns that are used in the WHERE clauses but are not in the segment_by or order_by. Use minmax for columns used in range queries.

```sql
ALTER TABLE your_table_name SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id',
    timescaledb.orderby = 'timestamp DESC'
    timescaledb.sparse_index = 'minmax(value_1),...'
);

-- Compress after data unlikely to change (adjust `after` parameter based on update patterns)
CALL add_columnstore_policy('your_table_name', after => INTERVAL '7 days');
```

## Step 2: Migration Planning

### Pre-Migration Checklist

- [ ] Partition column selected
- [ ] Chunk interval calculated (or using default)
- [ ] PK includes partition column OR user approved modification
- [ ] No Hypertable→Hypertable foreign keys
- [ ] Unique constraints include partition column
- [ ] Created compression configuration (segment_by, order_by, sparse indexes, compression policy)
- [ ] Maintenance window scheduled / backup created.

### Migration Options

#### Option 1: In-Place (Tables < 1GB)

```sql
-- Enable extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Convert to hypertable (locks table)
SELECT create_hypertable(
    'your_table_name',
    'timestamp_column',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Configure compression
ALTER TABLE your_table_name SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id',
    timescaledb.orderby = 'timestamp DESC',
    timescaledb.sparse_index = 'minmax(value_1),...'
);

-- Adjust `after` parameter based on update patterns
CALL add_columnstore_policy('your_table_name', after => INTERVAL '7 days');
```

#### Option 2: Blue-Green (Tables > 1GB)

```sql
-- 1. Create new hypertable
CREATE TABLE your_table_name_new (LIKE your_table_name INCLUDING ALL);

-- 2. Convert to hypertable
SELECT create_hypertable('your_table_name_new', 'timestamp_column');

-- 3. Configure compression
ALTER TABLE your_table_name_new SET (
    timescaledb.enable_columnstore,
    timescaledb.segmentby = 'entity_id',
    timescaledb.orderby = 'timestamp DESC'
);

-- 4. Migrate data in batches
INSERT INTO your_table_name_new
SELECT * FROM your_table_name
WHERE timestamp_column >= '2024-01-01' AND timestamp_column < '2024-02-01';
-- Repeat for each time range

-- 4. Enter maintenance window and do the following:

-- 5. Pause modification of the old table.

-- 6. Copy over the most recent data from the old table to the new table.

-- 7. Swap tables
BEGIN;
ALTER TABLE your_table_name RENAME TO your_table_name_old;
ALTER TABLE your_table_name_new RENAME TO your_table_name;
COMMIT;

-- 8. Exit maintenance window.

-- 9. (sometime much later) Drop old table after validation
-- DROP TABLE your_table_name_old;
```

### Common Issues

#### Foreign Keys

```sql
-- Check foreign keys
SELECT conname, confrelid::regclass as referenced_table
FROM pg_constraint
WHERE (conrelid = 'your_table_name'::regclass
    OR confrelid = 'your_table_name'::regclass)
  AND contype = 'f';
```

**Supported:** Plain→Hypertable, Hypertable→Plain
**NOT supported:** Hypertable→Hypertable

⚠️ **CRITICAL:** Hypertable→Hypertable FKs must be dropped (enforce in application). **ASK USER PERMISSION**. If no, **STOP MIGRATION**.

#### Large Table Migration Time

```sql
-- Rough estimate: ~75k rows/second
SELECT
    pg_size_pretty(pg_total_relation_size(tablename)) as size,
    n_live_tup as rows,
    ROUND(n_live_tup / 75000.0 / 60, 1) as estimated_minutes
FROM pg_stat_user_tables
WHERE tablename = 'your_table_name';
```

**Solutions for large tables (>1GB/10M rows):** Use blue-green migration, migrate during off-peak, test on subset first

## Step 3: Performance Validation

### Chunk & Compression Analysis

```sql
-- View chunks and compression
SELECT
    chunk_name,
    pg_size_pretty(total_bytes) as size,
    pg_size_pretty(compressed_total_bytes) as compressed_size,
    ROUND((total_bytes - compressed_total_bytes::numeric) / total_bytes * 100, 1) as compression_pct,
    range_start,
    range_end
FROM timescaledb_information.chunks
WHERE hypertable_name = 'your_table_name'
ORDER BY range_start DESC;
```

**Look for:**

- Consistent chunk sizes (within 2x)
- Compression >90% for time-series
- Recent chunks uncompressed
- Chunk indexes < 25% RAM

### Query Performance Tests

```sql
-- 1. Time-range query (should show chunk exclusion)
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), AVG(value)
FROM your_table_name
WHERE timestamp >= NOW() - INTERVAL '1 day';

-- 2. Entity + time query (benefits from segment_by)
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM your_table_name
WHERE entity_id = 'X' AND timestamp >= NOW() - INTERVAL '1 week';

-- 3. Aggregation (benefits from columnstore)
EXPLAIN (ANALYZE, BUFFERS)
SELECT DATE_TRUNC('hour', timestamp), entity_id, COUNT(*), AVG(value)
FROM your_table_name
WHERE timestamp >= NOW() - INTERVAL '1 month'
GROUP BY 1, 2;
```

**✅ Good signs:**

- "Chunks excluded during startup: X" in EXPLAIN plan
- "Custom Scan (ColumnarScan)" for compressed data
- Lower "Buffers: shared read" in EXPLAIN ANALYZE plan than pre-migration
- Faster execution times

**❌ Bad signs:**

- "Seq Scan" on large chunks
- No chunk exclusion messages
- Slower than before migration

### Storage Metrics

```sql
-- Monitor compression effectiveness
SELECT
    hypertable_name,
    pg_size_pretty(total_bytes) as total_size,
    pg_size_pretty(compressed_total_bytes) as compressed_size,
    ROUND(compressed_total_bytes::numeric / total_bytes * 100, 1) as compressed_pct_of_total,
    ROUND((uncompressed_total_bytes - compressed_total_bytes::numeric) /
          uncompressed_total_bytes * 100, 1) as compression_ratio_pct
FROM timescaledb_information.hypertables
WHERE hypertable_name = 'your_table_name';
```

**Monitor:**

- compression_ratio_pct >90% (typical time-series)
- compressed_pct_of_total growing as data ages
- Size growth slowing significantly vs pre-hypertable
- Decreasing compression_ratio_pct = poor segment_by

### Troubleshooting

#### Poor Chunk Exclusion

```sql
-- Verify chunks are being excluded
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM your_table_name
WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-02';
-- Look for "Chunks excluded during startup: X"
```

#### Poor Compression

```sql
-- Get newest compressed chunk name
SELECT chunk_name FROM timescaledb_information.chunks
WHERE hypertable_name = 'your_table_name'
  AND compressed_total_bytes IS NOT NULL
ORDER BY range_start DESC LIMIT 1;

-- Analyze segment distribution
SELECT segment_by_column, COUNT(*) as rows_per_segment
FROM _timescaledb_internal._hyper_X_Y_chunk  -- Use actual chunk name
GROUP BY 1 ORDER BY 2 DESC;
```

**Look for:** <20 rows per segment: Poor segment_by choice (should be >100) => Low compression potential.

#### Poor insert performance

Check that you don't have too many indexes. Unused indexes hurt insert performance and should be dropped.

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

**Look for:** Unused indexes via a low idx_scan value. Drop such indexes (but ask user permission).

### Ongoing Monitoring

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

**Look for:**

- compression_coverage_pct should increase over time as data ages and gets compressed.
- total_chunks should not grow too quickly (more than 10000 becomes a problem).
- You should not see unexpected spikes in total_size or compressed_size.

## Success Criteria

**✅ Migration successful when:**

- All queries return correct results
- Query performance equal or better
- Compression >90% for older data
- Chunk exclusion working for time queries
- Insert performance acceptable

**❌ Investigate if:**

- Query performance >20% worse
- Compression <80%
- No chunk exclusion
- Insert performance degraded
- Increased error rates

Focus on high-volume, insert-heavy workloads with time-based access patterns for best ROI.
