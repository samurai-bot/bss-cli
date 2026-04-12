"""TMF629 Customer Management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_customer_service
from app.schemas.tmf.customer import (
    AddContactMediumRequest,
    ContactMediumSchema,
    CreateCustomerRequest,
    Tmf629Customer,
    UpdateCustomerRequest,
    to_tmf629_customer,
)
from app.services.customer_service import CustomerService

router = APIRouter(tags=["TMF629 Customer"])


@router.post("/customer", response_model=Tmf629Customer, response_model_by_alias=True, status_code=201)
async def create_customer(
    body: CreateCustomerRequest,
    svc: CustomerService = Depends(get_customer_service),
) -> Tmf629Customer:
    cust = await svc.create_customer(
        given_name=body.given_name,
        family_name=body.family_name,
        date_of_birth=body.date_of_birth,
        contact_mediums=[cm.model_dump() if hasattr(cm, "model_dump") else cm for cm in body.contact_medium],
    )
    cust = await svc.get_customer(cust.id)
    return to_tmf629_customer(cust)


@router.get("/customer", response_model=list[Tmf629Customer], response_model_by_alias=True)
async def list_customers(
    status: str | None = None,
    name: str | None = None,
    limit: int = 20,
    offset: int = 0,
    svc: CustomerService = Depends(get_customer_service),
) -> list[Tmf629Customer]:
    custs = await svc.list_customers(
        status=status, name_contains=name, limit=limit, offset=offset
    )
    return [to_tmf629_customer(c) for c in custs]


@router.get("/customer/{customer_id}", response_model=Tmf629Customer, response_model_by_alias=True)
async def get_customer(
    customer_id: str,
    svc: CustomerService = Depends(get_customer_service),
) -> Tmf629Customer:
    cust = await svc.get_customer(customer_id)
    if not cust:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    return to_tmf629_customer(cust)


@router.patch("/customer/{customer_id}", response_model=Tmf629Customer, response_model_by_alias=True)
async def update_customer(
    customer_id: str,
    body: UpdateCustomerRequest,
    svc: CustomerService = Depends(get_customer_service),
) -> Tmf629Customer:
    updates = body.model_dump(exclude_none=True)
    cust = await svc.update_customer(customer_id, **updates)
    cust = await svc.get_customer(cust.id)
    return to_tmf629_customer(cust)


@router.post(
    "/customer/{customer_id}/contactMedium",
    response_model=ContactMediumSchema,
    response_model_by_alias=True,
    status_code=201,
)
async def add_contact_medium(
    customer_id: str,
    body: AddContactMediumRequest,
    svc: CustomerService = Depends(get_customer_service),
) -> ContactMediumSchema:
    cm = await svc.add_contact_medium(
        customer_id,
        medium_type=body.medium_type,
        value=body.value,
        is_primary=body.is_primary,
    )
    return ContactMediumSchema(
        id=cm.id,
        medium_type=cm.medium_type,
        value=cm.value,
        is_primary=cm.is_primary,
        valid_from=cm.valid_from,
    )


@router.delete("/customer/{customer_id}/contactMedium/{cm_id}", status_code=204)
async def remove_contact_medium(
    customer_id: str,
    cm_id: str,
    svc: CustomerService = Depends(get_customer_service),
) -> None:
    await svc.remove_contact_medium(customer_id, cm_id)
