import hashlib
import hmac
import json
import math
import os
import re
from datetime import UTC, datetime, timedelta
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE_URLS = {"sandbox": "https://rest-api-test.tinkoff.ru", "production": "https://securepay.tinkoff.ru"}
_MAX_RESPONSE = 2 * 1024 * 1024
_MAX_NOTICE = 64 * 1024
_NOTICE_STATUSES = {"AUTHORIZED", "CONFIRMED", "REVERSED", "REFUNDED", "PARTIAL_REFUNDED", "REJECTED", "3DS_CHECKING", "DEADLINE_EXPIRED"}


class TBankConfigurationError(ValueError):
    pass


class TBankProtocolError(ValueError):
    pass


class TBankRejected(RuntimeError):
    pass


class TBankUnknownResult(RuntimeError):
    pass


def _invalid():
    raise TBankProtocolError("Invalid T-Bank message.")


def _text(value):
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        _invalid()
    return value


def _deal_id(value):
    if type(value) not in (str, int) or re.fullmatch(r"[1-9][0-9]*", str(value)) is None:
        _invalid()
    return str(value)


def _amount(value, minimum=1):
    if type(value) is not int or value < minimum:
        _invalid()
    return value


def _https_url(value):
    valid = False
    try:
        parsed = urlsplit(_text(value))
        parsed.port
        valid = parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None and not parsed.fragment
    except ValueError:
        pass
    if not valid:
        _invalid()
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _json(raw, limit):
    if not isinstance(raw, bytes) or len(raw) > limit:
        _invalid()
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=lambda value: _invalid())
    except (ValueError, UnicodeError, RecursionError):
        pass
    else:
        if isinstance(data, dict):
            return data
    _invalid()


def signature(payload, password):
    _text(password)
    if not isinstance(payload, dict) or "Password" in payload or any(not isinstance(key, str) for key in payload):
        _invalid()
    values = {"Password": password}
    for key, value in payload.items():
        if key == "Token" or isinstance(value, (dict, list)):
            continue
        if type(value) is bool:
            values[key] = "true" if value else "false"
        elif type(value) in (str, int):
            values[key] = str(value)
        else:
            _invalid()
    return hashlib.sha256("".join(values[key] for key in sorted(values)).encode("utf-8")).hexdigest()


def verify_notification(raw, *, terminal_key, password, expected_order_id, expected_payment_id, expected_amount, expected_deal_id):
    payload = _json(raw, _MAX_NOTICE)
    token = payload.get("Token")
    if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{64}", token) is None:
        _invalid()
    if not hmac.compare_digest(token, signature(payload, password)):
        _invalid()
    if (payload.get("TerminalKey") != _text(terminal_key)
            or payload.get("OrderId") != _text(expected_order_id)
            or payload.get("PaymentId") != _text(expected_payment_id)
            or _deal_id(payload.get("SpAccumulationId")) != _deal_id(expected_deal_id)):
        _invalid()
    status, success = payload.get("Status"), payload.get("Success")
    if not isinstance(status, str) or status not in _NOTICE_STATUSES or type(success) is not bool:
        _invalid()
    if not isinstance(payload.get("ErrorCode"), str) or (success and payload["ErrorCode"] != "0"):
        _invalid()
    current = _amount(payload.get("Amount"), 0)
    original = _amount(expected_amount, 0)
    if current > original or (status in {"AUTHORIZED", "CONFIRMED"} and (current != original or not success)):
        _invalid()
    return {"order_id": payload["OrderId"], "payment_id": payload["PaymentId"],
            "deal_id": _deal_id(payload["SpAccumulationId"]), "amount": current, "status": status, "success": success}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class TBankClient:
    def __init__(self, *, terminal_key, password, environment, live_enabled=False, timeout=15):
        if (not isinstance(terminal_key, str) or not terminal_key or not isinstance(password, str) or not password
                or type(environment) is not str or environment not in BASE_URLS or (environment == "production" and live_enabled is not True)
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 120):
            raise TBankConfigurationError("T-Bank integration is not configured or enabled.")
        self._terminal_key = terminal_key
        self._password = password
        self._base_url = BASE_URLS[environment]
        self._timeout = timeout
        self._opener = build_opener(_NoRedirect())

    @classmethod
    def from_environment(cls):
        return cls(terminal_key=os.environ.get("TBANK_TERMINAL_KEY"), password=os.environ.get("TBANK_PASSWORD"),
                   environment=os.environ.get("TBANK_ENVIRONMENT"), live_enabled=os.environ.get("TBANK_LIVE_ENABLED") == "true")

    def _post(self, method, payload, *, mutation):
        if any(key in payload for key in ("TerminalKey", "Token", "Password")):
            _invalid()
        body = {**payload, "TerminalKey": self._terminal_key}
        body["Token"] = signature(body, self._password)
        try:
            encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, UnicodeError, RecursionError):
            encoded = None
        if encoded is None:
            _invalid()
        request = Request(self._base_url + "/v2/" + method, data=encoded,
                          headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        valid = False
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    _invalid()
                result = _json(response.read(_MAX_RESPONSE + 1), _MAX_RESPONSE)
                if response.length is not None and response.length != 0:
                    _invalid()
            if type(result.get("Success")) is not bool or not isinstance(result.get("ErrorCode"), str):
                _invalid()
            if result["Success"]:
                if result["ErrorCode"] != "0":
                    _invalid()
                self._validate_response(method, payload, result)
            elif not result["ErrorCode"] or result["ErrorCode"] == "0":
                _invalid()
            valid = True
        except HTTPError as exc:
            exc.close()
        except (URLError, OSError, HTTPException, TBankProtocolError):
            pass
        # Suppressing display alone retains the raw error in __context__.
        if not valid:
            if mutation:
                raise TBankUnknownResult("T-Bank result is unknown; reconcile before any retry.")
            raise TBankProtocolError("Unable to reconcile T-Bank payment.")
        if not result["Success"]:
            raise TBankRejected("T-Bank rejected the request; this does not establish the payment balance.")
        return result

    def _validate_response(self, method, payload, reply):
        if method == "createSpDeal":
            _deal_id(reply.get("SpAccumulationId"))
            return
        if reply.get("TerminalKey") != self._terminal_key:
            _invalid()
        _text(reply.get("OrderId"))
        for key in ("OrderId", "PaymentId"):
            if key in payload and reply.get(key) != payload[key]:
                _invalid()
        if method == "CheckOrder":
            if type(reply.get("Payments")) is not list:
                _invalid()
            for payment in reply["Payments"]:
                if type(payment) is not dict:
                    _invalid()
                _text(payment.get("PaymentId"))
                _text(payment.get("Status"))
            return
        _text(reply.get("PaymentId"))
        _text(reply.get("Status"))
        if method in {"Init", "GetState"}:
            _amount(reply.get("Amount"), minimum=0)
        if method == "Init":
            if reply["Amount"] != payload["Amount"]:
                _invalid()
            _https_url(reply.get("PaymentURL"))
        if method == "Cancel":
            original = _amount(reply.get("OriginalAmount"), minimum=0)
            remaining = _amount(reply.get("NewAmount"), minimum=0)
            if remaining > original:
                _invalid()

    def create_deal(self, deal_type):
        if deal_type not in {"N1", "1N", "NN"}:
            _invalid()
        return self._post("createSpDeal", {"SpDealType": deal_type}, mutation=True)

    def initialize_payment(self, payload):
        if not isinstance(payload, dict):
            _invalid()
        _text(payload.get("OrderId"))
        _amount(payload.get("Amount"), 100)
        if payload.get("Currency") != 643 or payload.get("PayType") != "T":
            _invalid()
        if ("DealId" in payload) == ("CreateDealWithType" in payload):
            _invalid()
        if "DealId" in payload:
            _deal_id(payload["DealId"])
        elif payload["CreateDealWithType"] != "NN":
            _invalid()
        if isinstance(payload.get("DATA"), dict) and {"SpAccumulationId", "StartSpAccumulation", "SpFinalPayout"} & set(payload["DATA"]):
            _invalid()
        for name in ("NotificationURL", "SuccessURL", "FailURL"):
            _https_url(payload.get(name))
        valid_deadline = False
        try:
            deadline = datetime.fromisoformat(_text(payload.get("RedirectDueDate")))
            interval = deadline - datetime.now(UTC)
            valid_deadline = timedelta(minutes=1) <= interval <= timedelta(days=90)
        except (ValueError, TypeError):
            pass
        if not valid_deadline:
            _invalid()
        return self._post("Init", payload, mutation=True)

    def get_payment(self, payment_id):
        return self._post("GetState", {"PaymentId": _text(payment_id)}, mutation=False)

    def check_order(self, order_id):
        return self._post("CheckOrder", {"OrderId": _text(order_id)}, mutation=False)

    def confirm_payment(self, payment_id, amount):
        return self._post("Confirm", {"PaymentId": _text(payment_id), "Amount": _amount(amount)}, mutation=True)

    def cancel_payment(self, payment_id, amount, operation_id):
        return self._post("Cancel", {"PaymentId": _text(payment_id), "Amount": _amount(amount, 100),
                                     "ExternalRequestId": _text(operation_id)}, mutation=True)
