from rvbbit.sql_rewriter import rewrite_rvbbit_syntax


def test_sentiment_aggregate_rewrites_to_semantic_sentiment():
    q = "SELECT state, SENTIMENT_AGG(observed) AS fear FROM bigfoot_vw GROUP BY state"
    rewritten = rewrite_rvbbit_syntax(q)
    assert "semantic_sentiment(to_json(LIST(" in rewritten


def test_sentiment_scalar_is_not_treated_as_llm_aggregate():
    q = "SELECT id, SENTIMENT(observed) AS s FROM bigfoot_vw"
    rewritten = rewrite_rvbbit_syntax(q)
    assert "llm_sentiment_" not in rewritten.lower()
    assert "semantic_sentiment(to_json(LIST(" not in rewritten
    assert "sentiment(" in rewritten.lower()
