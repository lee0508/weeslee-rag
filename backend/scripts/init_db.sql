-- PromptoRAG Database Initialization Script
-- Run this script in MySQL to create the database

-- Create database
CREATE DATABASE IF NOT EXISTS promptorag
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE promptorag;

-- Show confirmation
SELECT 'Database promptorag created successfully!' AS message;
