# DF Redeem

Tool dòng lệnh giúp đổi nhiều Delta Force CDKey cho nhiều tài khoản, hỗ trợ
proxy và tự thử lại khi máy chủ giới hạn tốc độ hoặc gặp lỗi tạm thời.

## Tải bản Windows

Tải file `DF-Redeem-v1.1.0-windows-x64.zip` trong mục **Releases**, giải nén
toàn bộ rồi chạy `DF-Redeem.exe`.

Giao diện có ba ô để dán tài khoản, CDKey và proxy. Bấm **Lưu và chạy** để lưu
dữ liệu trên máy và bắt đầu đổi code. Kết quả được hiển thị ngay trong cửa sổ.

Không di chuyển riêng file `.exe` ra khỏi thư mục đã giải nén. Dữ liệu được lưu
trong thư mục `data` nằm cạnh chương trình để lần sau không phải nhập lại.

## Cài đặt

Yêu cầu Python 3.11 trở lên.

```powershell
py -m pip install -r requirements.txt
```

## Chuẩn bị dữ liệu

Các file nằm trong thư mục `data`:

### `accounts.txt`

Mỗi tài khoản một dòng:

```text
openid:token
```

#### Cách lấy `openid` và `token`

1. Mở trang redeem Delta Force và đăng nhập tài khoản.
2. Nhấn `F12`, chọn tab **Console**.
3. Dán đoạn JavaScript sau rồi nhấn Enter:

```javascript
(() => {
  const cookie = document.cookie
    .split("; ")
    .find((item) => item.startsWith("user_info="));

  if (!cookie) {
    console.error(
      "Không tìm thấy cookie user_info. Hãy đăng nhập rồi tải lại trang.",
    );
    return;
  }

  try {
    const value = cookie.slice("user_info=".length);
    const account = JSON.parse(decodeURIComponent(value));

    if (!account.openid || !account.token) {
      console.error("Cookie user_info không có openid/token.", account);
      return;
    }

    console.log(`${account.openid}:${account.token}`);
  } catch (error) {
    console.error("Không đọc được cookie user_info:", error);
  }
})();
```

Console sẽ hiển thị một dòng:

```text
openid:token
```

Tự chọn dòng đó và sao chép vào `data/accounts.txt`. Đăng xuất, đăng nhập tài
khoản khác và lặp lại nếu dùng nhiều tài khoản. Không chia sẻ `token` cho người
khác.

Các file `data/accounts.txt`, `data/codes.txt` và `data/proxies.txt` được Git
bỏ qua để tránh vô tình công khai token hoặc mật khẩu proxy.

### `codes.txt`

Mỗi CDKey một dòng:

```text
CODE_1
CODE_2
```

### `proxies.txt`

File này không bắt buộc. Mỗi proxy một dòng, hỗ trợ:

```text
ip:port
ip:port:user:password
http://user:password@ip:port
socks5://user:password@ip:port
```

Chương trình tự kiểm tra proxy và bỏ qua proxy lỗi. Nếu không có proxy hoạt
động, chương trình sẽ kết nối trực tiếp.

## Chạy bằng mã nguồn

```powershell
py main.py
```

Chương trình mặc định mở giao diện. Có thể chạy chế độ dòng lệnh bằng
`py main.py --cli`.

Mỗi tài khoản chỉ gửi một request tại một thời điểm và nghỉ ngẫu nhiên
1,5–3 giây giữa các code. Nhiều tài khoản vẫn có thể chạy song song. Nếu máy
chủ báo gửi quá nhanh, chương trình tự chờ 10 giây, sau đó tăng thời gian chờ
và thử lại.

Nếu API trả lỗi hệ thống, chương trình giữ nguyên account/proxy và chờ
15 giây, 30 giây, rồi 60 giây trước các lần thử lại.

Kết quả chỉ được in trên màn hình, không ghi ra file.
