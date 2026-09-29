from unittest import mock

from invsales import alerts, kpis
from invsales.config import Settings


def test_message_lists_most_urgent_first(sales, products):
    msg = alerts.format_message(kpis.reorder_alerts(sales, products))
    assert msg.splitlines()[0].startswith("2 product(s) need reordering")
    assert msg.index("Gamma") < msg.index("Alpha")


def test_no_alerts_message(products):
    assert "above their reorder level" in alerts.format_message(kpis.reorder_alerts.__globals__["pd"].DataFrame())


def test_dry_run_sends_nothing(sales, products):
    s = Settings(slack_webhook_url="https://hooks.example/x")
    with mock.patch.object(alerts.requests, "post") as post:
        alerts.dispatch(kpis.reorder_alerts(sales, products), s, send=False)
    post.assert_not_called()


def test_slack_payload(sales, products):
    s = Settings(slack_webhook_url="https://hooks.example/x", smtp_host=None)
    with mock.patch.object(alerts.requests, "post") as post:
        text = alerts.dispatch(kpis.reorder_alerts(sales, products), s, send=True)
    post.assert_called_once()
    assert post.call_args.kwargs["json"] == {"text": text} and post.call_args.args[0] == "https://hooks.example/x"


def test_email_requires_config(sales, products):
    import pytest
    with pytest.raises(ValueError):
        alerts.send_email(Settings(smtp_host="smtp.example"), "s", "b")
