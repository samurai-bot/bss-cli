"""Inventory API tests — MSISDN + eSIM."""

from httpx import AsyncClient

MSISDN_PREFIX = "/inventory-api/v1"
ESIM_PREFIX = "/inventory-api/v1"


class TestMsisdn:
    async def test_list_msisdns(self, client: AsyncClient):
        r = await client.get(f"{MSISDN_PREFIX}/msisdn", params={"status": "available", "limit": 5})
        assert r.status_code == 200
        body = r.json()
        assert len(body) <= 5
        if body:
            assert body[0]["status"] == "available"

    async def test_get_msisdn(self, client: AsyncClient):
        r = await client.get(f"{MSISDN_PREFIX}/msisdn/90000005")
        assert r.status_code == 200
        assert r.json()["msisdn"] == "90000005"

    async def test_get_msisdn_not_found(self, client: AsyncClient):
        r = await client.get(f"{MSISDN_PREFIX}/msisdn/99999999")
        assert r.status_code == 404

    async def test_reserve_msisdn(self, client: AsyncClient):
        r = await client.post(f"{MSISDN_PREFIX}/msisdn/90000005/reserve")
        assert r.status_code == 200
        assert r.json()["status"] == "reserved"

    async def test_reserve_already_reserved(self, client: AsyncClient):
        await client.post(f"{MSISDN_PREFIX}/msisdn/90000006/reserve")
        r = await client.post(f"{MSISDN_PREFIX}/msisdn/90000006/reserve")
        assert r.status_code == 422

    async def test_release_msisdn(self, client: AsyncClient):
        await client.post(f"{MSISDN_PREFIX}/msisdn/90000007/reserve")
        r = await client.post(f"{MSISDN_PREFIX}/msisdn/90000007/release")
        assert r.status_code == 200
        assert r.json()["status"] == "available"

    async def test_release_available_fails(self, client: AsyncClient):
        r = await client.post(f"{MSISDN_PREFIX}/msisdn/90000008/release")
        assert r.status_code == 422
        assert r.json()["reason"] == "msisdn.release.only_if_reserved_or_assigned"


class TestEsim:
    async def test_list_esims(self, client: AsyncClient):
        r = await client.get(f"{ESIM_PREFIX}/esim", params={"status": "available", "limit": 5})
        assert r.status_code == 200
        body = r.json()
        assert len(body) <= 5

    async def test_reserve_esim(self, client: AsyncClient):
        r = await client.post(f"{ESIM_PREFIX}/esim/reserve")
        assert r.status_code == 201
        body = r.json()
        assert body["profile_state"] == "reserved"
        assert body["iccid"].startswith("8910")

    async def test_esim_activation_code(self, client: AsyncClient):
        # Reserve first
        r = await client.post(f"{ESIM_PREFIX}/esim/reserve")
        iccid = r.json()["iccid"]

        r = await client.get(f"{ESIM_PREFIX}/esim/{iccid}/activation")
        assert r.status_code == 200
        body = r.json()
        assert body["activation_code"].startswith("LPA:1$smdp.bss-cli.local$")
        assert body["smdp_server"] == "smdp.bss-cli.local"

    async def test_esim_lifecycle(self, client: AsyncClient):
        # Reserve
        r = await client.post(f"{ESIM_PREFIX}/esim/reserve")
        iccid = r.json()["iccid"]

        # Mark downloaded
        r = await client.post(f"{ESIM_PREFIX}/esim/{iccid}/mark-downloaded")
        assert r.status_code == 200
        assert r.json()["profile_state"] == "downloaded"

        # Mark activated
        r = await client.post(f"{ESIM_PREFIX}/esim/{iccid}/mark-activated")
        assert r.status_code == 200
        assert r.json()["profile_state"] == "activated"

    async def test_esim_release_from_reserved(self, client: AsyncClient):
        r = await client.post(f"{ESIM_PREFIX}/esim/reserve")
        iccid = r.json()["iccid"]

        r = await client.post(f"{ESIM_PREFIX}/esim/{iccid}/recycle")
        # Can't recycle from reserved — invalid transition
        assert r.status_code == 422

    async def test_esim_invalid_transition(self, client: AsyncClient):
        # Get an available eSIM
        r = await client.get(f"{ESIM_PREFIX}/esim", params={"status": "available", "limit": 1})
        if r.json():
            iccid = r.json()[0]["iccid"]
            # Can't mark-downloaded from available
            r = await client.post(f"{ESIM_PREFIX}/esim/{iccid}/mark-downloaded")
            assert r.status_code == 422
