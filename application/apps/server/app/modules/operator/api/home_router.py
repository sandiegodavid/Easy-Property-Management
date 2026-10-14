"""Typed Home reads execute synchronously in FastAPI's worker boundary."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Query
from pydantic import Field, ValidationError, field_validator, model_validator

from app.modules.operator.application.home_contracts import (
    HomeScope,
    HomeQuery,
    AttentionQuery,
    CollectionQuery,
    HomeResponse,
    AttentionResponse,
    CollectionResponse,
    InventoryQuery,
    HomeInventoryResponse,
)
from app.modules.operator.application.home_service import HomeCompositionService
from app.modules.operator.application.home_vocabulary import Collection
from app.modules.operator.domain.models import Contract, OperatorError, OperatorStorageFailure
from app.modules.portfolio.application.attention_ports import PortfolioAttentionError
from app.platform.api_errors import domain_problem, validation_problem


class ScopeInput(Contract):
    propertyId: UUID | None = None

    def scope(self):
        return HomeScope(
            kind="property" if self.propertyId else "portfolio", property_id=self.propertyId
        )


class HorizonInput(ScopeInput):
    horizonDays: Literal[7, 30, 90] = 7

    @field_validator("horizonDays", mode="before")
    @classmethod
    def query_horizon(cls, value):
        return int(value) if value in ("7", "30", "90") else value


class HomeInput(HorizonInput):
    fromOn: date
    throughOn: date
    limitPerSection: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.fromOn > self.throughOn:
            raise ValueError("Money dates must be ordered.")
        return self


class AttentionInput(ScopeInput):
    limit: int = Field(default=5, ge=1, le=10)


class CollectionInput(HorizonInput):
    collection: Collection
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)


class InventoryInput(ScopeInput):
    occupancy: Literal["vacant", "unknown"]
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)


class HomeProblem(Contract):
    code: str
    message: str


class HomeErrorResponse(Contract):
    detail: HomeProblem


ERRORS = {code: {"model": HomeErrorResponse} for code in (404, 409, 413, 422, 503)}


def _invoke(operation):
    try:
        return operation()
    except (OperatorError, PortfolioAttentionError) as error:
        status = 503 if isinstance(error, OperatorStorageFailure) else error.status_code
        raise domain_problem(error, status_code=status) from error
    except ValidationError as error:
        raise validation_problem(error) from error


def register_home(router, service: HomeCompositionService):
    @router.get(
        "/home/inventory",
        response_model=HomeInventoryResponse,
        operation_id="getOperatorHomeInventory",
        responses=ERRORS,
    )
    def inventory(query: Annotated[InventoryInput, Query()]):
        return _invoke(
            lambda: service.inventory_items(
                InventoryQuery(
                    scope=query.scope(),
                    occupancy=query.occupancy,
                    limit=query.limit,
                    cursor=query.cursor,
                )
            )
        )

    @router.get(
        "/home", response_model=HomeResponse, operation_id="getOperatorHome", responses=ERRORS
    )
    def home(query: Annotated[HomeInput, Query()]):
        return _invoke(
            lambda: service.home(
                HomeQuery(
                    scope=query.scope(),
                    horizon_days=query.horizonDays,
                    from_on=query.fromOn,
                    through_on=query.throughOn,
                    limit_per_section=query.limitPerSection,
                )
            )
        )

    @router.get(
        "/home/attention",
        response_model=AttentionResponse,
        operation_id="getOperatorHomeAttention",
        responses=ERRORS,
    )
    def attention(query: Annotated[AttentionInput, Query()]):
        return _invoke(
            lambda: service.attention(AttentionQuery(scope=query.scope(), limit=query.limit))
        )

    @router.get(
        "/home/items",
        response_model=CollectionResponse,
        operation_id="getOperatorHomeItems",
        responses=ERRORS,
    )
    def items(query: Annotated[CollectionInput, Query()]):
        return _invoke(
            lambda: service.items(
                CollectionQuery(
                    scope=query.scope(),
                    collection=query.collection,
                    horizon_days=query.horizonDays,
                    limit=query.limit,
                    cursor=query.cursor,
                )
            )
        )
