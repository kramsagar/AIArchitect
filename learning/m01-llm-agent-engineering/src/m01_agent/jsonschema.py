"""Turn a Pydantic model into an OpenAI *strict* JSON schema (function calling + structured outputs).

Strict mode requires: every object has `additionalProperties: false`, every property is listed in
`required` (optional values are expressed as a nullable type instead) and no `default` keywords.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = copy.deepcopy(model.model_json_schema())
    _make_strict(schema)
    for sub in schema.get("$defs", {}).values():
        _make_strict(sub)
    return schema


def _make_strict(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("title", None)
        node.pop("default", None)
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        for key, value in list(node.items()):
            if key != "$defs":
                _make_strict(value)
    elif isinstance(node, list):
        for item in node:
            _make_strict(item)
