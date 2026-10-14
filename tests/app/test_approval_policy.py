"""Only Zepto confirmation, checkout, and payment actions require approval."""

import pytest

from theos.runtime.approvals import requires_approval


@pytest.mark.parametrize(
    "name",
    [
        "sandbox_run_command",
        "sandbox_execute_code",
        "sandbox_browser",
        "gmail_send_draft",
        "delete_user_file",
        "delete_custom_table",
        "configure_memory_automation",
        "zepto_search_products",
        "zepto_get_cart",
        "zepto_update_cart",
        "zepto_select_saved_address",
        "zepto_order_history",
    ],
)
def test_ordinary_tools_do_not_require_approval(name):
    assert not requires_approval(name)


@pytest.mark.parametrize(
    "name",
    [
        "zepto_confirm_cart",
        "zepto_create_order",
        "zepto_place_order",
        "zepto_checkout",
        "zepto_create_online_payment_order",
        "zepto_create_upi_reserve_pay_order",
        "zepto_create_wallet_order",
        "zepto_get_payment_status",
    ],
)
def test_confirmation_and_payment_tools_require_approval(name):
    assert requires_approval(name)
