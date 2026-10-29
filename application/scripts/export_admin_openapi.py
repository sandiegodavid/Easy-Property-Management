"""Deterministic private setup schemas, without a workspace or installed host."""

import json

from app.modules.hosted_admin.application.setup import (
    SetupCommand,
    SetupDirectory,
    SetupOptions,
    SetupView,
)


def specification():
    schemas = {}
    for model in (SetupCommand, SetupDirectory, SetupOptions, SetupView):
        value = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(value.pop("$defs", {}))
        schemas[model.__name__] = value
    return {
        "openapi": "3.1.0",
        "info": {"title": "Private Admin setup", "version": "1"},
        "paths": {},
        "components": {"schemas": schemas},
    }


if __name__ == "__main__":
    print(json.dumps(specification(), indent=2) + "\n", end="")
