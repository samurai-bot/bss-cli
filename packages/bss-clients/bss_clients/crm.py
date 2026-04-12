"""CRMClient — service-to-service client for CRM (port 8002).

Covers TMF629 customer, TMF621 trouble ticket, TMF683 interaction,
plus the custom /crm-api/v1/ surface for case, KYC, and agent.
"""

from __future__ import annotations

from typing import Any

from .auth import AuthProvider
from .base import BSSClient


class CRMClient(BSSClient):
    """Client for the CRM service (port 8002)."""

    def __init__(
        self,
        base_url: str = "http://crm:8000",
        auth_provider: AuthProvider | None = None,
        timeout: float = 5.0,
    ):
        super().__init__(base_url, auth_provider, timeout)

    # ── Customer (TMF629) ────────────────────────────────────────────────

    async def create_customer(
        self,
        *,
        name: str,
        email: str | None = None,
        phone: str | None = None,
    ) -> dict[str, Any]:
        """POST /tmf-api/customerManagement/v4/customer."""
        contact_mediums = []
        if email:
            contact_mediums.append(
                {"mediumType": "email", "characteristic": {"emailAddress": email}}
            )
        if phone:
            contact_mediums.append(
                {"mediumType": "mobile", "characteristic": {"phoneNumber": phone}}
            )
        body: dict[str, Any] = {"name": name}
        if contact_mediums:
            body["contactMedium"] = contact_mediums
        resp = await self._request(
            "POST",
            "/tmf-api/customerManagement/v4/customer",
            json=body,
        )
        return resp.json()

    async def get_customer(self, customer_id: str) -> dict[str, Any]:
        """GET /tmf-api/customerManagement/v4/customer/{id}."""
        resp = await self._request(
            "GET", f"/tmf-api/customerManagement/v4/customer/{customer_id}"
        )
        return resp.json()

    async def list_customers(
        self,
        *,
        state: str | None = None,
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /tmf-api/customerManagement/v4/customer."""
        params: dict[str, Any] = {}
        if state:
            params["status"] = state
        if name_contains:
            params["name"] = name_contains
        resp = await self._request(
            "GET",
            "/tmf-api/customerManagement/v4/customer",
            params=params,
        )
        return resp.json()

    async def update_customer(
        self, customer_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH /tmf-api/customerManagement/v4/customer/{id}."""
        resp = await self._request(
            "PATCH",
            f"/tmf-api/customerManagement/v4/customer/{customer_id}",
            json=patch,
        )
        return resp.json()

    async def add_contact_medium(
        self,
        customer_id: str,
        *,
        medium_type: str,
        value: str,
    ) -> dict[str, Any]:
        """POST /tmf-api/customerManagement/v4/customer/{id}/contactMedium."""
        if medium_type == "email":
            characteristic = {"emailAddress": value}
        elif medium_type == "mobile":
            characteristic = {"phoneNumber": value}
        else:
            characteristic = {"value": value}
        resp = await self._request(
            "POST",
            f"/tmf-api/customerManagement/v4/customer/{customer_id}/contactMedium",
            json={"mediumType": medium_type, "characteristic": characteristic},
        )
        return resp.json()

    async def remove_contact_medium(
        self, customer_id: str, medium_id: str
    ) -> dict[str, Any]:
        """DELETE /tmf-api/customerManagement/v4/customer/{id}/contactMedium/{cm}."""
        resp = await self._request(
            "DELETE",
            f"/tmf-api/customerManagement/v4/customer/{customer_id}/contactMedium/{medium_id}",
        )
        return resp.json() if resp.content else {"id": medium_id, "removed": True}

    async def close_customer(self, customer_id: str) -> dict[str, Any]:
        """PATCH customer with status=closed (policy-gated)."""
        return await self.update_customer(customer_id, {"status": "closed"})

    # ── KYC ──────────────────────────────────────────────────────────────

    async def attest_kyc(
        self,
        customer_id: str,
        *,
        provider: str,
        attestation_token: str,
    ) -> dict[str, Any]:
        """POST /crm-api/v1/customer/{id}/kyc-attestation."""
        resp = await self._request(
            "POST",
            f"/crm-api/v1/customer/{customer_id}/kyc-attestation",
            json={"provider": provider, "attestationToken": attestation_token},
        )
        return resp.json()

    async def get_kyc_status(self, customer_id: str) -> dict[str, Any]:
        """GET /crm-api/v1/customer/{id}/kyc-status."""
        resp = await self._request(
            "GET", f"/crm-api/v1/customer/{customer_id}/kyc-status"
        )
        return resp.json()

    # ── Case (/crm-api/v1/case) ──────────────────────────────────────────

    async def open_case(
        self,
        *,
        customer_id: str,
        subject: str,
        category: str,
        priority: str,
    ) -> dict[str, Any]:
        """POST /crm-api/v1/case."""
        resp = await self._request(
            "POST",
            "/crm-api/v1/case",
            json={
                "customerId": customer_id,
                "subject": subject,
                "category": category,
                "priority": priority,
            },
        )
        return resp.json()

    async def get_case(self, case_id: str) -> dict[str, Any]:
        """GET /crm-api/v1/case/{id}."""
        resp = await self._request("GET", f"/crm-api/v1/case/{case_id}")
        return resp.json()

    async def list_cases(
        self,
        *,
        customer_id: str | None = None,
        state: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /crm-api/v1/case."""
        params: dict[str, Any] = {}
        if customer_id:
            params["customerId"] = customer_id
        if state:
            params["state"] = state
        if agent_id:
            params["agentId"] = agent_id
        resp = await self._request("GET", "/crm-api/v1/case", params=params)
        return resp.json()

    async def add_case_note(self, case_id: str, *, body: str) -> dict[str, Any]:
        """POST /crm-api/v1/case/{id}/note."""
        resp = await self._request(
            "POST",
            f"/crm-api/v1/case/{case_id}/note",
            json={"body": body},
        )
        return resp.json()

    async def update_case(
        self, case_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH /crm-api/v1/case/{id}."""
        resp = await self._request(
            "PATCH", f"/crm-api/v1/case/{case_id}", json=patch
        )
        return resp.json()

    async def transition_case(
        self, case_id: str, *, to_state: str
    ) -> dict[str, Any]:
        """PATCH case with state transition."""
        return await self.update_case(case_id, {"state": to_state})

    async def update_case_priority(
        self, case_id: str, *, priority: str
    ) -> dict[str, Any]:
        """PATCH case priority."""
        return await self.update_case(case_id, {"priority": priority})

    async def close_case(
        self, case_id: str, *, resolution_code: str
    ) -> dict[str, Any]:
        """POST /crm-api/v1/case/{id}/close — policy-gated."""
        resp = await self._request(
            "POST",
            f"/crm-api/v1/case/{case_id}/close",
            json={"resolutionCode": resolution_code},
        )
        return resp.json()

    # ── Ticket (TMF621) ──────────────────────────────────────────────────

    async def open_ticket(
        self,
        *,
        ticket_type: str,
        subject: str,
        case_id: str | None = None,
        customer_id: str | None = None,
        order_id: str | None = None,
        subscription_id: str | None = None,
        service_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /tmf-api/troubleTicket/v4/troubleTicket."""
        body: dict[str, Any] = {
            "ticketType": ticket_type,
            "subject": subject,
        }
        relates = []
        if case_id:
            relates.append({"entityType": "case", "id": case_id})
        if customer_id:
            relates.append({"entityType": "customer", "id": customer_id})
        if order_id:
            relates.append({"entityType": "order", "id": order_id})
        if subscription_id:
            relates.append({"entityType": "subscription", "id": subscription_id})
        if service_id:
            relates.append({"entityType": "service", "id": service_id})
        if relates:
            body["relatedEntity"] = relates
        resp = await self._request(
            "POST", "/tmf-api/troubleTicket/v4/troubleTicket", json=body
        )
        return resp.json()

    async def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        """GET /tmf-api/troubleTicket/v4/troubleTicket/{id}."""
        resp = await self._request(
            "GET", f"/tmf-api/troubleTicket/v4/troubleTicket/{ticket_id}"
        )
        return resp.json()

    async def list_tickets(
        self,
        *,
        customer_id: str | None = None,
        case_id: str | None = None,
        state: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /tmf-api/troubleTicket/v4/troubleTicket."""
        params: dict[str, Any] = {}
        if customer_id:
            params["customerId"] = customer_id
        if case_id:
            params["caseId"] = case_id
        if state:
            params["state"] = state
        if agent_id:
            params["agentId"] = agent_id
        resp = await self._request(
            "GET", "/tmf-api/troubleTicket/v4/troubleTicket", params=params
        )
        return resp.json()

    async def assign_ticket(
        self, ticket_id: str, *, agent_id: str
    ) -> dict[str, Any]:
        """PATCH troubleTicket with assignedAgent."""
        resp = await self._request(
            "PATCH",
            f"/tmf-api/troubleTicket/v4/troubleTicket/{ticket_id}",
            json={"assignedAgent": agent_id},
        )
        return resp.json()

    async def transition_ticket(
        self, ticket_id: str, *, to_state: str
    ) -> dict[str, Any]:
        """POST /tmf-api/troubleTicket/v4/troubleTicket/{id}/transition."""
        resp = await self._request(
            "POST",
            f"/tmf-api/troubleTicket/v4/troubleTicket/{ticket_id}/transition",
            json={"toState": to_state},
        )
        return resp.json()

    async def resolve_ticket(
        self, ticket_id: str, *, resolution_notes: str
    ) -> dict[str, Any]:
        """POST /tmf-api/troubleTicket/v4/troubleTicket/{id}/resolve."""
        resp = await self._request(
            "POST",
            f"/tmf-api/troubleTicket/v4/troubleTicket/{ticket_id}/resolve",
            json={"resolutionNotes": resolution_notes},
        )
        return resp.json()

    async def close_ticket(self, ticket_id: str) -> dict[str, Any]:
        """Transition ticket → closed."""
        return await self.transition_ticket(ticket_id, to_state="closed")

    async def cancel_ticket(self, ticket_id: str) -> dict[str, Any]:
        """POST /tmf-api/troubleTicket/v4/troubleTicket/{id}/cancel — destructive."""
        resp = await self._request(
            "POST", f"/tmf-api/troubleTicket/v4/troubleTicket/{ticket_id}/cancel"
        )
        return resp.json()

    # ── Interaction (TMF683) ─────────────────────────────────────────────

    async def log_interaction(
        self,
        *,
        customer_id: str,
        channel: str,
        action: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """POST /tmf-api/customerInteractionManagement/v1/interaction."""
        body: dict[str, Any] = {
            "customerId": customer_id,
            "channel": channel,
            "action": action,
        }
        if note:
            body["note"] = note
        resp = await self._request(
            "POST",
            "/tmf-api/customerInteractionManagement/v1/interaction",
            json=body,
        )
        return resp.json()

    async def list_interactions(
        self, customer_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """GET /tmf-api/customerInteractionManagement/v1/interaction."""
        resp = await self._request(
            "GET",
            "/tmf-api/customerInteractionManagement/v1/interaction",
            params={"customerId": customer_id, "limit": limit},
        )
        return resp.json()

    # ── Agent ────────────────────────────────────────────────────────────

    async def list_agents(
        self, *, state: str | None = None
    ) -> list[dict[str, Any]]:
        """GET /crm-api/v1/agent."""
        params: dict[str, Any] = {}
        if state:
            params["state"] = state
        resp = await self._request("GET", "/crm-api/v1/agent", params=params)
        return resp.json()

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """GET /crm-api/v1/agent/{id}."""
        resp = await self._request("GET", f"/crm-api/v1/agent/{agent_id}")
        return resp.json()
