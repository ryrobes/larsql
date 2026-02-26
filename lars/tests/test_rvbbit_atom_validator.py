import json

from lars.skills.rvbbit_atom import valid_rvbbit_atom


def _atom(**overrides):
    atom = {
        "intent": "Show top states by sightings",
        "title": "Top States",
        "summary": "Top states by sighting count",
        "sql": "SELECT state, COUNT(*) AS sightings_count FROM csv_files.bigfoot_sightings GROUP BY state",
        "displayType": "barChart",
        "gridSize": "medium",
        "detectedDimensions": ["state"],
        "verified": True,
        "displayHints": {"x": "state", "y": "sightings_count"},
    }
    atom.update(overrides)
    return atom


def _safe_sql_run_output(row_count=3):
    return [
        {
            "tool": "safe_sql_run",
            "result": json.dumps(
                {
                    "row_count": row_count,
                    "columns": ["state", "sightings_count"],
                    "results": [{"state": "WA", "sightings_count": 12}],
                }
            ),
        }
    ]


def test_valid_rvbbit_atom_accepts_valid_atom_scope_payload():
    payload = {"atoms": [_atom()]}
    result = valid_rvbbit_atom(
        content=json.dumps(payload),
        scope="atom",
        tool_outputs=_safe_sql_run_output(row_count=5),
    )
    assert result["valid"] is True


def test_valid_rvbbit_atom_parses_markdown_fenced_json():
    payload = {"atoms": [_atom()]}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    result = valid_rvbbit_atom(
        content=fenced,
        scope="atom",
        tool_outputs=_safe_sql_run_output(row_count=1),
    )
    assert result["valid"] is True


def test_valid_rvbbit_atom_returns_schema_error_for_missing_required_field():
    payload = {"atoms": [_atom(title=None)]}
    result = valid_rvbbit_atom(
        content=json.dumps(payload),
        scope="atom",
        tool_outputs=_safe_sql_run_output(row_count=2),
    )
    assert result["valid"] is False
    assert "Schema errors:" in result["reason"]
    assert "title" in result["reason"]


def test_valid_rvbbit_atom_rejects_invalid_scope_shape():
    payload = {"atoms": [_atom(), _atom(title="Second", intent="Show trend over time", displayType="lineChart")]}
    result = valid_rvbbit_atom(
        content=json.dumps(payload),
        scope="atom",
        tool_outputs=_safe_sql_run_output(row_count=4),
    )
    assert result["valid"] is False
    assert "Scope=atom requires exactly 1 atom." in result["reason"]


def test_valid_rvbbit_atom_requires_successful_safe_sql_run_for_verified_atoms():
    payload = {"atoms": [_atom()]}
    result = valid_rvbbit_atom(
        content=json.dumps(payload),
        scope="atom",
        tool_outputs=[{"tool": "safe_sql_run", "result": json.dumps({"status": "error", "row_count": 0, "error": "bad sql"})}],
    )
    assert result["valid"] is False
    assert "successful safe_sql_run" in result["reason"]


def test_valid_rvbbit_atom_grid_scope_requires_verified_atom():
    payload = {"atoms": [_atom(verified=False)]}
    result = valid_rvbbit_atom(
        content=json.dumps(payload),
        scope="grid",
        tool_outputs=[],
    )
    assert result["valid"] is False
    assert "Scope=grid requires at least one verified atom." in result["reason"]
