from __future__ import annotations

import asyncio
import hashlib
import json
import math
import queue
import random
import sys
import threading
import time
import tkinter as tk
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable
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
VERSION = "1.1.0"

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
    log: Callable[[str], None] = print,
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
            log(
                f"  ACC {account_number}: server giới hạn tốc độ, "
                f"chờ {delay:.0f}s rồi thử lại ({attempt}/{RETRIES})..."
            )
        elif status == "SYSTEM_ERROR":
            delay = SYSTEM_ERROR_DELAY * 2 ** (attempt - 1)
            log(
                f"  ACC {account_number}: máy chủ lỗi, "
                f"chờ {delay:.0f}s rồi thử lại ({attempt}/{RETRIES})..."
            )
        else:
            delay = 2 ** (attempt - 1) + random.uniform(0.25, 0.75)
        await asyncio.sleep(delay)

    raise AssertionError("Vòng retry không thể tới đây")


async def find_working_proxies(
    proxies: list[str],
    needed: int,
    log: Callable[[str], None] = print,
) -> list[str]:
    if not proxies:
        return []

    working = []
    log(f"Đang kiểm tra proxy, cần {needed} proxy hoạt động...")
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
                log(f"  Proxy #{index}: OK")
                if len(working) >= needed:
                    break
            else:
                log(f"  Proxy #{index}: HTTP {response.status_code}")
        except RequestsError as error:
            log(f"  Proxy #{index}: {type(error).__name__}: {error}")

    if not working:
        log("Không có proxy hoạt động; chuyển sang kết nối trực tiếp.")
    return working


async def run(log: Callable[[str], None] = print) -> None:
    accounts = load_accounts()
    codes = load_codes()
    proxies = load_proxies()
    if not accounts:
        raise ValueError(f"{ACCOUNTS_FILE} chưa có account")
    if not codes:
        raise ValueError(f"{CODES_FILE} chưa có code")

    proxies = await find_working_proxies(proxies, len(accounts), log)
    total_jobs = len(accounts) * len(codes)

    log(
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
                        sessions[number - 1], number, openid, token, code, log
                    )
                    async with progress_lock:
                        completed += 1
                        log(
                            f"[{completed:>5}/{total_jobs}] "
                            f"ACC {number:<3} {code:<24} "
                            f"{result['status']:<18} {result['message']}"
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


class RedeemApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.running = False

        root.title(f"DF Redeem v{VERSION}")
        root.geometry("920x720")
        root.minsize(760, 620)
        root.configure(background="#F3F7F6")
        root.option_add("*Font", ("Segoe UI", 10))

        style = ttk.Style(root)
        style.theme_use("vista")
        style.configure("App.TFrame", background="#F3F7F6")
        style.configure("Card.TFrame", background="#FFFFFF")
        style.configure(
            "Title.TLabel",
            background="#F3F7F6",
            foreground="#12372A",
            font=("Segoe UI Semibold", 22),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#F3F7F6",
            foreground="#52665F",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Section.TLabel",
            background="#FFFFFF",
            foreground="#12372A",
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Hint.TLabel",
            background="#FFFFFF",
            foreground="#5E6F69",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Status.TLabel",
            background="#E8F5EF",
            foreground="#176A4B",
            padding=(12, 8),
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "Primary.TButton",
            font=("Segoe UI Semibold", 11),
            padding=(18, 10),
        )
        style.configure("Secondary.TButton", padding=(14, 8))

        container = ttk.Frame(root, style="App.TFrame", padding=(28, 22))
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="DF Redeem", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            container,
            text="Dán dữ liệu vào 3 ô bên dưới, sau đó bấm Lưu và chạy.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 16))

        form = ttk.Frame(container, style="Card.TFrame", padding=18)
        form.pack(fill="both", expand=True)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        form.rowconfigure(2, weight=1)

        self.accounts_text = self._create_input(
            form,
            row=0,
            column=0,
            title="1. Tài khoản",
            hint="Mỗi dòng: openid:token",
            height=6,
        )
        self.codes_text = self._create_input(
            form,
            row=0,
            column=1,
            title="2. CDKey",
            hint="Mỗi dòng một code",
            height=6,
        )
        self.proxies_text = self._create_input(
            form,
            row=2,
            column=0,
            title="3. Proxy (không bắt buộc)",
            hint="ip:port hoặc ip:port:user:password",
            height=5,
        )

        log_frame = ttk.Frame(form, style="Card.TFrame")
        log_frame.grid(row=2, column=1, rowspan=2, sticky="nsew", padx=(9, 0), pady=(14, 0))
        ttk.Label(log_frame, text="Kết quả", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            log_frame,
            text="Token và mật khẩu proxy không được ghi vào phần này.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 7))
        self.log_text = tk.Text(
            log_frame,
            height=11,
            wrap="word",
            state="disabled",
            relief="solid",
            borderwidth=1,
            background="#F8FAF9",
            foreground="#243C34",
            selectbackground="#BCE5D3",
            font=("Consolas", 9),
            padx=9,
            pady=8,
        )
        self.log_text.pack(fill="both", expand=True)

        footer = ttk.Frame(container, style="App.TFrame")
        footer.pack(fill="x", pady=(14, 0))
        self.status_label = ttk.Label(
            footer,
            text="Sẵn sàng",
            style="Status.TLabel",
        )
        self.status_label.pack(side="left")
        ttk.Button(
            footer,
            text="Chỉ lưu",
            command=self.save_data,
            style="Secondary.TButton",
        ).pack(side="right", padx=(8, 0))
        self.run_button = ttk.Button(
            footer,
            text="Lưu và chạy",
            command=self.start,
            style="Primary.TButton",
        )
        self.run_button.pack(side="right")

        self.load_data()
        self.accounts_text.focus_set()
        root.bind("<Control-s>", lambda _event: self.save_data())
        root.after(100, self.process_events)

    def _create_input(
        self,
        parent: ttk.Frame,
        *,
        row: int,
        column: int,
        title: str,
        hint: str,
        height: int,
    ) -> tk.Text:
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=(0, 9) if column == 0 else (9, 0),
            pady=(0, 0) if row == 0 else (14, 0),
        )
        ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w")
        ttk.Label(frame, text=hint, style="Hint.TLabel").pack(anchor="w", pady=(2, 7))
        text = tk.Text(
            frame,
            height=height,
            wrap="none",
            undo=True,
            relief="solid",
            borderwidth=1,
            background="#FFFFFF",
            foreground="#172B24",
            insertbackground="#172B24",
            selectbackground="#BCE5D3",
            font=("Consolas", 10),
            padx=9,
            pady=8,
        )
        text.pack(fill="both", expand=True)
        return text

    @staticmethod
    def _text_value(widget: tk.Text) -> str:
        return widget.get("1.0", "end-1c").strip()

    def load_data(self) -> None:
        for widget, path in (
            (self.accounts_text, ACCOUNTS_FILE),
            (self.codes_text, CODES_FILE),
            (self.proxies_text, PROXIES_FILE),
        ):
            if path.exists():
                widget.insert("1.0", path.read_text(encoding="utf-8-sig"))

    def save_data(self, *, notify: bool = True) -> bool:
        accounts = self._text_value(self.accounts_text)
        codes = self._text_value(self.codes_text)
        proxies = self._text_value(self.proxies_text)
        if not accounts:
            messagebox.showerror("Thiếu tài khoản", "Hãy nhập ít nhất một tài khoản.")
            self.accounts_text.focus_set()
            return False
        if not codes:
            messagebox.showerror("Thiếu CDKey", "Hãy nhập ít nhất một CDKey.")
            self.codes_text.focus_set()
            return False

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ACCOUNTS_FILE.write_text(f"{accounts}\n", encoding="utf-8")
        CODES_FILE.write_text(f"{codes}\n", encoding="utf-8")
        if proxies:
            PROXIES_FILE.write_text(f"{proxies}\n", encoding="utf-8")
        elif PROXIES_FILE.exists():
            PROXIES_FILE.unlink()

        if notify:
            self.status_label.configure(text="Đã lưu dữ liệu trên máy")
        return True

    def start(self) -> None:
        if self.running or not self.save_data(notify=False):
            return
        try:
            load_accounts()
            load_codes()
            load_proxies()
        except (FileNotFoundError, ValueError) as error:
            messagebox.showerror("Dữ liệu chưa đúng", str(error))
            return

        self.running = True
        self.run_button.configure(state="disabled", text="Đang chạy...")
        self.status_label.configure(text="Đang xử lý, vui lòng chờ")
        self._clear_log()
        self._append_log("Bắt đầu đổi code...")
        threading.Thread(target=self._run_worker, daemon=True).start()

    def _run_worker(self) -> None:
        try:
            asyncio.run(run(lambda message: self.events.put(("log", message))))
        except (FileNotFoundError, ValueError) as error:
            self.events.put(("error", str(error)))
        except Exception as error:
            self.events.put(("error", f"{type(error).__name__}: {error}"))
        else:
            self.events.put(("done", "Đã xử lý xong tất cả tài khoản và CDKey."))

    def process_events(self) -> None:
        try:
            while True:
                event, message = self.events.get_nowait()
                if event == "log":
                    self._append_log(message)
                elif event == "error":
                    self._finish("Có lỗi xảy ra")
                    self._append_log(f"LỖI: {message}")
                    messagebox.showerror("Không thể tiếp tục", message)
                elif event == "done":
                    self._finish("Đã hoàn tất")
                    self._append_log(message)
        except queue.Empty:
            pass
        self.root.after(100, self.process_events)

    def _finish(self, status: str) -> None:
        self.running = False
        self.run_button.configure(state="normal", text="Lưu và chạy")
        self.status_label.configure(text=status)

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


def main() -> None:
    if "--cli" in sys.argv:
        configure_console()
        try:
            asyncio.run(run())
        except (FileNotFoundError, ValueError) as error:
            print(f"Lỗi cấu hình: {error}", file=sys.stderr)
            raise SystemExit(2) from error
        return

    root = tk.Tk()
    RedeemApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
