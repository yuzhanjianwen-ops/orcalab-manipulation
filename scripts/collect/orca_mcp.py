"""OrcaLab MCP 客户端 —— 直连 OrcaStudio 的 MCP 服务(127.0.0.1:12345)。

用途：在不开 GUI 的情况下查询/编辑场景（列 Actor、加相机、设位姿、截图）。
注意：这是"辅助工具"，与 teleop/collect 主流程独立，不修改任何既有文件。
"""
import json
import re
import socket

HOST = "127.0.0.1"
PORT = 12345
PATH = "/mcp"
PROTO = "2024-11-05"


class OrcaMcp:
    def __init__(self, host=HOST, port=PORT, timeout=30.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sid = None
        self._rid = 0

    # ---------- 传输层 ----------
    def _post(self, payload, timeout=None):
        body = json.dumps(payload).encode("utf-8")
        head = (
            "POST %s HTTP/1.1\r\nHost: %s\r\n"
            "Accept: application/json, text/event-stream\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: %d\r\n" % (PATH, self.host, len(body))
        )
        if self.sid:
            head += "mcp-session-id: %s\r\n" % self.sid
        head += "Connection: close\r\n\r\n"
        s = socket.socket()
        s.settimeout(timeout or self.timeout)
        try:
            s.connect((self.host, self.port))
            s.sendall(head.encode("utf-8") + body)
            chunks = []
            while True:
                try:
                    c = s.recv(65536)
                except socket.timeout:
                    break
                if not c:
                    break
                chunks.append(c)
                # 上限要足够大：get_view_png_from_transform 会回传 base64 图像，
                # 1080x1080 的复杂场景 PNG 可达 3MB+，base64 后 4MB+。
                # 之前卡在 4MB 会把图截断，表现为“渲染失败”。
                if sum(len(x) for x in chunks) > 48_000_000:
                    break
        finally:
            s.close()
        raw = b"".join(chunks).decode("utf-8", "replace")
        for line in raw.splitlines():
            if line.lower().startswith("mcp-session-id:"):
                self.sid = line.split(":", 1)[1].strip()
        return raw

    @staticmethod
    def _unwrap(raw):
        """把 SSE/text 响应解成 JSON 对象。"""
        # SSE: 每行 data: {...}
        for m in re.finditer(r"^data: (.*)$", raw, re.M):
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        # 纯 JSON body
        body = raw.split("\r\n\r\n", 1)
        if len(body) == 2:
            try:
                return json.loads(body[1])
            except Exception:
                pass
        return {"raw": raw}

    def rpc(self, method, params=None, notify=False, timeout=None):
        self._rid += 1
        payload = {
            "jsonrpc": "2.0",
            "id": None if notify else self._rid,
            "method": method,
            "params": params or {},
        }
        return self._unwrap(self._post(payload, timeout))

    # ---------- 会话 ----------
    def connect(self):
        r = self.rpc("initialize", {
            "protocolVersion": PROTO,
            "capabilities": {},
            "clientInfo": {"name": "orca-mcp-cli", "version": "1.0"},
        })
        info = r.get("result", {}).get("serverInfo", {})
        self.rpc("notifications/initialized", {}, notify=True)
        return info

    def tools(self):
        r = self.rpc("tools/list")
        return r.get("result", {}).get("tools", [])

    def call(self, name, args=None, timeout=None):
        return self.rpc("tools/call", {"name": name, "arguments": args or {}}, timeout=timeout)


def _text(result):
    """把 tools/call 结果里的文本内容抽出来。"""
    out = []
    for c in (result.get("result", {}) or {}).get("content", []) or []:
        if c.get("type") == "text":
            out.append(c.get("text", ""))
    return "\n".join(out)


def call_text(mcp, name, args=None, timeout=None):
    r = mcp.call(name, args, timeout=timeout)
    if "error" in r:
        return "ERROR: " + json.dumps(r["error"], ensure_ascii=False)
    return _text(r)


if __name__ == "__main__":
    import sys

    m = OrcaMcp()
    print("serverInfo:", m.connect())
    ts = m.tools()
    print("tools:", len(ts))
    if len(sys.argv) > 1:
        name = sys.argv[1]
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(call_text(m, name, args))
