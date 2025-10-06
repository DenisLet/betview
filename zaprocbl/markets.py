import json, requests, time, hmac, hashlib
from typing import Any
def build_api_key_auth_headers(
    api_key: str,
    api_secret: str,
    req_data: Any,
) -> Any:
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"

    param_str = timestamp + api_key + recv_window + str(req_data)
    signature = hmac.new(
        api_secret.encode("utf-8"),
        param_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "X-CITRO-SIGNATURE": signature,
        "X-CITRO-API-KEY": api_key,
        "X-CITRO-TIMESTAMP": timestamp,
        "X-CITRO-RECV-WINDOW": recv_window,
    }
URL = "https://api.citronus.pro/public/v1/jsonrpc"
API_KEY = "efea345d-d460-4b63-8b1d-c6d0ad98bd79"
SECRET  = "cad212a852e4efd28698b4bf7e13988483da768b125886eb7f45058601b6324b5ef62e595bd414141033963bb35a4f191a11daf577978be9822a237e1934738b"

body = {"jsonrpc":"2.0","method":"create_order","params":{"category":"spot", "data":{
    "symbol": "BTC/USDT",
    "action": "sell",
    "type": "limit",
    "amount": 0.01,
    "price": 111600,
}},"id":str(1)}
auth_headers = build_api_key_auth_headers(API_KEY, SECRET, body)
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    **auth_headers,
}
r = requests.post(URL, headers=headers, data=json.dumps(body))
print(r.status_code, r.text)
