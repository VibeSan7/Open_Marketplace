import hashlib
import importlib
import json
import os
import secrets
import threading
import traceback
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch


class TBankProtocolTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module("open_marketplace.payments.tbank")
        except ImportError:
            self.fail("T-Bank Safe Deal protocol adapter is missing")
        self.terminal = secrets.token_hex(12)
        self.password = secrets.token_urlsafe(32)
        self.calls = []
        self.response = {"Success": True, "ErrorCode": "0", "Status": "NEW", "PaymentId": "5001",
                         "TerminalKey": self.terminal, "OrderId": "local-checkout-1", "Amount": 12345,
                         "PaymentURL": "https://pay-test.tbank.ru/local-test-fixture"}
        self.http_status = 200
        self.raw = None
        self.broken_chunk = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                owner.calls.append((self.path, json.loads(body)))
                self.send_response(owner.http_status)
                self.send_header("Content-Type", "application/json")
                if owner.broken_chunk:
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.write(b"10\r\n{}\r\n")
                    return
                if owner.http_status == 302:
                    self.send_header("Location", "/must-not-follow")
                self.end_headers()
                self.wfile.write(owner.raw if owner.raw is not None else json.dumps(owner.response).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        endpoint = f"http://127.0.0.1:{self.server.server_port}"
        self.urls = patch.object(self.module, "BASE_URLS", {"sandbox": endpoint, "production": endpoint})
        self.urls.start()
        self.addCleanup(self.urls.stop)
        self.client = self.module.TBankClient(terminal_key=self.terminal, password=self.password, environment="sandbox")

    def payment(self):
        return {"OrderId": "local-checkout-1", "Amount": 12345, "Currency": 643, "PayType": "T", "CreateDealWithType": "NN",
                "NotificationURL": "https://marketplace.example/payments/notice", "SuccessURL": "https://marketplace.example/orders/1",
                "FailURL": "https://marketplace.example/orders/1", "RedirectDueDate": (datetime.now(UTC) + timedelta(hours=1)).isoformat(timespec="seconds")}

    def notice(self, **changes):
        result = {"TerminalKey": self.terminal, "OrderId": "local-checkout-1", "PaymentId": "5001", "Amount": 12345,
                  "Status": "CONFIRMED", "Success": True, "ErrorCode": "0", "SpAccumulationId": 9001}
        result.update(changes)
        result["Token"] = self.module.signature(result, self.password)
        return result

    def verify(self, notice):
        return self.module.verify_notification(
            json.dumps(notice).encode(), terminal_key=self.terminal, password=self.password,
            expected_order_id="local-checkout-1", expected_payment_id="5001", expected_amount=12345, expected_deal_id="9001",
        )

    def test_signs_sorted_root_values_and_lowercase_boolean_without_mutation(self):
        payload = {"TerminalKey": self.terminal, "Amount": 100, "Success": True, "DATA": {"ignored": "nested"}, "Receipt": []}
        expected = hashlib.sha256(("100" + self.password + "true" + self.terminal).encode()).hexdigest()
        self.assertEqual(self.module.signature(payload, self.password), expected)
        self.assertNotIn("Password", payload)
        self.assertNotIn("Token", payload)

    def test_signature_includes_deal_id_and_ignores_previous_token(self):
        payload = self.notice()
        self.assertEqual(self.module.signature(payload, self.password), payload["Token"])
        changed = {**payload, "SpAccumulationId": 9002}
        self.assertNotEqual(self.module.signature(changed, self.password), payload["Token"])

    def test_rejects_root_password_and_unsupported_signed_values(self):
        for payload in ({"Password": "injected"}, {"Amount": float("nan")}, {"Amount": None}):
            with self.subTest(payload=payload), self.assertRaises(self.module.TBankProtocolError):
                self.module.signature(payload, self.password)

    def test_initialize_uses_explicit_nn_hold_currency_and_signature(self):
        payload = self.payment()
        result = self.client.initialize_payment(payload)
        self.assertEqual(result["PaymentId"], "5001")
        path, sent = self.calls[0]
        self.assertEqual(path, "/v2/Init")
        self.assertEqual(sent["CreateDealWithType"], "NN")
        self.assertEqual((sent["PayType"], sent["Currency"], sent["Amount"]), ("T", 643, 12345))
        self.assertEqual(sent["Token"], self.module.signature(sent, self.password))
        self.assertNotIn("Password", sent)
        self.assertNotIn("Token", payload)

    def test_initialization_rejects_missing_ambiguous_or_wrong_deal_configuration(self):
        for changes in ({"CreateDealWithType": "11"}, {"DealId": "9001"}, {"Currency": 840}, {"PayType": "O"}, {"Amount": True}, {"Amount": 99}):
            with self.subTest(changes=changes), self.assertRaises(self.module.TBankProtocolError):
                self.client.initialize_payment({**self.payment(), **changes})
        payload = self.payment()
        del payload["CreateDealWithType"]
        with self.assertRaises(self.module.TBankProtocolError):
            self.client.initialize_payment(payload)
        self.assertEqual(self.calls, [])

    def test_initialization_accepts_existing_deal_without_creating_another(self):
        payload = self.payment()
        del payload["CreateDealWithType"]
        payload["DealId"] = "9001"
        self.client.initialize_payment(payload)
        self.assertEqual(self.calls[0][1]["DealId"], "9001")
        self.assertNotIn("CreateDealWithType", self.calls[0][1])

    def test_create_deal_uses_separate_documented_method(self):
        self.response = {"Success": True, "ErrorCode": "0", "SpAccumulationId": "9001"}
        self.assertEqual(self.client.create_deal("NN")["SpAccumulationId"], "9001")
        self.assertEqual(self.calls[0][0], "/v2/createSpDeal")
        self.assertEqual(self.calls[0][1]["SpDealType"], "NN")

    def test_payment_state_and_order_lookup_are_distinct(self):
        self.client.get_payment("5001")
        self.response = {"Success": True, "ErrorCode": "0", "TerminalKey": self.terminal, "OrderId": "local-checkout-1", "Payments": []}
        self.client.check_order("local-checkout-1")
        self.assertEqual([call[0] for call in self.calls], ["/v2/GetState", "/v2/CheckOrder"])
        self.assertEqual(self.calls[0][1]["PaymentId"], "5001")
        self.assertEqual(self.calls[1][1]["OrderId"], "local-checkout-1")

    def test_confirm_is_not_payout_and_cancel_requires_stable_request_id(self):
        self.client.confirm_payment("5001", 12345)
        self.response = {"Success": True, "ErrorCode": "0", "TerminalKey": self.terminal, "PaymentId": "5001", "OrderId": "local-checkout-1", "Status": "PARTIAL_REFUNDED", "OriginalAmount": 12345, "NewAmount": 12245}
        self.client.cancel_payment("5001", 100, "refund-operation-1")
        self.assertEqual([call[0] for call in self.calls], ["/v2/Confirm", "/v2/Cancel"])
        self.assertEqual(self.calls[1][1]["ExternalRequestId"], "refund-operation-1")
        with self.assertRaises(self.module.TBankProtocolError):
            self.client.cancel_payment("5001", 100, "")
        self.assertEqual(len(self.calls), 2)

    def test_authenticated_notice_binds_every_identity_and_amount(self):
        notice = self.verify(self.notice())
        self.assertEqual(notice, {"order_id": "local-checkout-1", "payment_id": "5001", "deal_id": "9001", "amount": 12345, "status": "CONFIRMED", "success": True})
        for changes in ({"OrderId": "other-order"}, {"PaymentId": "other-payment"}, {"SpAccumulationId": 9002}, {"TerminalKey": "other-terminal"}, {"Amount": 12344}):
            with self.subTest(changes=changes), self.assertRaises(self.module.TBankProtocolError):
                self.verify(self.notice(**changes))

    def test_tampered_notice_is_rejected_and_card_data_not_returned(self):
        payload = self.notice(CardId=123, Pan="redacted-test-card", ExpDate="test-expiry")
        result = self.verify(payload)
        self.assertFalse({"CardId", "Pan", "ExpDate", "Token", "TerminalKey"} & set(result))
        payload["Amount"] = 1
        with self.assertRaises(self.module.TBankProtocolError):
            self.verify(payload)

    def test_partial_refund_current_amount_is_preserved_not_treated_as_new_payment(self):
        result = self.verify(self.notice(Status="PARTIAL_REFUNDED", Amount=12000))
        self.assertEqual((result["status"], result["amount"]), ("PARTIAL_REFUNDED", 12000))
        result = self.verify(self.notice(Status="AUTHORIZED"))
        self.assertEqual(result["status"], "AUTHORIZED")
        self.assertNotIn("paid", result)

    def test_duplicate_json_keys_and_nonfinite_values_are_rejected(self):
        payload = self.notice()
        raw = json.dumps(payload)[:-1] + ', "Amount":12345}'
        kwargs = dict(terminal_key=self.terminal, password=self.password, expected_order_id="local-checkout-1", expected_payment_id="5001", expected_amount=12345, expected_deal_id="9001")
        for body in (raw.encode(), b'{"Amount":NaN}', b'[]', b'x' * 65537):
            with self.subTest(size=len(body)), self.assertRaises(self.module.TBankProtocolError):
                self.module.verify_notification(body, **kwargs)

    def test_unknown_or_inconsistent_status_cannot_be_accepted(self):
        for changes in ({"Status": "CUSTOM_PAID"}, {"Success": "true"}, {"Status": "CONFIRMED", "Success": False}, {"ErrorCode": "999"}, {"Amount": True}):
            with self.subTest(changes=changes), self.assertRaises(self.module.TBankProtocolError):
                self.verify(self.notice(**changes))

    def test_provider_rejection_is_not_success_and_is_not_retried(self):
        self.response = {"Success": False, "ErrorCode": "999", "Message": self.password, "Details": self.terminal}
        with self.assertRaises(self.module.TBankRejected) as result:
            self.client.initialize_payment(self.payment())
        self.assertNotIn(self.password, str(result.exception))
        self.assertEqual(len(self.calls), 1)

    def test_ambiguous_mutation_response_is_unknown_and_never_retried(self):
        for status, raw in ((500, b'{}'), (302, b'{}'), (200, b'bad-json'), (200, b'[]'), (200, b'{"Success":NaN}')):
            with self.subTest(status=status, raw=raw):
                self.calls.clear()
                self.http_status, self.raw = status, raw
                with self.assertRaises(self.module.TBankUnknownResult):
                    self.client.initialize_payment(self.payment())
                self.assertEqual(len(self.calls), 1)

    def test_configuration_is_disabled_by_default_and_production_requires_gate(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(self.module.TBankConfigurationError):
            self.module.TBankClient.from_environment()
        with self.assertRaises(self.module.TBankConfigurationError):
            self.module.TBankClient(terminal_key=self.terminal, password=self.password, environment="production")
        with self.assertRaises(self.module.TBankConfigurationError):
            self.module.TBankClient(terminal_key=self.terminal, password=self.password, environment="https://attacker.example")
        self.assertEqual(self.calls, [])

    def test_network_errors_do_not_leak_context_or_claim_no_charge(self):
        from urllib.error import URLError
        with patch.object(self.client._opener, "open", side_effect=URLError(self.password)):
            try:
                self.client.initialize_payment(self.payment())
            except self.module.TBankUnknownResult as error:
                self.assertIsNone(error.__context__)
                output = traceback.format_exc()
            else:
                self.fail("Network uncertainty was swallowed")
        self.assertNotIn(self.password, output)
        self.assertNotIn(self.terminal, output)
        self.assertNotIn(self.password, repr(self.client))

    def test_missing_or_mismatched_mutation_response_cannot_be_success(self):
        original = dict(self.response)
        for changes in ({"PaymentId": None}, {"OrderId": "other"}, {"TerminalKey": "other"}, {"Amount": 1}, {"PaymentURL": "javascript:alert(1)"}):
            with self.subTest(changes=changes), self.assertRaises(self.module.TBankUnknownResult):
                self.response = {**original, **changes}
                self.client.initialize_payment(self.payment())

    def test_lookup_rejects_another_payment(self):
        self.response["PaymentId"] = "different"
        with self.assertRaises(self.module.TBankProtocolError):
            self.client.get_payment("5001")

    def test_incomplete_chunked_response_is_unknown_without_raw_exception(self):
        self.broken_chunk = True
        with self.assertRaises(self.module.TBankUnknownResult) as caught:
            self.client.initialize_payment(self.payment())
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(len(self.calls), 1)

    def test_invalid_deadline_or_callback_url_fails_before_network(self):
        for change in ({"RedirectDueDate": "invalid"}, {"RedirectDueDate": "2000-01-01T00:00:00+00:00"}, {"NotificationURL": "https://marketplace.example:broken/notice"}):
            with self.subTest(change=change), self.assertRaises(self.module.TBankProtocolError):
                self.client.initialize_payment({**self.payment(), **change})
        self.assertEqual(self.calls, [])
