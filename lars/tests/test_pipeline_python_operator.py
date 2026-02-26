import pytest

from lars.pipeline_tools import python_transform


def test_python_transform_dataframe_result():
    rows = [
        {"a": 1, "b": 2},
        {"a": 3, "b": 4},
    ]

    out = python_transform(
        code='result = df.assign(total=df["a"] + df["b"])',
        _table=rows,
        _table_columns=["a", "b"],
    )

    assert "data" in out
    assert len(out["data"]) == 2
    assert out["data"][0]["total"] == 3
    assert out["data"][1]["total"] == 7


def test_python_transform_defaults_to_df_when_result_not_set():
    rows = [{"x": 10}, {"x": 20}]

    out = python_transform(
        code='df["x2"] = df["x"] * 2',
        _table=rows,
        _table_columns=["x"],
    )

    assert len(out["data"]) == 2
    assert out["data"][0]["x2"] == 20
    assert out["data"][1]["x2"] == 40


def test_python_transform_context_is_available():
    out = python_transform(
        code='result = {"stage": context.get("stage_index"), "rows": len(df)}',
        _table=[{"x": 1}, {"x": 2}, {"x": 3}],
        _table_columns=["x"],
        _pipeline_context={"stage_index": 2},
    )

    assert out["data"] == [{"stage": 2, "rows": 3}]


def test_python_transform_rejects_invalid_result_type():
    with pytest.raises(ValueError, match="result must be"):
        python_transform(
            code="result = 42",
            _table=[{"x": 1}],
            _table_columns=["x"],
        )


def test_python_transform_requires_non_empty_code():
    with pytest.raises(ValueError, match="non-empty code"):
        python_transform(
            code="   ",
            _table=[{"x": 1}],
            _table_columns=["x"],
        )
