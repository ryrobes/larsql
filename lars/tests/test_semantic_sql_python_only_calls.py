from pathlib import Path


def test_match_pair_and_match_template_have_cascades():
    base = Path(__file__).parent.parent / "lars" / "builtin_cascades" / "semantic_sql"
    assert (base / "match_pair.cascade.yaml").exists()
    assert (base / "match_template.cascade.yaml").exists()

