"""Inventory service — MSISDN + eSIM pool management."""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_context
from app.domain import esim_state
from app.policies.base import PolicyViolation
from app.policies import inventory as inv_policies
from app.repositories.esim_repo import EsimRepository
from app.repositories.msisdn_repo import MsisdnRepository
from bss_models.inventory import EsimProfile, MsisdnPool

log = structlog.get_logger()


class InventoryService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        msisdn_repo: MsisdnRepository,
        esim_repo: EsimRepository,
    ) -> None:
        self._session = session
        self._msisdn_repo = msisdn_repo
        self._esim_repo = esim_repo

    # ── MSISDN ──────────────────────────────────────────────────────

    async def list_msisdns(
        self,
        *,
        status: str | None = None,
        prefix: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[MsisdnPool]:
        return await self._msisdn_repo.list_msisdns(
            status=status, prefix=prefix, limit=limit, offset=offset
        )

    async def get_msisdn(self, msisdn: str) -> MsisdnPool | None:
        return await self._msisdn_repo.get(msisdn)

    async def reserve_msisdn(self, msisdn: str) -> MsisdnPool:
        ctx = auth_context.current()
        result = await self._msisdn_repo.reserve_atomic(msisdn, ctx.tenant)
        if not result:
            raise PolicyViolation(
                rule="msisdn.reserve.status_must_be_available",
                message=f"MSISDN {msisdn} is not available for reservation",
                context={"msisdn": msisdn},
            )
        await self._session.commit()
        return result

    async def assign_msisdn(self, msisdn: str, subscription_id: str | None = None) -> MsisdnPool:
        row = await self._msisdn_repo.get(msisdn)
        if not row:
            raise PolicyViolation(
                rule="msisdn.assign.not_found",
                message=f"MSISDN {msisdn} not found",
                context={"msisdn": msisdn},
            )
        if row.status not in ("reserved", "assigned"):
            raise PolicyViolation(
                rule="msisdn.assign.must_be_reserved",
                message=f"MSISDN {msisdn} must be reserved before assignment",
                context={"msisdn": msisdn, "status": row.status},
            )
        row.status = "assigned"
        if subscription_id:
            row.assigned_to_subscription_id = subscription_id
        await self._msisdn_repo.update_status(msisdn, "assigned")
        await self._session.commit()
        return row

    async def release_msisdn(self, msisdn: str) -> MsisdnPool:
        row = await self._msisdn_repo.get(msisdn)
        if not row:
            raise PolicyViolation(
                rule="msisdn.release.not_found",
                message=f"MSISDN {msisdn} not found",
                context={"msisdn": msisdn},
            )
        inv_policies.check_msisdn_releasable(row.status, msisdn)
        result = await self._msisdn_repo.update_status(msisdn, "available")
        await self._session.commit()
        return result

    # ── eSIM ────────────────────────────────────────────────────────

    async def list_esims(
        self, *, status: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[EsimProfile]:
        return await self._esim_repo.list_esims(
            status=status, limit=limit, offset=offset
        )

    async def get_esim(self, iccid: str) -> EsimProfile | None:
        return await self._esim_repo.get(iccid)

    async def reserve_esim(self) -> EsimProfile:
        ctx = auth_context.current()
        result = await self._esim_repo.reserve_next_available(ctx.tenant)
        if not result:
            raise PolicyViolation(
                rule="esim.reserve.status_must_be_available",
                message="No eSIM profile available for reservation",
                context={},
            )
        await self._session.commit()
        return result

    async def assign_msisdn_to_esim(self, iccid: str, msisdn: str) -> EsimProfile:
        esim = await self._esim_repo.get(iccid)
        if not esim:
            raise PolicyViolation(
                rule="esim.not_found",
                message=f"eSIM {iccid} not found",
                context={"iccid": iccid},
            )
        if esim.profile_state != "reserved":
            raise PolicyViolation(
                rule="esim.assign_msisdn.esim_must_be_reserved",
                message=f"eSIM {iccid} must be reserved to assign MSISDN",
                context={"iccid": iccid, "state": esim.profile_state},
            )
        msisdn_row = await self._msisdn_repo.get(msisdn)
        if not msisdn_row:
            raise PolicyViolation(
                rule="esim.assign_msisdn.msisdn_not_found",
                message=f"MSISDN {msisdn} not found",
                context={"msisdn": msisdn},
            )
        inv_policies.check_msisdn_reserved_for_assign(msisdn_row.status, msisdn)

        result = await self._esim_repo.update_state(iccid, "reserved", assigned_msisdn=msisdn)
        await self._session.commit()
        return result

    async def _transition_esim(self, iccid: str, trigger: str) -> EsimProfile:
        esim = await self._esim_repo.get(iccid)
        if not esim:
            raise PolicyViolation(
                rule="esim.not_found",
                message=f"eSIM {iccid} not found",
                context={"iccid": iccid},
            )
        if not esim_state.is_valid_transition(esim.profile_state, trigger):
            raise PolicyViolation(
                rule="esim.transition.invalid",
                message=f"Cannot '{trigger}' eSIM from state '{esim.profile_state}'",
                context={"iccid": iccid, "state": esim.profile_state, "trigger": trigger},
            )
        new_state = esim_state.get_next_state(esim.profile_state, trigger)
        result = await self._esim_repo.update_state(iccid, new_state)
        await self._session.commit()
        return result

    async def mark_downloaded(self, iccid: str) -> EsimProfile:
        return await self._transition_esim(iccid, "download")

    async def mark_activated(self, iccid: str) -> EsimProfile:
        return await self._transition_esim(iccid, "activate")

    async def recycle_esim(self, iccid: str) -> EsimProfile:
        return await self._transition_esim(iccid, "recycle")

    async def release_esim(self, iccid: str) -> EsimProfile:
        return await self._transition_esim(iccid, "release")

    async def get_activation_code(self, iccid: str) -> dict:
        esim = await self._esim_repo.get(iccid)
        if not esim:
            raise PolicyViolation(
                rule="esim.not_found",
                message=f"eSIM {iccid} not found",
                context={"iccid": iccid},
            )
        return {
            "iccid": esim.iccid,
            "activation_code": esim.activation_code,
            "smdp_server": esim.smdp_server,
            "matching_id": esim.matching_id,
        }
