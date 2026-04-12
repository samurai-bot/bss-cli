"""TMF622 ProductOrder Pydantic schemas — camelCase for API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from bss_models.order_mgmt import OrderItem, ProductOrder

ORDER_PATH = "/tmf-api/productOrderingManagement/v4/productOrder"


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    customer_id: str
    offering_id: str
    msisdn_preference: str | None = None
    notes: str | None = None


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    action: str
    offering_id: str
    state: str | None = None
    target_subscription_id: str | None = None


class ProductOrderResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    href: str
    customer_id: str
    state: str
    order_date: datetime | None = None
    requested_completion_date: datetime | None = None
    completed_date: datetime | None = None
    msisdn_preference: str | None = None
    notes: str | None = None
    items: list[OrderItemResponse] = []
    at_type: str = Field(default="ProductOrder", serialization_alias="@type")


def to_order_item_response(item: OrderItem) -> OrderItemResponse:
    return OrderItemResponse(
        id=item.id,
        action=item.action,
        offering_id=item.offering_id,
        state=item.state,
        target_subscription_id=item.target_subscription_id,
    )


def to_product_order_response(order: ProductOrder) -> ProductOrderResponse:
    return ProductOrderResponse(
        id=order.id,
        href=f"{ORDER_PATH}/{order.id}",
        customer_id=order.customer_id,
        state=order.state,
        order_date=order.order_date,
        requested_completion_date=order.requested_completion_date,
        completed_date=order.completed_date,
        msisdn_preference=order.msisdn_preference,
        notes=order.notes,
        items=[to_order_item_response(i) for i in order.items] if order.items else [],
    )
