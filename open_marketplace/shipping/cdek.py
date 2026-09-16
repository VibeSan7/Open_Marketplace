import datetime
import json
import os
import re
import socket
import time
import uuid
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


PRODUCTION_BASE_URL = "https://api.cdek.ru"
SANDBOX_BASE_URL = "https://api.edu.cdek.ru"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class CdekConfigurationError(Exception):
    pass


class CdekInputError(Exception):
    pass


class CdekProtocolError(Exception):
    pass


class CdekUnknownResult(Exception):
    pass


class CdekHTTPError(Exception):
    def __init__(self, status_code):
        self.status_code = int(status_code)
        super().__init__("CDEK HTTP status %d" % self.status_code)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _is_mapping(value):
    return isinstance(value, dict)


def _raise_response_errors(response, *, operation=None, request_uuid=None):
    errors = response.get("errors")
    if errors:
        raise CdekProtocolError("CDEK response contains errors")
    requests = response.get("requests")
    if requests is not None:
        if not isinstance(requests, list):
            raise CdekProtocolError("CDEK response has malformed requests")
        for request in requests:
            if not isinstance(request, dict):
                raise CdekProtocolError("CDEK response has malformed request")
            matches = (operation is None or request.get("type") == operation) and (request_uuid is None or request.get("request_uuid") == request_uuid)
            if matches and request.get("errors"):
                raise CdekProtocolError("CDEK request contains errors")


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _canonical_uuid(value):
    if not isinstance(value, str):
        raise ValueError
    parsed = uuid.UUID(value)
    canonical = str(parsed)
    if value != canonical:
        raise ValueError
    return canonical


def _stable_number(value):
    if not isinstance(value, str) or not value or len(value) > 40:
        raise ValueError
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in value):
        raise ValueError
    return value


def _aware_timestamp(value):
    if not isinstance(value, str):
        raise ValueError
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


class CdekClient:
    def __init__(self, *, client_id, client_secret, environment, timeout=15, live_enabled=False):
        if not isinstance(client_id, str) or not client_id:
            raise CdekConfigurationError("CDEK client_id is required")
        if not isinstance(client_secret, str) or not client_secret:
            raise CdekConfigurationError("CDEK client_secret is required")
        if environment not in ("sandbox", "production"):
            raise CdekConfigurationError("CDEK environment must be sandbox or production")
        if environment == "production" and live_enabled is not True:
            raise CdekConfigurationError("CDEK production mode is disabled")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
            raise CdekConfigurationError("CDEK timeout must be finite and between 0 and 120 seconds")
        self.client_id = client_id
        self.client_secret = client_secret
        self.environment = environment
        self._endpoint = SANDBOX_BASE_URL if environment == "sandbox" else PRODUCTION_BASE_URL
        self.timeout = timeout
        self._token = None
        self._token_deadline = 0.0

    @classmethod
    def from_environment(cls):
        environment = os.environ.get("CDEK_ENVIRONMENT")
        client_id = os.environ.get("CDEK_CLIENT_ID")
        client_secret = os.environ.get("CDEK_CLIENT_SECRET")
        if environment == "production" and os.environ.get("CDEK_LIVE_ENABLED") != "true":
            raise CdekConfigurationError("CDEK production mode is disabled")
        if environment not in ("sandbox", "production") or not client_id or not client_secret:
            raise CdekConfigurationError("CDEK environment and credentials are required")
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            environment=environment,
            live_enabled=os.environ.get("CDEK_LIVE_ENABLED") == "true",
        )

    @property
    def _base_url(self):
        return self._endpoint

    def _url(self, path):
        return self._base_url.rstrip("/") + path

    def _request_json(self, method, path, *, body=None, expected_statuses, operation, uncertain):
        encoded_body = None
        if body is not None:
            try:
                encoded_body = json.dumps(
                    body,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError):
                raise CdekInputError("CDEK request payload is not valid JSON") from None
        headers = {"Accept": "application/json"}
        if encoded_body is not None:
            headers["Content-Type"] = "application/json"
        if operation != "auth":
            headers["Authorization"] = "Bearer " + self._get_token()
        request = Request(self._url(path), data=encoded_body, headers=headers, method=method)
        opener = build_opener(_NoRedirectHandler())
        failure = None
        response = None
        try:
            response = opener.open(request, timeout=self.timeout)
        except HTTPError as error:
            status = error.code
            try:
                error.close()
            except OSError:
                pass
            failure = ("http", status)
        except (OSError, URLError, socket.timeout, TimeoutError, HTTPException):
            failure = ("network", None)
        if failure is not None:
            kind, status = failure
            if kind == "network":
                if uncertain:
                    raise CdekUnknownResult("CDEK operation result is unknown") from None
                raise CdekProtocolError("CDEK network operation failed") from None
            if uncertain and status >= 500:
                raise CdekUnknownResult("CDEK operation result is unknown") from None
            raise CdekHTTPError(status)

        status = response.getcode()
        if status not in expected_statuses:
            response.close()
            if uncertain and status >= 500:
                raise CdekUnknownResult("CDEK operation result is unknown") from None
            raise CdekHTTPError(status)

        read_failure = False
        data = None
        try:
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if response.length is not None and response.length != 0:
                read_failure = True
        except (OSError, URLError, socket.timeout, TimeoutError, HTTPException):
            read_failure = True
        finally:
            response.close()
        if read_failure:
            if uncertain:
                raise CdekUnknownResult("CDEK operation result is unknown") from None
            raise CdekProtocolError("CDEK response could not be read") from None
        if len(data) > MAX_RESPONSE_BYTES:
            if uncertain:
                raise CdekUnknownResult("CDEK operation result is unknown") from None
            raise CdekProtocolError("CDEK response exceeds the size limit") from None
        parsed = None
        try:
            text = data.decode("utf-8")
            parsed = json.loads(text, object_pairs_hook=_json_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, TypeError, ValueError, RecursionError):
            pass
        if not isinstance(parsed, dict):
            if uncertain:
                raise CdekUnknownResult("CDEK operation result is unknown") from None
            raise CdekProtocolError("CDEK response must be an object") from None
        return parsed

    def _get_token(self):
        now = time.monotonic()
        if self._token is not None and now < self._token_deadline:
            return self._token
        query = urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        start = time.monotonic()
        response = self._request_json(
            "POST",
            "/v2/oauth/token?" + query,
            expected_statuses=(200,),
            operation="auth",
            uncertain=False,
        )
        _raise_response_errors(response)
        token = response.get("access_token")
        token_type = response.get("token_type")
        expires_in = response.get("expires_in")
        if (
            not isinstance(token, str)
            or not token
            or re.fullmatch(r"[A-Za-z0-9\-._~+/]+=*", token) is None
            or token_type != "bearer"
            or isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or expires_in <= 0
        ):
            raise CdekProtocolError("CDEK token response is malformed")
        self._token = token
        self._token_deadline = start + expires_in
        return token

    def _authorized_json(self, method, path, *, body=None, expected_statuses, operation, uncertain=False):
        return self._request_json(
            method,
            path,
            body=body,
            expected_statuses=expected_statuses,
            operation=operation,
            uncertain=uncertain,
        )

    def calculate_tariff(self, payload):
        if not _is_mapping(payload) or "type" not in payload or "currency" not in payload:
            raise CdekInputError("CDEK tariff type and currency are required")
        if payload["type"] is None or payload["currency"] is None:
            raise CdekInputError("CDEK tariff type and currency are required")
        response = self._authorized_json(
            "POST",
            "/v2/calculator/tariff",
            body=payload,
            expected_statuses=(200,),
            operation="calculate_tariff",
        )
        _raise_response_errors(response)
        required = ("currency", "delivery_sum", "period_max", "period_min", "total_sum", "weight_calc")
        if any(field not in response for field in required):
            raise CdekProtocolError("CDEK tariff response is incomplete")
        return response

    def create_order(self, payload):
        if not _is_mapping(payload):
            raise CdekInputError("CDEK order payload must be an object")
        order_type = payload.get("type")
        if isinstance(order_type, bool) or not isinstance(order_type, int) or order_type not in (1, 2):
            raise CdekInputError("CDEK order type is required")
        if "tariff_code" not in payload or payload["tariff_code"] is None:
            raise CdekInputError("CDEK tariff_code is required")
        if not isinstance(payload.get("recipient"), dict) or not payload["recipient"]:
            raise CdekInputError("CDEK recipient is required")
        if not isinstance(payload.get("packages"), list) or not payload["packages"]:
            raise CdekInputError("CDEK packages are required")
        has_from_location = payload.get("from_location") is not None
        has_shipment_point = payload.get("shipment_point") is not None
        has_to_location = payload.get("to_location") is not None
        has_delivery_point = payload.get("delivery_point") is not None
        if has_from_location == has_shipment_point or has_to_location == has_delivery_point:
            raise CdekInputError("CDEK order routes are invalid")
        if order_type == 1 and "number" not in payload:
            raise CdekInputError("CDEK order number is required")
        if "number" in payload:
            try:
                _stable_number(payload["number"])
            except (TypeError, ValueError):
                raise CdekInputError("CDEK order number is invalid") from None
        response = self._authorized_json(
            "POST",
            "/v2/orders",
            body=payload,
            expected_statuses=(202,),
            operation="create",
            uncertain=True,
        )
        return self._accepted_order(response, operation="CREATE")

    def _accepted_order(self, response, *, operation, expected_uuid=None):
        _raise_response_errors(response, operation=operation)
        valid = False
        try:
            if operation == "CREATE" or "entity" in response:
                entity = response.get("entity")
                if not isinstance(entity, dict):
                    raise ValueError
                order_uuid = _canonical_uuid(entity.get("uuid"))
                if expected_uuid is not None and order_uuid != expected_uuid:
                    raise ValueError
            request_state(response, operation=operation)
            valid = True
        except (ValueError, CdekProtocolError):
            pass
        if not valid:
            raise CdekUnknownResult("CDEK operation result is unknown")
        return response

    def get_order(self, *, order_uuid):
        try:
            canonical = _canonical_uuid(order_uuid)
        except (AttributeError, TypeError, ValueError):
            raise CdekInputError("CDEK order UUID is invalid") from None
        response = self._authorized_json(
            "GET",
            "/v2/orders/" + canonical,
            expected_statuses=(200,),
            operation="get",
        )
        _raise_response_errors(response, operation="GET")
        if not isinstance(response.get("entity"), dict) or response["entity"].get("uuid") != canonical:
            raise CdekProtocolError("CDEK order identity does not match")
        return response

    def find_order(self, *, number):
        try:
            stable_number = _stable_number(number)
        except (TypeError, ValueError):
            raise CdekInputError("CDEK order number is invalid") from None
        response = self._authorized_json(
            "GET",
            "/v2/orders?" + urlencode({"im_number": stable_number}),
            expected_statuses=(200,),
            operation="find",
        )
        _raise_response_errors(response, operation="GET")
        if not isinstance(response.get("entity"), dict) or response["entity"].get("number") != stable_number:
            raise CdekProtocolError("CDEK order identity does not match")
        return response

    def delete_order(self, *, order_uuid):
        try:
            canonical = _canonical_uuid(order_uuid)
        except (AttributeError, TypeError, ValueError):
            raise CdekInputError("CDEK order UUID is invalid") from None
        response = self._authorized_json(
            "DELETE",
            "/v2/orders/" + canonical,
            expected_statuses=(202,),
            operation="delete",
            uncertain=True,
        )
        return self._accepted_order(response, operation="DELETE", expected_uuid=canonical)


def request_state(response, *, operation, request_uuid=None):
    if not _is_mapping(response) or not isinstance(operation, str) or not operation:
        raise CdekInputError("CDEK request state input is invalid")
    if request_uuid is not None:
        try:
            expected_uuid = _canonical_uuid(request_uuid)
        except (AttributeError, TypeError, ValueError):
            raise CdekInputError("CDEK request UUID is invalid") from None
    else:
        expected_uuid = None
    _raise_response_errors(response, operation=operation, request_uuid=expected_uuid)
    requests = response.get("requests")
    if not isinstance(requests, list):
        raise CdekProtocolError("CDEK response has no request state")
    matches = []
    for request in requests:
        if not isinstance(request, dict):
            raise CdekProtocolError("CDEK response has malformed request")
        request_type = request.get("type")
        state = request.get("state")
        if not isinstance(request_type, str) or not isinstance(state, str):
            raise CdekProtocolError("CDEK request state is malformed")
        if state not in ("ACCEPTED", "WAITING", "SUCCESSFUL", "INVALID"):
            raise CdekProtocolError("CDEK request state is unknown")
        try:
            _aware_timestamp(request.get("date_time"))
        except (TypeError, ValueError):
            raise CdekProtocolError("CDEK request timestamp is malformed") from None
        if "request_uuid" in request:
            try:
                request_id = _canonical_uuid(request["request_uuid"])
            except (AttributeError, TypeError, ValueError):
                raise CdekProtocolError("CDEK request UUID is malformed") from None
        else:
            request_id = None
        if request_type == operation and (expected_uuid is None or request_id == expected_uuid):
            matches.append(state)
    if len(matches) != 1:
        raise CdekProtocolError("CDEK request state is ambiguous")
    return matches[0]


def delivery_status(response, *, expected_uuid, expected_number):
    if not _is_mapping(response):
        raise CdekProtocolError("CDEK order response is malformed")
    try:
        expected_entity_uuid = _canonical_uuid(expected_uuid)
        _stable_number(expected_number)
    except (AttributeError, TypeError, ValueError):
        raise CdekInputError("CDEK expected order identity is invalid") from None
    _raise_response_errors(response, operation="GET")
    entity = response.get("entity")
    if not isinstance(entity, dict):
        raise CdekProtocolError("CDEK order entity is missing")
    try:
        entity_uuid = _canonical_uuid(entity.get("uuid"))
    except (AttributeError, TypeError, ValueError):
        raise CdekProtocolError("CDEK order entity is malformed") from None
    if entity_uuid != expected_entity_uuid or entity.get("number") != expected_number:
        raise CdekProtocolError("CDEK order identity does not match")
    statuses = entity.get("statuses")
    if statuses is None:
        raise CdekProtocolError("CDEK order statuses are missing")
    if not isinstance(statuses, list):
        raise CdekProtocolError("CDEK order statuses are malformed")
    active = []
    for status in statuses:
        if not isinstance(status, dict) or not isinstance(status.get("deleted"), bool):
            raise CdekProtocolError("CDEK order status is malformed")
        if not isinstance(status.get("code"), str) or not status["code"]:
            raise CdekProtocolError("CDEK order status is malformed")
        try:
            date_time = _aware_timestamp(status.get("date_time"))
        except (TypeError, ValueError):
            raise CdekProtocolError("CDEK order status timestamp is malformed") from None
        if not status["deleted"]:
            active.append((date_time, status["code"]))
    if not active:
        return None
    newest_time = max(item[0] for item in active)
    newest_codes = {code for timestamp, code in active if timestamp == newest_time}
    if len(newest_codes) != 1:
        raise CdekProtocolError("CDEK order status is ambiguous")
    return next(iter(newest_codes))
