-- Sets up database similar to how Tiger Cloud works where we have a
-- tsdbadmin user that is not a superuser.
CREATE ROLE tsdbadmin
WITH
  LOGIN PASSWORD 'password';

CREATE DATABASE tsdb
WITH
  OWNER tsdbadmin;

\c tsdb

CREATE EXTENSION IF NOT EXISTS vector CASCADE;

-- Create schema for docs
CREATE SCHEMA IF NOT EXISTS docs AUTHORIZATION tsdbadmin;
