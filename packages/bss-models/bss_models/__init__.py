"""BSS-CLI shared models package.

Imports all domain models so that ``Base.metadata`` contains every table
when Alembic (or any other tool) loads this package.
"""

from .base import Base, TenantMixin, TimestampMixin

# CRM (12 tables)
from .crm import (
    Agent,
    Case,
    CaseNote,
    ContactMedium,
    Customer,
    CustomerIdentity,
    Individual,
    Interaction,
    Party,
    SlaPolicy,
    Ticket,
    TicketStateHistory,
)

# Catalog (7 tables)
from .catalog import (
    BundleAllowance,
    ProductOffering,
    ProductOfferingPrice,
    ProductSpecification,
    ProductToServiceMapping,
    ServiceSpecification,
    VasOffering,
)

# Inventory (2 tables)
from .inventory import EsimProfile, MsisdnPool

# Payment (2 tables)
from .payment import PaymentAttempt, PaymentMethod

# Order Management (3 tables)
from .order_mgmt import OrderItem, OrderStateHistory, ProductOrder

# Service Inventory (4 tables)
from .service_inventory import (
    Service,
    ServiceOrder,
    ServiceOrderItem,
    ServiceStateHistory,
)

# Provisioning (2 tables)
from .provisioning import FaultInjection, ProvisioningTask

# Subscription (4 tables)
from .subscription import (
    BundleBalance,
    Subscription,
    SubscriptionStateHistory,
    VasPurchase,
)

# Mediation (1 table)
from .mediation import UsageEvent

# Billing (2 tables)
from .billing import BillingAccount, CustomerBill

# Audit (1 table)
from .audit import DomainEvent

# Portal Auth (4 tables) — v0.8
from .portal_auth import (
    EmailChangePending,
    Identity,
    LoginAttempt,
    LoginToken,
    PortalAction,
    Session,
)

__all__ = [
    "Base",
    "TenantMixin",
    "TimestampMixin",
    # CRM
    "Party",
    "Individual",
    "ContactMedium",
    "Customer",
    "CustomerIdentity",
    "Interaction",
    "Agent",
    "Case",
    "CaseNote",
    "Ticket",
    "TicketStateHistory",
    "SlaPolicy",
    # Catalog
    "ProductSpecification",
    "ProductOffering",
    "ProductOfferingPrice",
    "BundleAllowance",
    "VasOffering",
    "ServiceSpecification",
    "ProductToServiceMapping",
    # Inventory
    "MsisdnPool",
    "EsimProfile",
    # Payment
    "PaymentMethod",
    "PaymentAttempt",
    # Order Management
    "ProductOrder",
    "OrderItem",
    "OrderStateHistory",
    # Service Inventory
    "ServiceOrder",
    "ServiceOrderItem",
    "Service",
    "ServiceStateHistory",
    # Provisioning
    "ProvisioningTask",
    "FaultInjection",
    # Subscription
    "Subscription",
    "BundleBalance",
    "VasPurchase",
    "SubscriptionStateHistory",
    # Mediation
    "UsageEvent",
    # Billing
    "BillingAccount",
    "CustomerBill",
    # Audit
    "DomainEvent",
    # Portal Auth (v0.8 + v0.10 PortalAction + v0.10 EmailChangePending)
    "Identity",
    "LoginToken",
    "Session",
    "LoginAttempt",
    "PortalAction",
    "EmailChangePending",
]
