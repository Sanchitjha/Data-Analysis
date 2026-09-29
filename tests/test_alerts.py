from unittest import mock

from invsales import alerts, kpis
from invsales.config import Settings


def test_message_lists_most_urgent_first(sales, inventory, products, warehouses):
    msg = alerts.format_message(kpis.reorder_alerts(sales, inventory, products, warehouses))
    assert msg.splitlines()[0].startswith("3 item(s) need reordering")
    assert msg.index("Gamma") < msg.index("Alpha") and "Delhi" in msg


def test_no_alerts_message():
    import pandas as pd
    assert "above their reorder level" in alerts.format_message(pd.DataFrame())


def test_dry_run_sends_nothing(sales, inventory, products, warehouses):
    s = Settings(slack_webhook_url="https://hooks.example/x")
    with mock.patch.object(alerts.requests, "post") as post:
        alerts.dispatch(kpis.reorder_alerts(sales, inventory, products, warehouses), s, send=False)
    post.assert_not_called()


def test_slack_payload(sales, inventory, products, warehouses):
    s = Settings(slack_webhook_url="https://hooks.example/x", smtp_host=None)
    with mock.patch.object(alerts.requests, "post") as post:
        text = alerts.dispatch(kpis.reorder_alerts(sales, inventory, products, warehouses), s, send=True)
    post.assert_called_once()
    assert post.call_args.kwargs["json"] == {"text": text} and post.call_args.args[0] == "https://hooks.example/x"


def test_email_requires_config(sales, inventory, products, warehouses):
    import pytest
    with pytest.raises(ValueError):
        alerts.send_email(Settings(smtp_host="smtp.example"), "s", "b")
