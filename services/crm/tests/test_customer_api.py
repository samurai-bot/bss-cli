"""Customer API tests — TMF629."""

from httpx import AsyncClient

PREFIX = "/tmf-api/customerManagement/v4"


class TestCreateCustomer:
    async def test_create_customer_happy(self, client: AsyncClient):
        r = await client.post(
            f"{PREFIX}/customer",
            json={
                "givenName": "Test",
                "familyName": "User",
                "contactMedium": [
                    {"medium_type": "email", "value": "test.user@example.com", "is_primary": True}
                ],
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["status"] == "active"
        assert body["kycStatus"] == "not_verified"
        assert body["@type"] == "Customer"
        assert "id" in body
        assert body["id"].startswith("CUST-")

    async def test_create_customer_no_contact_medium(self, client: AsyncClient):
        r = await client.post(
            f"{PREFIX}/customer",
            json={
                "givenName": "No",
                "familyName": "Contact",
                "contactMedium": [],
            },
        )
        assert r.status_code == 422
        body = r.json()
        assert body["reason"] == "customer.create.requires_contact_medium"

    async def test_create_customer_duplicate_email(self, client: AsyncClient):
        email = "duplicate.test@example.com"
        r1 = await client.post(
            f"{PREFIX}/customer",
            json={
                "givenName": "First",
                "familyName": "User",
                "contactMedium": [{"medium_type": "email", "value": email}],
            },
        )
        assert r1.status_code == 201

        r2 = await client.post(
            f"{PREFIX}/customer",
            json={
                "givenName": "Second",
                "familyName": "User",
                "contactMedium": [{"medium_type": "email", "value": email}],
            },
        )
        assert r2.status_code == 422
        assert r2.json()["reason"] == "customer.create.email_unique"


class TestGetCustomer:
    async def test_get_customer_not_found(self, client: AsyncClient):
        r = await client.get(f"{PREFIX}/customer/CUST-NONEXISTENT")
        assert r.status_code == 404

    async def test_get_customer_after_create(self, client: AsyncClient):
        r = await client.post(
            f"{PREFIX}/customer",
            json={
                "givenName": "Fetch",
                "familyName": "Me",
                "contactMedium": [{"medium_type": "email", "value": "fetch.me@example.com"}],
            },
        )
        cust_id = r.json()["id"]
        r2 = await client.get(f"{PREFIX}/customer/{cust_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == cust_id


class TestContactMedium:
    async def test_add_contact_medium(self, client: AsyncClient):
        r = await client.post(
            f"{PREFIX}/customer",
            json={
                "givenName": "Contact",
                "familyName": "Test",
                "contactMedium": [{"medium_type": "email", "value": "contact.test@example.com"}],
            },
        )
        cust_id = r.json()["id"]

        r2 = await client.post(
            f"{PREFIX}/customer/{cust_id}/contactMedium",
            json={"mediumType": "phone", "value": "+6590001234"},
        )
        assert r2.status_code == 201
        assert r2.json()["mediumType"] == "phone"
