import json
import secrets
import unittest
import uuid
from unittest.mock import patch

from open_marketplace.shipping import cdek
from open_marketplace.shipping.tests.test_cdek import FixtureServer, create_payload, token_response


class CdekBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.order_uuid = str(uuid.uuid4())
        self.request_uuid = str(uuid.uuid4())
        self.accepted = {
            "entity": {"uuid": self.order_uuid},
            "requests": [{"type": "CREATE", "state": "ACCEPTED", "date_time": "2026-01-01T00:00:00Z", "request_uuid": self.request_uuid}],
        }
        self.reply = {"status": 202, "body": self.accepted}
        self.token = secrets.token_urlsafe(32)

        def respond(record):
            if record["path"].startswith("/v2/oauth/token?"):
                return {"body": token_response(self.token)}
            return self.reply

        self.server = FixtureServer(respond)
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.base = patch.object(cdek, "SANDBOX_BASE_URL", self.server.base_url)
        self.base.start()
        self.addCleanup(self.base.stop)
        self.client = cdek.CdekClient(client_id=secrets.token_urlsafe(16), client_secret=secrets.token_urlsafe(32), environment="sandbox")

    def test_live_constructor_needs_separate_enablement_and_bounded_timeout(self):
        with self.assertRaises(cdek.CdekConfigurationError):
            cdek.CdekClient(client_id=secrets.token_urlsafe(16), client_secret=secrets.token_urlsafe(32), environment="production")
        for timeout in (float("nan"), float("inf"), 121):
            with self.subTest(timeout=timeout), self.assertRaises(cdek.CdekConfigurationError):
                cdek.CdekClient(client_id=secrets.token_urlsafe(16), client_secret=secrets.token_urlsafe(32), environment="sandbox", timeout=timeout)

    def test_duplicate_json_fields_cannot_change_selected_order(self):
        encoded = json.dumps(self.accepted)
        self.reply["body"] = ('{"entity":{"uuid":"' + str(uuid.uuid4()) + '"},' + encoded[1:]).encode()
        with self.assertRaises(cdek.CdekUnknownResult) as caught:
            self.client.create_order(create_payload())
        self.assertIsNone(caught.exception.__context__)

    def test_accepted_without_matching_request_metadata_is_unknown(self):
        for body in ({}, {"entity": {"uuid": self.order_uuid}}, {"requests": self.accepted["requests"]},
                     {"entity": {"uuid": self.order_uuid}, "requests": [{**self.accepted["requests"][0], "type": "GET"}]}):
            with self.subTest(body=body), self.assertRaises(cdek.CdekUnknownResult):
                self.reply["body"] = body
                self.client.create_order(create_payload())

    def test_broken_chunked_response_does_not_escape_as_raw_exception(self):
        self.reply = {"status": 202, "headers": {"Transfer-Encoding": "chunked"}, "body": b"10\r\n{}\r\n"}
        with self.assertRaises(cdek.CdekUnknownResult) as caught:
            self.client.create_order(create_payload())
        self.assertIsNone(caught.exception.__context__)

    def test_short_content_length_body_is_unknown_even_with_valid_json(self):
        encoded = json.dumps(self.accepted).encode()
        self.reply = {"status": 202, "headers": {"Content-Length": str(len(encoded) + 10)}, "body": encoded}
        with self.assertRaises(cdek.CdekUnknownResult):
            self.client.create_order(create_payload())

    def test_bad_bearer_token_is_rejected_before_request_headers(self):
        self.token = secrets.token_urlsafe(24) + "\r\nX-Injected: blocked"
        with self.assertRaises(cdek.CdekProtocolError) as caught:
            self.client.create_order(create_payload())
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(len(self.server.server.records), 1)

    def test_get_and_find_bind_response_identity(self):
        self.reply = {"status": 200, "body": {"entity": {"uuid": str(uuid.uuid4()), "number": "other"}, "requests": []}}
        with self.assertRaises(cdek.CdekProtocolError):
            self.client.get_order(order_uuid=self.order_uuid)
        with self.assertRaises(cdek.CdekProtocolError):
            self.client.find_order(number="ORDER-1")

    def test_unrelated_failed_request_cannot_replace_target_state(self):
        response = {"requests": [
            {"type": "UPDATE", "state": "INVALID", "date_time": "2026-01-01T00:00:00Z", "errors": [{"code": "bad"}]},
            {"type": "CREATE", "state": "SUCCESSFUL", "date_time": "2026-01-01T00:00:00Z", "request_uuid": self.request_uuid},
        ]}
        self.assertEqual(cdek.request_state(response, operation="CREATE", request_uuid=self.request_uuid), "SUCCESSFUL")
        response["entity"] = {"uuid": self.order_uuid, "number": "ORDER-1", "statuses": [{"code": "DELIVERED", "date_time": "2026-01-01T00:00:00Z", "deleted": False}]}
        self.assertEqual(cdek.delivery_status(response, expected_uuid=self.order_uuid, expected_number="ORDER-1"), "DELIVERED")
