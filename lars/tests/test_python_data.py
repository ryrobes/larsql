from lars.skills.data_tools import python_data


def test_python_data_helper_functions_share_execution_namespace():
    """Functions defined in the snippet should be able to call each other."""
    code = """
def _strip_fence(text):
    return text.strip()

def _parse_json_like(text):
    return _strip_fence(text)

result = _parse_json_like("  ok  ")
"""
    out = python_data(code=code, _outputs={}, _state={}, _input={})

    assert out["_route"] == "success"
    assert out["type"] == "scalar"
    assert out["result"] == "ok"


def test_python_data_result_can_use_defined_helper_chain():
    code = """
def add_one(x):
    return x + 1

def add_two(x):
    return add_one(add_one(x))

result = add_two(5)
"""
    out = python_data(code=code, _outputs={}, _state={}, _input={})

    assert out["_route"] == "success"
    assert out["result"] == 7
