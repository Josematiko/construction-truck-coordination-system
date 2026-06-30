import base64
import json
from datetime import datetime
from urllib import error, parse, request

from flask import current_app


class MpesaError(Exception):
    pass


def normalize_phone_number(phone_number):
    digits = ''.join(ch for ch in str(phone_number or '') if ch.isdigit())
    if not digits:
        raise MpesaError("Phone number is required.")

    if digits.startswith('0') and len(digits) == 10:
        digits = '254' + digits[1:]
    elif digits.startswith('7') and len(digits) == 9:
        digits = '254' + digits
    elif digits.startswith('254') and len(digits) == 12:
        pass
    else:
        raise MpesaError("Use 07XXXXXXXX or 2547XXXXXXXX format.")

    if not digits.startswith('2547') or len(digits) != 12:
        raise MpesaError("Phone number must be a Safaricom mobile number.")

    return digits


def _base_url():
    env = (current_app.config.get('MPESA_ENV') or 'sandbox').lower()
    if env == 'production':
        return 'https://api.safaricom.co.ke'
    return 'https://sandbox.safaricom.co.ke'


def _request_timeout():
    try:
        return int(current_app.config.get('MPESA_TIMEOUT', 30))
    except (TypeError, ValueError):
        return 30


def _json_request(url, method='GET', payload=None, headers=None):
    req_headers = {'Content-Type': 'application/json'}
    if headers:
        req_headers.update(headers)

    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')

    req = request.Request(url, data=data, headers=req_headers, method=method)

    try:
        with request.urlopen(req, timeout=_request_timeout()) as response:
            raw = response.read().decode('utf-8') or '{}'
            return json.loads(raw)
    except error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='ignore')
        try:
            parsed = json.loads(body)
            detail = parsed.get('errorMessage') or parsed.get('error_description') or body
        except Exception:
            detail = body or str(exc)
        raise MpesaError(f"M-Pesa API error ({exc.code}): {detail}")
    except error.URLError as exc:
        raise MpesaError(f"Failed to reach M-Pesa API: {exc.reason}")


def _access_token():
    consumer_key = current_app.config.get('MPESA_CONSUMER_KEY')
    consumer_secret = current_app.config.get('MPESA_CONSUMER_SECRET')
    if not consumer_key or not consumer_secret:
        raise MpesaError("M-Pesa credentials are missing. Set MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET.")

    auth = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode('utf-8')).decode('utf-8')
    url = f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials"
    response = _json_request(url, headers={'Authorization': f'Basic {auth}'})
    token = response.get('access_token')
    if not token:
        raise MpesaError("Could not obtain M-Pesa access token.")
    return token


def _stk_password(timestamp):
    shortcode = current_app.config.get('MPESA_SHORTCODE')
    passkey = current_app.config.get('MPESA_PASSKEY')
    if not shortcode or not passkey:
        raise MpesaError("M-Pesa shortcode/passkey missing. Set MPESA_SHORTCODE and MPESA_PASSKEY.")
    encoded = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode('utf-8')).decode('utf-8')
    return shortcode, encoded


def initiate_stk_push(amount, phone_number, account_reference, transaction_desc, callback_url):
    normalized_phone = normalize_phone_number(phone_number)
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    shortcode, password = _stk_password(timestamp)
    token = _access_token()

    payload = {
        'BusinessShortCode': shortcode,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': int(round(float(amount))),
        'PartyA': normalized_phone,
        'PartyB': shortcode,
        'PhoneNumber': normalized_phone,
        'CallBackURL': callback_url,
        'AccountReference': str(account_reference)[:20],
        'TransactionDesc': str(transaction_desc)[:50],
    }

    url = f"{_base_url()}/mpesa/stkpush/v1/processrequest"
    response = _json_request(
        url,
        method='POST',
        payload=payload,
        headers={'Authorization': f'Bearer {token}'}
    )
    return response, normalized_phone


def parse_stk_callback(payload):
    callback = ((payload or {}).get('Body') or {}).get('stkCallback') or {}
    metadata_items = callback.get('CallbackMetadata', {}).get('Item', []) or []
    metadata = {}
    for item in metadata_items:
        name = item.get('Name')
        if name:
            metadata[name] = item.get('Value')

    return {
        'merchant_request_id': callback.get('MerchantRequestID'),
        'checkout_request_id': callback.get('CheckoutRequestID'),
        'result_code': callback.get('ResultCode'),
        'result_desc': callback.get('ResultDesc'),
        'metadata': metadata,
    }
