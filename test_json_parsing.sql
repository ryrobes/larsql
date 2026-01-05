-- Test different ways to parse JSON array
CREATE TEMP TABLE test_data AS
SELECT '[{"id": "1", "text": "hello", "score": 0.9}, {"id": "2", "text": "world", "score": 0.8}]' AS json_str;

-- Method 1: read_json with format
SELECT * FROM read_json((SELECT json_str FROM test_data), format='array');

-- Method 2: read_json_auto
SELECT * FROM read_json_auto((SELECT json_str FROM test_data));
