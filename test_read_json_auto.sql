-- Test if read_json_auto works with JSON string directly
SELECT * FROM read_json_auto('[{"id": "1", "text": "test", "score": 0.9}]');
