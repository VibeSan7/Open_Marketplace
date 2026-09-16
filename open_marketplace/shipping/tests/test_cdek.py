import base64

import json
import os
import secrets
import socket
import threading
import time
import traceback
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from unittest import mock
from urllib.parse import parse_qs, urlsplit


from open_marketplace.shipping import cdek


def token_response(token):
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
    }


def credentials():
    return {
        "client_id": secrets.token_urlsafe(16),
        "client_secret": secrets.token_urlsafe(24),
    }


def calculator_response():
    return {
        "delivery_sum": 100.0,
        "period_min": 1,
        "period_max": 3,
        "weight_calc": 1000,
        "total_sum": 120.0,
        "currency": "RUB",
    }


def create_payload(order_number="ORDER-1"):
    return {
        "type": 1,
        "number": order_number,
        "tariff_code": 137,
        "from_location": {"code": 44, "address": "Sender street 1"},
        "to_location": {"code": 137, "address": "Recipient street 2"},
        "recipient": {"name": "Recipient", "phones": [{"number": "+12025550123"}]},
        "packages": [{"number": "1", "weight": 1000, "length": 10, "width": 10, "height": 10,
                      "items": [{"name": "Fixture item", "ware_key": "fixture-item", "payment": {"value": 0}, "cost": 100, "weight": 1000, "amount": 1}]}],
        "comment": "preserve this field",
    }


def order_entity(order_uuid, number="ORDER-1", statuses=None):
    return {
        "uuid": order_uuid,
        "type": 1,
        "number": number,
        "tariff_code": 137,
        "from_location": {"address": "Sender street 1"},
        "to_location": {"address": "Recipient street 2"},
        "sender": {"name": "Sender", "phones": []},
        "recipient": {"name": "Recipient", "phones": []},
        "packages": [{"number": "1", "weight": 1000}],
        "statuses": [] if statuses is None else statuses,
        "is_client_return": False,
        "is_return": False,
        "is_reverse": False,
    }


def response_with_entity(entity, requests=None):
    return {
        "entity": entity,
        "requests": [] if requests is None else requests,
    }


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format_string, *args):
        return

    def _serve(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        record = {
            "method": self.command,
            "path": self.path,
            "headers": {key.lower(): value for key, value in self.headers.items()},
            "body": body,
        }
        self.server.records.append(record)
        response = self.server.responder(record)
        if response.get("delay"):
            time.sleep(response["delay"])
        status = response.get("status", 200)
        payload = response.get("body", b"")
        if isinstance(payload, dict):
            payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        headers = response.get("headers", {})
        if payload and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        if payload and "Content-Length" not in headers:
            headers["Content-Length"] = str(len(payload))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if payload:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    do_GET = _serve
    do_POST = _serve
    do_DELETE = _serve


class FixtureServer:
    def __init__(self, responder):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self.server.daemon_threads = True
        self.server.records = []
        self.server.responder = responder
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return "http://127.0.0.1:%d" % self.server.server_port

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class CdekContractTests(unittest.TestCase):
    def client(self, server, timeout=2):
        return cdek.CdekClient(
            client_id=secrets.token_urlsafe(16),
            client_secret=secrets.token_urlsafe(24),
            environment="sandbox",
            timeout=timeout,
        )

    def patch_base(self, server):
        return mock.patch.object(cdek, "SANDBOX_BASE_URL", server.base_url)

    def test_client_class_is_exposed(self):
        assert hasattr(cdek, "CdekClient"), "CdekClient must be implemented"

    def test_auth_query_and_calculator_http_contract(self):
        token = secrets.token_urlsafe(20)

        def responder(record):
            if record["path"].startswith("/v2/oauth/token?"):
                self.assertEqual("POST", record["method"])
                query = parse_qs(urlsplit(record["path"]).query)
                self.assertEqual(["client_credentials"], query["grant_type"])
                self.assertEqual(1, len(query["client_id"]))
                self.assertEqual(1, len(query["client_secret"]))
                return {"body": token_response(token)}
            self.assertEqual("POST", record["method"])
            self.assertEqual("/v2/calculator/tariff", record["path"])
            self.assertEqual("Bearer " + token, record["headers"]["authorization"])
            self.assertEqual("application/json", record["headers"]["content-type"])
            payload = json.loads(record["body"])
            self.assertEqual(1, payload["type"])
            self.assertEqual(1, payload["currency"])
            return {"body": calculator_response()}

        with FixtureServer(responder) as server, self.patch_base(server):
            payload = {
                "type": 1,
                "currency": 1,
                "tariff_code": 137,
                "from_location": {"code": 44},
                "to_location": {"code": 137},
                "packages": [{"weight": 1000}],
            }
            result = self.client(server).calculate_tariff(payload)
        self.assertEqual(calculator_response(), result)

    def test_token_is_cached_until_expiration(self):
        calls = []

        def responder(record):
            calls.append(record)
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(secrets.token_urlsafe(16))}
            return {"body": calculator_response()}

        with FixtureServer(responder) as server, self.patch_base(server):
            client = self.client(server)
            payload = {"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]}
            client.calculate_tariff(payload)
            client.calculate_tariff(payload)
        self.assertEqual(1, sum(record["path"].startswith("/v2/oauth/token") for record in calls))

    def test_token_refreshes_after_monotonic_deadline_without_replaying_operation(self):
        tokens = [secrets.token_urlsafe(16), secrets.token_urlsafe(16)]
        calls = []

        def responder(record):
            calls.append(record)
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(tokens.pop(0))}
            return {"body": calculator_response()}

        payload = {"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]}
        with FixtureServer(responder) as server, self.patch_base(server), mock.patch.object(cdek.time, "monotonic", side_effect=[0.0, 10.0, 3610.0, 3620.0]):
            client = self.client(server)
            client.calculate_tariff(payload)
            client.calculate_tariff(payload)
        self.assertEqual(2, sum(record["path"].startswith("/v2/oauth/token") for record in calls))
        self.assertEqual(4, len(calls))

    def test_create_preserves_payload_and_202_is_pending(self):
        token = secrets.token_urlsafe(16)
        order_uuid = str(uuid.uuid4())
        request_uuid = str(uuid.uuid4())
        received = {}

        def responder(record):
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            self.assertEqual("POST", record["method"])
            self.assertEqual("/v2/orders", record["path"])
            received.update(json.loads(record["body"]))
            return {"status": 202, "body": response_with_entity({"uuid": order_uuid}, [{"request_uuid": request_uuid, "type": "CREATE", "state": "ACCEPTED", "date_time": "2026-01-01T00:00:00Z"}])}

        with FixtureServer(responder) as server, self.patch_base(server):
            payload = create_payload()
            result = self.client(server).create_order(payload)
        self.assertEqual(payload, received)
        self.assertEqual("ACCEPTED", cdek.request_state(result, operation="CREATE", request_uuid=request_uuid))

    def test_get_successful_request_cannot_prove_create(self):
        request_uuid = str(uuid.uuid4())
        response = response_with_entity({}, [{"request_uuid": request_uuid, "type": "GET", "state": "SUCCESSFUL", "date_time": "2026-01-01T00:00:00Z"}])
        with self.assertRaises(cdek.CdekProtocolError):
            cdek.request_state(response, operation="CREATE")

    def test_request_state_rejects_ambiguous_and_respects_uuid(self):
        first = str(uuid.uuid4())
        second = str(uuid.uuid4())
        response = response_with_entity({}, [
            {"request_uuid": first, "type": "CREATE", "state": "WAITING", "date_time": "2026-01-01T00:00:00Z"},
            {"request_uuid": second, "type": "CREATE", "state": "SUCCESSFUL", "date_time": "2026-01-01T00:01:00Z"},
        ])
        with self.assertRaises(cdek.CdekProtocolError):
            cdek.request_state(response, operation="CREATE")
        self.assertEqual("WAITING", cdek.request_state(response, operation="CREATE", request_uuid=first))

    def test_delivery_status_filters_deleted_and_uses_latest_active_status(self):
        entity_uuid = str(uuid.uuid4())
        response = response_with_entity(order_entity(entity_uuid, statuses=[
            {"code": "DELIVERED", "date_time": "2026-01-02T00:00:00Z", "deleted": True},
            {"code": "DELIVERED", "date_time": "2026-01-01T00:00:00Z", "deleted": False},
            {"code": "CANCELLED", "date_time": "2026-01-03T00:00:00+03:00", "deleted": False},
        ]))
        self.assertEqual("CANCELLED", cdek.delivery_status(response, expected_uuid=entity_uuid, expected_number="ORDER-1"))

    def test_delivery_status_empty_or_all_deleted_is_none(self):
        entity_uuid = str(uuid.uuid4())
        response = response_with_entity(order_entity(entity_uuid, statuses=[{"code": "DELIVERED", "date_time": "2026-01-02T00:00:00Z", "deleted": True}]))
        self.assertIsNone(cdek.delivery_status(response, expected_uuid=entity_uuid, expected_number="ORDER-1"))
        self.assertIsNone(cdek.delivery_status(response_with_entity(order_entity(entity_uuid)), expected_uuid=entity_uuid, expected_number="ORDER-1"))

    def test_delivery_status_rejects_wrong_entity_deleted_type_and_bad_timestamp(self):
        entity_uuid = str(uuid.uuid4())
        response = response_with_entity(order_entity(entity_uuid, statuses=[{"code": "DELIVERED", "date_time": "2026-01-02T00:00:00Z", "deleted": "false"}]))
        with self.assertRaises(cdek.CdekProtocolError):
            cdek.delivery_status(response, expected_uuid=str(uuid.uuid4()), expected_number="ORDER-1")
        with self.assertRaises(cdek.CdekProtocolError):
            cdek.delivery_status(response, expected_uuid=entity_uuid, expected_number="ORDER-1")
        bad_time = response_with_entity(order_entity(entity_uuid, statuses=[{"code": "DELIVERED", "date_time": "not-a-time", "deleted": False}]))
        with self.assertRaises(cdek.CdekProtocolError):
            cdek.delivery_status(bad_time, expected_uuid=entity_uuid, expected_number="ORDER-1")

    def test_find_order_url_encodes_number(self):
        token = secrets.token_urlsafe(16)
        seen = []

        def responder(record):
            seen.append(record)
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"body": response_with_entity(order_entity(str(uuid.uuid4()), number="A/B 1"))}

        with FixtureServer(responder) as server, self.patch_base(server):
            cdek.CdekClient(**credentials(), environment="sandbox").find_order(number="A/B 1")
        self.assertEqual("/v2/orders?im_number=A%2FB+1", seen[1]["path"])

    def test_get_order_uses_canonical_uuid_path(self):
        token = secrets.token_urlsafe(16)
        order_uuid = str(uuid.uuid4())
        seen = []

        def responder(record):
            seen.append(record)
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"body": response_with_entity(order_entity(order_uuid))}

        with FixtureServer(responder) as server, self.patch_base(server):
            cdek.CdekClient(**credentials(), environment="sandbox").get_order(order_uuid=order_uuid)
        self.assertEqual("GET", seen[1]["method"])
        self.assertEqual("/v2/orders/" + order_uuid, seen[1]["path"])

    def test_delete_uses_delete_request_and_202_response(self):
        token = secrets.token_urlsafe(16)
        order_uuid = str(uuid.uuid4())
        seen = []

        def responder(record):
            seen.append(record)
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"status": 202, "body": {"requests": [{"type": "DELETE", "state": "ACCEPTED", "request_uuid": str(uuid.uuid4()), "date_time": "2026-01-01T00:00:00Z"}]}}

        with FixtureServer(responder) as server, self.patch_base(server):
            cdek.CdekClient(**credentials(), environment="sandbox").delete_order(order_uuid=order_uuid)
        self.assertEqual("DELETE", seen[1]["method"])
        self.assertEqual("/v2/orders/" + order_uuid, seen[1]["path"])

    def test_nested_request_errors_are_not_swallowed(self):
        response = {"requests": [{"type": "CREATE", "state": "INVALID", "errors": [{"code": "bad", "message": "private details"}]}]}
        with self.assertRaises(cdek.CdekProtocolError):
            cdek.request_state(response, operation="CREATE")

    def test_validation_rejects_routes_recipient_packages_and_ids_before_network(self):
        client = cdek.CdekClient(**credentials(), environment="sandbox")
        cases = [
            {"type": 1, "number": "x", "tariff_code": 1, "recipient": {}, "packages": [{"number": "1", "weight": 1}]},
            {"type": 1, "number": "x", "tariff_code": 1, "recipient": {}, "packages": [], "from_location": {}, "to_location": {}},
            {"type": 1, "number": "x", "tariff_code": 1, "recipient": {}, "packages": [{"number": "1", "weight": 1}], "from_location": {}, "shipment_point": "PVZ", "to_location": {}},
            {"type": 1, "number": "x", "tariff_code": 1, "recipient": {}, "packages": [{"number": "1", "weight": 1}], "shipment_point": "PVZ", "to_location": {}, "delivery_point": "PVZ2"},
            {"type": 1, "number": "тест", "tariff_code": 1, "recipient": {}, "packages": [{"number": "1", "weight": 1}], "shipment_point": "PVZ", "delivery_point": "PVZ2"},
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(cdek.CdekInputError):
                client.create_order(payload)
        with self.assertRaises(cdek.CdekInputError):
            client.find_order(number="x" * 41)
        with self.assertRaises(cdek.CdekInputError):
            client.find_order(number="тест")
        with self.assertRaises(cdek.CdekInputError):
            client.get_order(order_uuid="not-a-uuid")

    def test_calculator_requires_explicit_type_and_currency(self):
        client = cdek.CdekClient(**credentials(), environment="sandbox")
        for missing in ("type", "currency"):
            payload = {"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]}
            del payload[missing]
            with self.subTest(missing=missing), self.assertRaises(cdek.CdekInputError):
                client.calculate_tariff(payload)

    def test_refusal_and_401_do_not_retry(self):
        token = secrets.token_urlsafe(16)
        records = []

        def responder(record):
            records.append(record)
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"status": 401, "body": {"errors": [{"code": "unauthorized", "message": "secret"}]}}

        with FixtureServer(responder) as server, self.patch_base(server):
            client = self.client(server)
            with self.assertRaises(cdek.CdekHTTPError) as caught:
                client.calculate_tariff({"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]})
        self.assertEqual(401, caught.exception.status_code)
        self.assertEqual(2, len(records))

    def test_auth_refusal_sends_no_order_request(self):
        records = []

        def responder(record):
            records.append(record)
            return {"status": 401, "body": {"errors": [{"code": "unauthorized", "message": "secret"}]}}

        with FixtureServer(responder) as server, self.patch_base(server):
            with self.assertRaises(cdek.CdekHTTPError):
                self.client(server).create_order(create_payload())
        self.assertEqual(1, len(records))

    def test_create_and_delete_server_failures_are_unknown(self):
        token = secrets.token_urlsafe(16)
        calls = []

        def responder(record):
            calls.append(record)
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"status": 503, "body": b"provider private body"}

        with FixtureServer(responder) as server, self.patch_base(server):
            client = self.client(server)
            with self.assertRaises(cdek.CdekUnknownResult):
                client.create_order(create_payload())
            with self.assertRaises(cdek.CdekUnknownResult):
                client.delete_order(order_uuid=str(uuid.uuid4()))
        self.assertEqual(3, len(calls))

    def test_malformed_create_response_is_unknown(self):
        token = secrets.token_urlsafe(16)

        def responder(record):
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"status": 202, "body": b"not-json"}

        with FixtureServer(responder) as server, self.patch_base(server):
            with self.assertRaises(cdek.CdekUnknownResult):
                self.client(server).create_order(create_payload())

    def test_create_and_delete_timeouts_are_unknown(self):
        token = secrets.token_urlsafe(16)

        def responder(record):
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"delay": 0.3, "body": {"requests": []}}

        with FixtureServer(responder) as server, self.patch_base(server):
            client = self.client(server, timeout=0.05)
            with self.assertRaises(cdek.CdekUnknownResult):
                client.create_order(create_payload())
            with self.assertRaises(cdek.CdekUnknownResult):
                client.delete_order(order_uuid=str(uuid.uuid4()))

    def test_redirect_is_rejected_without_following_or_forwarding_secret(self):
        token_path_hits = []

        def responder(record):
            token_path_hits.append(record["path"])
            if record["path"].startswith("/v2/oauth/token"):
                return {"status": 302, "headers": {"Location": "/capture"}, "body": b"redirect"}
            self.fail("redirect target must not be requested")

        secret = secrets.token_urlsafe(24)
        with FixtureServer(responder) as server, self.patch_base(server):
            client = cdek.CdekClient(client_id=secrets.token_urlsafe(8), client_secret=secret, environment="sandbox")
            with self.assertRaises(cdek.CdekHTTPError) as caught:
                client.calculate_tariff({"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]})
        self.assertEqual(302, caught.exception.status_code)
        self.assertEqual(1, len(token_path_hits))
        self.assertNotIn(secret, str(caught.exception))

    def test_malformed_json_and_nonfinite_json_are_rejected(self):
        token = secrets.token_urlsafe(16)
        responses = [{"body": token_response(token)}, {"body": b"{broken"}]

        def responder(record):
            return responses.pop(0)

        with FixtureServer(responder) as server, self.patch_base(server):
            client = self.client(server)
            with self.assertRaises(cdek.CdekProtocolError):
                client.calculate_tariff({"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]})

        def nonfinite_responder(record):
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"body": b'{"delivery_sum":NaN}'}

        with FixtureServer(nonfinite_responder) as server, self.patch_base(server):
            with self.assertRaises(cdek.CdekProtocolError):
                self.client(server).calculate_tariff({"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]})

        with self.assertRaises(cdek.CdekInputError):
            self.client(None).calculate_tariff({"type": 1, "currency": 1, "value": float("nan")})

    def test_oversized_response_is_rejected_with_bounded_read(self):
        token = secrets.token_urlsafe(16)
        oversized = b"{" + b'"x":"' + b"a" * (2 * 1024 * 1024) + b'"}'

        def responder(record):
            if record["path"].startswith("/v2/oauth/token"):
                return {"body": token_response(token)}
            return {"body": oversized}

        with FixtureServer(responder) as server, self.patch_base(server):
            with self.assertRaises(cdek.CdekProtocolError):
                self.client(server).calculate_tariff({"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]})

    def test_configuration_is_fail_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(cdek.CdekConfigurationError):
                cdek.CdekClient.from_environment()
        with mock.patch.dict(os.environ, {"CDEK_ENVIRONMENT": "production", "CDEK_CLIENT_ID": secrets.token_urlsafe(8), "CDEK_CLIENT_SECRET": secrets.token_urlsafe(12), "CDEK_LIVE_ENABLED": "TRUE"}, clear=True):
            with self.assertRaises(cdek.CdekConfigurationError):
                cdek.CdekClient.from_environment()
        with mock.patch.dict(os.environ, {"CDEK_ENVIRONMENT": "production", "CDEK_CLIENT_ID": secrets.token_urlsafe(8), "CDEK_CLIENT_SECRET": secrets.token_urlsafe(12), "CDEK_LIVE_ENABLED": "true"}, clear=True):
            client = cdek.CdekClient.from_environment()
        self.assertEqual("production", client.environment)

    def test_exception_text_and_traceback_do_not_include_secret_or_url(self):
        secret = secrets.token_urlsafe(24)

        def responder(record):
            return {"status": 401, "body": {"errors": [{"message": secret}]}}

        with FixtureServer(responder) as server, self.patch_base(server):
            client = cdek.CdekClient(client_id=secrets.token_urlsafe(8), client_secret=secret, environment="sandbox")
            try:
                client.calculate_tariff({"type": 1, "currency": 1, "tariff_code": 137, "from_location": {}, "to_location": {}, "packages": [{"weight": 1}]})
            except Exception as exc:
                rendered = str(exc) + "\n" + "".join(traceback.format_exception(exc))
            else:
                self.fail("provider refusal must raise")
        self.assertNotIn(secret, rendered)
        self.assertNotIn(server.base_url, rendered)


if __name__ == "__main__":
    unittest.main()
