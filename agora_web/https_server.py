import http.server
import ssl
import os
import sys

# 配置
PORT = 3001
# 证书路径 (位于上级目录的 webRTC 文件夹中)
CERT_FILE = os.path.join(os.path.dirname(__file__), "../webRTC", "cert.pem")
KEY_FILE = os.path.join(os.path.dirname(__file__), "../webRTC", "key.pem")
# 要服务的目录 (当前目录)
DIRECTORY = os.path.dirname(__file__)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)


def run_server():
    # 检查证书是否存在
    if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
        print(f"错误: 找不到证书文件。请确保 {CERT_FILE} 和 {KEY_FILE} 存在。")
        print("你可以使用以下命令在项目根目录生成自签名证书:")
        print(
            "openssl req -x509 -newkey rsa:4096 -keyout webRTC/key.pem -out webRTC/cert.pem -days 365 -nodes"
        )
        return

    server_address = ("0.0.0.0", PORT)
    httpd = http.server.HTTPServer(server_address, Handler)

    # 包装 SSL
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT_FILE, KEY_FILE)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    print(f"Serving HTTPS on port {PORT}...")
    print(f"Document Root: {DIRECTORY}")
    print(f"Access at: https://localhost:{PORT}/ar_index.html")
    print(f"Access at: https://<Your-IP>:{PORT}/ar_index.html")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
