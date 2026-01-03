from pathlib import Path


def test_match_pair_and_match_template_have_cascades():
    base = Path("traits/semantic_sql")
    assert (base / "match_pair.cascade.yaml").exists()
    assert (base / "match_template.cascade.yaml").exists()

