from lars.semantic_sql.sql_macro import execute_sql_fragment, quote_sql_value


def test_execute_sql_fragment_integer_accepts_float_like_string():
    assert execute_sql_fragment("'1.0'", return_type="INTEGER") == 1


def test_quote_sql_value_integer_accepts_float_like_string():
    assert quote_sql_value("10.0", sql_type="INTEGER") == "10"

