# # create_key.py
# import json, requests
#
# URL = "https://api.citronus.pro/public/v1/api-keys/"
# JWT = "eyJhbGciOiJSUzI1NiIsImtpZCI6InZ3c3FaRUZHRFpydkd3Tmg4ZkpqSkxyYUVkaTdJVDZ1LWhnZlQyQ0F0RUkiLCJ0eXAiOiJKV1QifQ.eyJleHAiOjE4MDQ3ODIyNzUsInVpZCI6IjZlZjlmNWQzLWM1YjAtNGExYS1iZWUzLTZhODE0NDQzYTUwNCIsInN1YiI6MTUzNCwiY2xpZW50X3R5cGUiOiJ1c2VyIiwidXNlcm5hbWUiOiJVc2VyLXBybzloazJpbGsifQ.ga9Mm7QtTJjMk5lbAxia5wnXheEXGayIPURGCr-kgNC9ukoSD27GqtIHTjXZ6odGPKCOAH3w51u-HRdCLb1Ma9bPPZFE6eQMRdWRnwjh2OKRtN2gtSKHEQf6is78t78ifBBC-wDV1GQ_xVYgW-sDRAyNW_qFKkJAFZLWfQEASoBAY4RzmMm6wjARbtZyFJxB2IPOlt_PLZ7hkoq5dKvfif4AhCP10EZsRZBs2-pSU2aYbh6DMW7nNuGOT_G8alN8UXvFqS92oijQoagUVDOc_u0FfB-nVfVwO-Lr5fVhKETBqUeXYHUCY9fstRjgbDI3R_xf6v2Yh-OI1EP0b1_U3Q"
#
# headers = {
#     "Authorization": f"Bearer {JWT}",
#     "Accept": "application/json",
#     "Content-Type": "application/json",
# }
#
# body = {
#     "label": "Docs quick test7",
# }
#
# r = requests.post(URL, headers=headers, data=json.dumps(body), timeout=15)
# print("STATUS:", r.status_code)
# print(r.text)
# import json, requests, time, hmac, hashlib
# from typing import Any, Dict as AnyDict
#
# def build_api_key_auth_headers(
#     api_key: str,
#     api_secret: str,
#     req_data: Any,   # в подписи используется str(req_data)
# ) -> AnyDict:
#     timestamp = str(int(time.time() * 1000))
#     recv_window = "5000"
#
#     param_str = timestamp + api_key + recv_window + str(req_data)
#     signature = hmac.new(
#         api_secret.encode("utf-8"),
#         param_str.encode("utf-8"),
#         hashlib.sha256,
#     ).hexdigest()
#
#     return {
#         "X-CITRO-SIGNATURE": signature,
#         "X-CITRO-API-KEY": api_key,
#         "X-CITRO-TIMESTAMP": timestamp,
#         "X-CITRO-RECV-WINDOW": recv_window,
#     }
#
# URL = "https://api.citronus.pro/public/v1/jsonrpc"
# API_KEY = "efea345d-d460-4b63-8b1d-c6d0ad98bd79"
# API_SECRET  = "cad212a852e4efd28698b4bf7e13988483da768b125886eb7f45058601b6324b5ef62e595bd414141033963bb35a4f191a11daf577978be9822a237e1934738b"
#
# body = {"jsonrpc":"2.0","method":"tickers","params":{"category":"futures","symbol": "BTC/USDT"},"id":"1"}
#
# headers = {
#     "Content-Type": "application/json",
#     "Accept": "application/json",
#     **build_api_key_auth_headers(API_KEY, API_SECRET, body),
# }
#
# resp = requests.post(URL, headers=headers, data=json.dumps(body))
# print(resp.status_code, resp.text)
import json, requests, time, hmac, hashlib
from typing import Any, Optional
from email.utils import parsedate_to_datetime

URL = "https://api.citronus.pro/public/v1/jsonrpc"
API_KEY = "efea345d-d460-4b63-8b1d-c6d0ad98bd79"
SECRET  = "cad212a852e4efd28698b4bf7e13988483da768b125886eb7f45058601b6324b5ef62e595bd414141033963bb35a4f191a11daf577978be9822a237e1934738b"

# ------- ВСПОМОГАТЕЛЬНОЕ -------

def now_ms() -> int:
    return int(time.time() * 1000)

def get_server_epoch_ms(url: str, timeout: float = 3.0) -> Optional[int]:
    """
    Берём заголовок Date у твоего же хоста.
    HEAD может вернуть 405 на некоторых конфигурациях — тогда пробуем GET.
    """
    for method in ("HEAD", "GET"):
        try:
            resp = requests.request(method, url, timeout=timeout)
            date_hdr = resp.headers.get("Date")
            if date_hdr:
                dt = parsedate_to_datetime(date_hdr)
                # Должно быть UTC по RFC 7231; на всякий случай нормализуем:
                if dt.tzinfo is None:
                    # считаем как UTC
                    epoch_ms = int(dt.timestamp() * 1000)
                else:
                    epoch_ms = int(dt.astimezone(tz=None).timestamp() * 1000)
                return epoch_ms
        except Exception:
            pass
    return None

def measure_skew_ms() -> int:
    local_ms = now_ms()
    srv_ms = get_server_epoch_ms(URL)
    if srv_ms is None:
        # Фолбэк: без коррекции (лучше чем ничего)
        return 0
    return srv_ms - local_ms

def build_api_key_auth_headers(
    api_key: str,
    api_secret: str,
    req_data: Any,
    recv_window: int = 15000,  # Временно увеличим окно
    skew_ms: int = 0,
) -> dict:
    # Корректируем timestamp на измеренный skew
    timestamp_ms = now_ms() + skew_ms
    timestamp = str(timestamp_ms)
    recv_window_str = str(recv_window)

    # ВАЖНО: подпись над СТРОГО тем же JSON, что отправляем.
    # Поэтому сериализуем req_data заранее (без пробелов, стабильный порядок ключей не обязателен, но консистентность важна).
    req_str = json.dumps(req_data, separators=(",", ":"), ensure_ascii=False)

    param_str = timestamp + api_key + recv_window_str + req_str
    signature = hmac.new(
        api_secret.encode("utf-8"),
        param_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "X-CITRO-SIGNATURE": signature,
        "X-CITRO-API-KEY": api_key,
        "X-CITRO-TIMESTAMP": timestamp,
        "X-CITRO-RECV-WINDOW": recv_window_str,
    }

# --------- ПРИМЕР ВЫЗОВА ---------

if __name__ == "__main__":
    # 1) Меряем скью
    skew_ms = measure_skew_ms()
    print(f"[dbg] measured skew_ms={skew_ms:+d}  (~{skew_ms/1000:.3f}s)")

    # 2) Тело запроса
    body = {
        "jsonrpc": "2.0",
        "method": "create_order",
        "params": {
            "category": "spot",
            "data": {
                "action": "buy",
                "amount": "0.1",
                "symbol": "BTC/USDT",
                "type": "market",
            },
        },
        "id": "1",
    }

    # 3) Хэдеры (с учётом скью, и расширенного окна на время починки часов)
    auth_headers = build_api_key_auth_headers(API_KEY, SECRET, body, recv_window=60000, skew_ms=skew_ms)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **auth_headers,
    }

    # 4) Отправка
    r = requests.post(URL, headers=headers, data=json.dumps(body, separators=(",", ":")))
    print(r.status_code, r.text)
