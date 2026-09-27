from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import sys
import time
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from urllib.parse import quote, urlparse

try:
    from curl_cffi.requests import AsyncSession
    from curl_cffi.requests.errors import RequestsError
except ModuleNotFoundError:
    raise SystemExit(
        "Thiếu curl_cffi. Cài bằng: py -m pip install -r requirements.txt"
    ) from None


APPLICATION_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
DATA_DIR = APPLICATION_DIR / "data"
ACCOUNTS_FILE = DATA_DIR / "accounts.txt"
CODES_FILE = DATA_DIR / "codes.txt"
PROXIES_FILE = DATA_DIR / "proxies.txt"

BASE_URL = "https://sg-act.playerinfinite.com"
REDEEM_PATH = "api/proxy/present/CdkV2/RedeemCDKey"
CHECK_URL = f"{BASE_URL}/{REDEEM_PATH}"
APP_ID = "10005"
APP_KEY = "intel#!2022$act"
CONCURRENCY = 10
TIMEOUT = 20
RETRIES = 3
REQUEST_DELAY_MIN = 1.5
REQUEST_DELAY_MAX = 3.0
RATE_LIMIT_DELAY = 10.0
SYSTEM_ERROR_DELAY = 15.0

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "vi,fr-FR;q=0.9,fr;q=0.8,en-US;q=0.7,en;q=0.6",
    "content-type": "application/json",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "origin": "https://redeem.df.garena.sg",
    "referer": "https://redeem.df.garena.sg/",
}

MESSAGES = {
    0: ("SUCCESS", "Đã nhận thành công! Vui lòng kiểm tra thư trong game.", False),
    51: ("SYSTEM_ERROR", "Lỗi hệ thống.", True),
    300001: ("AUTH_EXPIRED", "Phiên đăng nhập đã hết hạn.", False),
    400053: ("ACCOUNT_LIMIT", "Tài khoản đã đổi code này.", False),
    400054: ("INVALID", "CDKey không hợp lệ.", False),
    400067: ("GROUP_LIMIT", "Tài khoản đạt giới hạn của nhóm CDKey.", False),
    400068: ("CODE_LIMIT", "CDKey đã hết lượt đổi.", False),
    400069: ("NOT_STARTED", "CDKey chưa đến thời gian đổi.", False),
    400070: ("EXPIRED", "CDKey đã hết thời gian đổi.", False),
    400072: ("ALREADY_REDEEMED", "Tài khoản đã đổi CDKey này.", False),
    400073: ("CONFIG_ERROR", "Lỗi cấu hình gói CDKey.", False),
    503001: ("NOT_ELIGIBLE", "Tài khoản chưa đủ điều kiện.", False),
    503701: ("NETWORK_ERROR", "Lỗi mạng từ máy chủ.", True),
}


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def read_lines(path: Path, *, required: bool = True) -> list[str]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Không tìm thấy {path}")
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def load_accounts() -> list[tuple[str, str]]:
    accounts = []
    for line_number, line in enumerate(read_lines(ACCOUNTS_FILE), start=1):
        if ":" not in line:
            raise ValueError(
                f"{ACCOUNTS_FILE}:{line_number}: phải có dạng openid:token"
            )
        openid, token = line.split(":", 1)
        if not openid.strip() or not token.strip():
            raise ValueError(f"{ACCOUNTS_FILE}:{line_number}: thiếu openid hoặc token")
        accounts.append((openid.strip(), token.strip()))
    return list(dict.fromkeys(accounts))


def load_codes() -> list[str]:
    return list(dict.fromkeys(read_lines(CODES_FILE)))


def normalize_proxy(value: str) -> str:
    if "://" in value:
        parsed = urlparse(value)
        if not parsed.hostname or not parsed.port:
            raise ValueError("proxy URL thiếu host hoặc port")
        return value

    parts = value.split(":", 3)
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{int(port)}"
    if len(parts) == 4:
        host, port, username, password = parts
        return f"http://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{int(port)}"
    raise ValueError("proxy phải có dạng ip:port hoặc ip:port:user:pass")


def load_proxies() -> list[str]:
    proxies = []
    for line_number, line in enumerate(
        read_lines(PROXIES_FILE, required=False), start=1
    ):
        try:
            proxies.append(normalize_proxy(line))
        except ValueError as error:
            raise ValueError(f"{PROXIES_FILE}:{line_number}: {error}") from error
    return proxies


def build_url(code: str, openid: str, token: str) -> str:
    request_uuid = str(uuid.uuid4())
    timestamp = math.floor(time.time() + 0.5)
    fields = (
        ("cdkey", code),
        ("channel", "10"),
        ("game_id", "30150"),
        ("gameid", "30150"),
        ("openid", openid),
        ("token", token),
        ("account_type", "1"),
        ("lang_type", "vi"),
        ("u", request_uuid),
        ("a", APP_ID),
        ("ts", str(timestamp)),
    )
    query = "&".join(f"{key}={quote(value, safe='')}" for key, value in fields)
    relative_url = f"{REDEEM_PATH}?{query}"
    signature_input = f"/{relative_url}&appkey={APP_KEY}"
    signature = hashlib.md5(signature_input.encode(), usedforsecurity=False).hexdigest()
    return f"{BASE_URL}/{relative_url}&s={signature}"


async def redeem(
    session: AsyncSession,
    account_number: int,
    openid: str,
    token: str,
    code: str,
) -> dict:
    body = {
        "lang_type": "vi",
        "role_info": {"game_id": "30150"},
        "cdkey": code,
    }

    for attempt in range(1, RETRIES + 2):
        retry_after = 0.0
        try:
            response = await session.post(build_url(code, openid, token), json=body)
            if response.status_code in {429, 500, 502, 503, 504}:
                is_rate_limit = response.status_code == 429
                status, message, retryable = (
                    "RATE_LIMIT" if is_rate_limit else "HTTP_ERROR",
                    "Gửi quá nhanh."
                    if is_rate_limit
                    else f"HTTP {response.status_code}",
                    True,
                )
                if is_rate_limit:
                    try:
                        retry_after = float(response.headers.get("Retry-After", 0))
                    except (TypeError, ValueError):
                        retry_after = 0.0
                api_code = None
                sequence = None
            elif response.status_code == 403:
                status, message, retryable = (
                    "FORBIDDEN",
                    "Proxy, fingerprint hoặc chữ ký bị từ chối.",
                    False,
                )
                api_code = None
                sequence = None
            elif not 200 <= response.status_code < 300:
                status, message, retryable = (
                    "HTTP_ERROR",
                    f"HTTP {response.status_code}",
                    False,
                )
                api_code = None
                sequence = None
            else:
                payload = response.json()
                api_code = int(payload.get("code"))
                server_message = str(payload.get("msg") or "")
                if "request too frequently" in server_message.lower():
                    status, message, retryable = (
                        "RATE_LIMIT",
                        "Gửi quá nhanh.",
                        True,
                    )
                else:
                    status, message, retryable = MESSAGES.get(
                        api_code,
                        ("UNKNOWN", server_message or "Lỗi không xác định.", False),
                    )
                sequence = payload.get("seq")
        except (RequestsError, json.JSONDecodeError, TypeError, ValueError) as error:
            status, message, retryable = (
                "NETWORK_ERROR",
                f"{type(error).__name__}: {error}",
                True,
            )
            api_code = None
            sequence = None
            response = None

        if not retryable or attempt > RETRIES:
            return {
                "account": account_number,
                "code": code,
                "status": status,
                "message": message,
                "api_code": api_code,
                "http_status": response.status_code if response else None,
                "attempts": attempt,
                "sequence": sequence,
            }
        if status == "RATE_LIMIT":
            delay = max(
                retry_after,
                RATE_LIMIT_DELAY * 2 ** (attempt - 1),
            )
            print(
                f"  ACC {account_number}: server giới hạn tốc độ, "
                f"chờ {delay:.0f}s rồi thử lại ({attempt}/{RETRIES})...",
                flush=True,
            )
        elif status == "SYSTEM_ERROR":
            delay = SYSTEM_ERROR_DELAY * 2 ** (attempt - 1)
            print(
                f"  ACC {account_number}: máy chủ lỗi, "
                f"chờ {delay:.0f}s rồi thử lại ({attempt}/{RETRIES})...",
                flush=True,
            )
        else:
            delay = 2 ** (attempt - 1) + random.uniform(0.25, 0.75)
        await asyncio.sleep(delay)

    raise AssertionError("Vòng retry không thể tới đây")


async def find_working_proxies(proxies: list[str], needed: int) -> list[str]:
    if not proxies:
        return []

    working = []
    print(f"Đang kiểm tra proxy, cần {needed} proxy hoạt động...")
    for index, proxy in enumerate(proxies, start=1):
        try:
            async with AsyncSession(
                impersonate="chrome",
                proxy=proxy,
                timeout=8,
                max_clients=1,
                trust_env=False,
            ) as session:
                response = await session.options(
                    CHECK_URL,
                    headers={
                        "origin": "https://redeem.df.garena.sg",
                        "access-control-request-method": "POST",
                    },
                )
            if response.status_code in {200, 204}:
                working.append(proxy)
                print(f"  Proxy #{index}: OK")
                if len(working) >= needed:
                    break
            else:
                print(f"  Proxy #{index}: HTTP {response.status_code}")
        except RequestsError as error:
            print(f"  Proxy #{index}: {type(error).__name__}: {error}")

    if not working:
        print("Không có proxy hoạt động; chuyển sang kết nối trực tiếp.")
    return working


async def run() -> None:
    accounts = load_accounts()
    codes = load_codes()
    proxies = load_proxies()
    if not accounts:
        raise ValueError(f"{ACCOUNTS_FILE} chưa có account")
    if not codes:
        raise ValueError(f"{CODES_FILE} chưa có code")

    proxies = await find_working_proxies(proxies, len(accounts))
    total_jobs = len(accounts) * len(codes)

    print(
        f"Accounts: {len(accounts)} | Codes: {len(codes)} | "
        f"Proxies: {len(proxies)} | Pending: {total_jobs} | "
        f"Concurrent accounts: {min(len(accounts), CONCURRENCY)}"
    )

    async with AsyncExitStack() as stack:
        sessions = []
        for index in range(len(accounts)):
            proxy = proxies[index % len(proxies)] if proxies else None
            session = await stack.enter_async_context(
                AsyncSession(
                    impersonate="chrome",
                    headers=HEADERS,
                    proxy=proxy,
                    timeout=TIMEOUT,
                    max_clients=1,
                    trust_env=False,
                )
            )
            sessions.append(session)

        completed = 0
        progress_lock = asyncio.Lock()
        account_limit = asyncio.Semaphore(CONCURRENCY)

        async def run_account(
            number: int,
            openid: str,
            token: str,
        ) -> None:
            nonlocal completed
            async with account_limit:
                for code_index, code in enumerate(codes):
                    result = await redeem(
                        sessions[number - 1], number, openid, token, code
                    )
                    async with progress_lock:
                        completed += 1
                        print(
                            f"[{completed:>5}/{total_jobs}] "
                            f"ACC {number:<3} {code:<24} "
                            f"{result['status']:<18} {result['message']}",
                            flush=True,
                        )
                    if code_index < len(codes) - 1:
                        await asyncio.sleep(
                            random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                        )

        account_tasks = [
            asyncio.create_task(run_account(number, openid, token))
            for number, (openid, token) in enumerate(accounts, start=1)
        ]
        await asyncio.gather(*account_tasks)


def main() -> None:
    configure_console()
    exit_code = 0
    try:
        asyncio.run(run())
    except (FileNotFoundError, ValueError) as error:
        print(f"Lỗi cấu hình: {error}", file=sys.stderr)
        exit_code = 2
    except KeyboardInterrupt:
        print("\nĐã dừng.")
        exit_code = 130
    finally:
        try:
            input("\nNhấn Enter để thoát...")
        except EOFError:
            pass
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
