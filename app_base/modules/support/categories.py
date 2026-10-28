from __future__ import annotations

from enum import StrEnum


class SupportCategory(StrEnum):
    GENERAL = "general"
    ACCOUNT_ISSUE = "account_issue"
    PAYMENT_ISSUE = "payment_issue"
    TECHNICAL_ISSUE = "technical_issue"
    SAFETY_ISSUE = "safety_issue"
    RIDE_ISSUE = "ride_issue"
    DELIVERY_ISSUE = "delivery_issue"
    ORDER_ISSUE = "order_issue"
    OTHER = "other"


SUPPORT_CATEGORY_CATALOG: tuple[dict[str, object], ...] = (
    {"id": SupportCategory.GENERAL, "label_key": "support.category.general", "contexts": ()},
    {"id": SupportCategory.ACCOUNT_ISSUE, "label_key": "support.category.account_issue", "contexts": ()},
    {"id": SupportCategory.PAYMENT_ISSUE, "label_key": "support.category.payment_issue", "contexts": ()},
    {"id": SupportCategory.TECHNICAL_ISSUE, "label_key": "support.category.technical_issue", "contexts": ()},
    {"id": SupportCategory.SAFETY_ISSUE, "label_key": "support.category.safety_issue", "contexts": ()},
    {
        "id": SupportCategory.RIDE_ISSUE,
        "label_key": "support.category.ride_issue",
        "contexts": (("diddigo", "ride"),),
    },
    {
        "id": SupportCategory.DELIVERY_ISSUE,
        "label_key": "support.category.delivery_issue",
        "contexts": (("diddisend", "delivery"),),
    },
    {
        "id": SupportCategory.ORDER_ISSUE,
        "label_key": "support.category.order_issue",
        "contexts": (("diddifood", "food_order"),),
    },
    {"id": SupportCategory.OTHER, "label_key": "support.category.other", "contexts": ()},
)


def category_catalog(*, owner_service: str | None = None, task_type: str | None = None) -> list[dict[str, object]]:
    context = (owner_service, task_type) if owner_service and task_type else None
    return [
        item
        for item in SUPPORT_CATEGORY_CATALOG
        if not item["contexts"] or (context is not None and context in item["contexts"])
    ]


def category_allows_context(
    category: SupportCategory,
    *,
    owner_service: str | None,
    task_type: str | None,
) -> bool:
    item = next(item for item in SUPPORT_CATEGORY_CATALOG if item["id"] == category)
    contexts = item["contexts"]
    if not contexts:
        return True
    return (owner_service, task_type) in contexts
