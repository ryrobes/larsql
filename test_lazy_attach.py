from rvbbit.sql_tools.lazy_attach import extract_any_dotted_prefixes, extract_relation_qualified_names


def test_extract_relation_qualified_names_basic():
    sql = "SELECT * FROM prod_db.public.users LIMIT 1"
    assert extract_relation_qualified_names(sql) == [["prod_db", "public", "users"]]


def test_extract_relation_qualified_names_multiple_relations():
    sql = """
    SELECT u.id, o.id
    FROM prod_db.public.users u
    JOIN analytics_db.public.orders o ON o.user_id = u.id
    WHERE u.id > 10
    """
    assert extract_relation_qualified_names(sql) == [
        ["prod_db", "public", "users"],
        ["analytics_db", "public", "orders"],
    ]


def test_extract_relation_qualified_names_quoted_identifiers():
    sql = 'SELECT * FROM "prod_db"."public"."users"'
    assert extract_relation_qualified_names(sql) == [["prod_db", "public", "users"]]


def test_extract_relation_qualified_names_ignores_string_literals():
    sql = "SELECT 'prod_db.public.users' AS x"
    assert extract_relation_qualified_names(sql) == []


def test_extract_any_dotted_prefixes_only_leftmost():
    sql = "SELECT prod_db.public.users.id, analytics_db.public.orders.total"
    assert extract_any_dotted_prefixes(sql) == {"prod_db", "analytics_db"}

