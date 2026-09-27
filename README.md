# Tool Redeem Gift Code Delta Force

Công cụ redeem Gift Code Delta Force cho nhiều tài khoản cùng lúc. Có giao
diện đơn giản, hỗ trợ proxy và hiển thị kết quả trực tiếp trong ứng dụng.

## Tải về

Tải phiên bản mới nhất tại:

**[Tải Tool Redeem Gift Code Delta Force cho Windows](https://github.com/phuccan0800/delta-force-redeem/releases/latest)**

Sau khi tải xong:

1. Giải nén toàn bộ file ZIP.
2. Mở `DF-Redeem.exe`.
3. Dán tài khoản, Gift Code và proxy vào các ô tương ứng.
4. Bấm **Lưu và chạy**.

Không cần cài Python. Không di chuyển riêng file `.exe` ra khỏi thư mục đã giải
nén.

## Định dạng dữ liệu

### Tài khoản

Mỗi tài khoản một dòng, theo định dạng:

```text
openid:token
```

Ví dụ:

```text
123456789:your_token
987654321:your_token
```

### Gift Code

Mỗi Gift Code một dòng:

```text
CODE_1
CODE_2
CODE_3
```

### Proxy

Proxy không bắt buộc. Nếu sử dụng, nhập mỗi proxy một dòng:

```text
ip:port
ip:port:user:password
http://user:password@ip:port
socks5://user:password@ip:port
```

Nếu không nhập proxy, ứng dụng sẽ sử dụng kết nối mạng hiện tại.

## Cách lấy `openid` và `token`

1. Mở trang redeem Delta Force và đăng nhập.
2. Nhấn `F12`, chọn tab **Console**.
3. Dán đoạn mã dưới đây rồi nhấn Enter:

```javascript
(() => {
  const cookie = document.cookie
    .split("; ")
    .find((item) => item.startsWith("user_info="));

  if (!cookie) {
    console.error("Không tìm thấy thông tin tài khoản. Hãy đăng nhập lại.");
    return;
  }

  const account = JSON.parse(
    decodeURIComponent(cookie.slice("user_info=".length)),
  );
  console.log(`${account.openid}:${account.token}`);
})();
```

Sao chép dòng `openid:token` hiển thị trong Console và dán vào ô **Tài khoản**
trong ứng dụng.

## Lưu ý bảo mật

- Không chia sẻ `token` tài khoản hoặc mật khẩu proxy.
- Dữ liệu được lưu cục bộ trong thư mục `data` cạnh ứng dụng.
- Các file chứa tài khoản, Gift Code và proxy không được đưa lên GitHub.

## Dành cho lập trình viên

Yêu cầu Python 3.11 trở lên:

```powershell
py -m pip install -r requirements.txt
py main.py
```

Chạy chế độ dòng lệnh:

```powershell
py main.py --cli
```
