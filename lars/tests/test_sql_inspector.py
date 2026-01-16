from lars.sql_tools.sql_inspector import inspect_sql_query


def test_inspector_finds_semantic_infix_and_function_calls():
    sql = """
    -- @ model: fast
    SELECT
      author_name,
      text,
      SENTIMENT(text) AS tone
    FROM tweets
    WHERE text CONTRADICTS 'SQL is a good interface for LLM applications'
    ORDER BY text RELEVANCE TO 'databases' DESC
    """.strip()

    result = inspect_sql_query(sql)
    calls = result["calls"]

    # Should find CONTRADICTS infix (dynamic cascade operator)
    assert any(c["kind"] == "semantic_infix" and "CONTRADICTS" in (c.get("display") or "") for c in calls)

    # Should find SENTIMENT(...) as a semantic function (scalar cascade operator pattern)
    assert any(c["kind"] == "semantic_function" and (c.get("function") or "").lower().endswith("sentiment_scalar") for c in calls)

    # Should find ORDER BY ... RELEVANCE TO ... clause (semantic_score-backed)
    assert any(c["kind"] == "semantic_infix" and "RELEVANCE TO" in (c.get("display") or "") for c in calls)


def test_inspector_offsets_match_original_substrings():
    sql = "SELECT * FROM docs WHERE title MEANS 'nighttime event'"
    result = inspect_sql_query(sql)
    means = [c for c in result["calls"] if c["kind"] == "semantic_infix" and "MEANS" in (c.get("display") or "")]
    assert means, result
    span = means[0]
    frag = sql[span["start"] : span["end"]]
    assert "MEANS" in frag


def test_inspector_finds_structural_constructs():
    sql = """
    SELECT *
    FROM a
    SEMANTIC JOIN b ON a.title ~ b.title
    GROUP BY MEANING
    """.strip()

    result = inspect_sql_query(sql)
    calls = result["calls"]
    assert any(c["kind"] == "structural" and c["display"] == "SEMANTIC JOIN" for c in calls)
    assert any(c["kind"] == "structural" and c["display"] == "GROUP BY MEANING" for c in calls)

    join = [c for c in calls if c["kind"] == "structural" and c["display"] == "SEMANTIC JOIN"][0]
    assert join.get("expands_to"), join
    assert any((it.get("function") or "").lower() == "semantic_match_pair" for it in join["expands_to"])


def test_inspector_llm_aggregate_includes_mapped_cascade_metadata():
    sql = """
    -- @ model: fast
    SELECT category, SUMMARIZE(review_text) AS s
    FROM reviews
    GROUP BY category
    """.strip()

    result = inspect_sql_query(sql)
    calls = result["calls"]
    agg = [c for c in calls if c["kind"] == "llm_aggregate"]
    assert agg, result
    call = agg[0]
    assert (call.get("function") or "").lower() == "semantic_summarize"
    assert call.get("cascade_id") == "semantic_summarize"
    assert call.get("shape") == "AGGREGATE"
    assert call.get("annotation") and call["annotation"].get("model") == "fast"
