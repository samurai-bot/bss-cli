"""Inventory policies for MSISDN and eSIM resources."""

from app.policies.base import PolicyViolation, policy


@policy("msisdn.reserve.status_must_be_available")
def check_msisdn_available(status: str, msisdn: str) -> None:
    if status != "available":
        raise PolicyViolation(
            rule="msisdn.reserve.status_must_be_available",
            message=f"MSISDN {msisdn} is not available (status={status})",
            context={"msisdn": msisdn, "status": status},
        )


@policy("msisdn.release.only_if_reserved_or_assigned")
def check_msisdn_releasable(status: str, msisdn: str) -> None:
    if status not in ("reserved", "assigned"):
        raise PolicyViolation(
            rule="msisdn.release.only_if_reserved_or_assigned",
            message=f"MSISDN {msisdn} cannot be released (status={status})",
            context={"msisdn": msisdn, "status": status},
        )


@policy("esim.reserve.status_must_be_available")
def check_esim_available(status: str, iccid: str) -> None:
    if status != "available":
        raise PolicyViolation(
            rule="esim.reserve.status_must_be_available",
            message=f"eSIM {iccid} is not available (status={status})",
            context={"iccid": iccid, "status": status},
        )


@policy("esim.release.only_if_reserved_or_assigned")
def check_esim_releasable(status: str, iccid: str) -> None:
    if status not in ("reserved", "assigned"):
        raise PolicyViolation(
            rule="esim.release.only_if_reserved_or_assigned",
            message=f"eSIM {iccid} cannot be released (status={status})",
            context={"iccid": iccid, "status": status},
        )


@policy("esim.assign_msisdn.msisdn_must_be_reserved")
def check_msisdn_reserved_for_assign(msisdn_status: str, msisdn: str) -> None:
    if msisdn_status not in ("reserved", "assigned"):
        raise PolicyViolation(
            rule="esim.assign_msisdn.msisdn_must_be_reserved",
            message=f"MSISDN {msisdn} must be reserved or assigned before binding to eSIM",
            context={"msisdn": msisdn, "status": msisdn_status},
        )
