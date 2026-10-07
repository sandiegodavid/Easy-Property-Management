from http import HTTPStatus

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.platform.api_errors import register_api_error_handlers


class Payload(BaseModel):
    note: str = Field(max_length=3)


def _client() -> TestClient:
    app = FastAPI()
    register_api_error_handlers(app)

    @app.post("/payload")
    def payload(value: Payload):
        return value

    return TestClient(app)


def test_bounded_request_content_returns_global_413_problem() -> None:
    response = _client().post("/payload", json={"note": "long"})

    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert response.json() == {
        "detail": {
            "code": "request_payload_too_large",
            "message": "Request content exceeds an allowed limit.",
        }
    }


def test_malformed_request_content_returns_global_422_problem() -> None:
    response = _client().post("/payload", json={"note": 1})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json() == {
        "detail": {
            "code": "request_validation",
            "message": "Request validation failed.",
        }
    }
