"""
课堂喊人传话系统 v3.0 - 云端多教室版
支持多个老师同时使用，互不干扰
部署：Render.com / 任意云服务器
"""

import os
import socket
import sys
import io
import random
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

# 修复 Windows GBK 控制台编码问题
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# 端口：云部署用环境变量 PORT，本地默认 9000
DEFAULT_PORT = int(os.environ.get("PORT", "9000"))
BASE_DIR = Path(__file__).parent / "static"

app = FastAPI(title="课堂喊人传话系统 v3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Room:
    """一个教室房间：1个老师 + N个显示屏"""
    def __init__(self, code):
        self.code = code
        self.teacher_ws = None
        self.displays = {}       # display_id → ws
        self.display_names = {}  # display_id → 名称
        self.created_at = datetime.now()
        self.last_active = datetime.now()

    def is_empty(self):
        return self.teacher_ws is None and len(self.displays) == 0


class RoomManager:
    """管理所有教室房间"""
    def __init__(self):
        self.rooms = {}  # room_code → Room

    def create_room(self, code=None):
        """创建新教室，4位数字代码"""
        if not code:
            for _ in range(100):
                code = str(random.randint(1000, 9999))
                if code not in self.rooms:
                    break
        if code not in self.rooms:
            self.rooms[code] = Room(code)
        self.rooms[code].last_active = datetime.now()
        return self.rooms[code]

    def get_room(self, code):
        return self.rooms.get(code)

    def cleanup_empty(self):
        """清理空房间"""
        empty = [code for code, room in self.rooms.items() if room.is_empty()]
        for code in empty:
            del self.rooms[code]

    @staticmethod
    def now_str():
        return datetime.now().strftime("%H:%M:%S")


mgr = RoomManager()


# ---- 页面路由 ----

@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/teacher")
async def teacher_page():
    return FileResponse(BASE_DIR / "teacher.html")


@app.get("/display")
async def display_page():
    return FileResponse(BASE_DIR / "display.html")


# ---- API ----

@app.get("/api/rooms/{code}/status")
async def room_status(code: str):
    """检查教室是否存在"""
    room = mgr.get_room(code)
    if room:
        return {"exists": True, "has_teacher": room.teacher_ws is not None, "display_count": len(room.displays)}
    return {"exists": False}


@app.get("/api/qrcode")
async def qrcode_api(url: str = "", color: str = "4F46E5"):
    """生成二维码"""
    if not url:
        return Response(content="missing url", status_code=400)
    try:
        import qrcode
        import qrcode.image.svg
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#" + color, back_color="white", image_factory=qrcode.image.svg.SvgImage)
        buf = io.BytesIO()
        img.save(buf)
        return Response(content=buf.getvalue(), media_type="image/svg+xml")
    except ImportError:
        return Response(content="qrcode lib not installed", status_code=500)


# ---- WebSocket 路由 ----

@app.websocket("/ws/teacher/{room_code}")
async def ws_teacher(websocket: WebSocket, room_code: str):
    """老师连接"""
    room = mgr.create_room(room_code)
    await websocket.accept()
    room.teacher_ws = websocket
    room.last_active = datetime.now()

    # 发送初始化信息
    displays_list = [{"id": did, "name": room.display_names.get(did, did)} for did in room.displays]
    await websocket.send_json({
        "type": "init",
        "room_code": room_code,
        "displays": displays_list,
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            room.last_active = datetime.now()

            if msg_type == "call":
                name = data.get("name", "")
                message = data.get("message", "") or f"{name}，老师叫你！"
                target = data.get("target_display", "")
                msg = {"type": "called", "name": name, "message": message, "time": mgr.now_str()}
                sent = await _send_to_displays(room, msg, target)
                await websocket.send_json({"type": "call_result", "success": sent, "name": name})

            elif msg_type == "message":
                content = data.get("content", "")
                target = data.get("target_display", "")
                msg = {"type": "message", "content": content, "time": mgr.now_str()}
                sent = await _send_to_displays(room, msg, target)
                await websocket.send_json({"type": "message_result", "success": sent})

            elif msg_type == "dismiss":
                target = data.get("target_display", "")
                msg = {"type": "dismiss", "time": mgr.now_str()}
                await _send_to_displays(room, msg, target, silent=True)
                await websocket.send_json({"type": "dismiss_result", "success": True})

    except Exception:
        pass
    finally:
        room.teacher_ws = None
        mgr.cleanup_empty()


@app.websocket("/ws/display/{room_code}/{display_id}")
async def ws_display(websocket: WebSocket, room_code: str, display_id: str):
    """显示屏连接"""
    room = mgr.create_room(room_code)
    await websocket.accept()
    display_name = websocket.query_params.get("name", display_id)
    room.displays[display_id] = websocket
    room.display_names[display_id] = display_name
    room.last_active = datetime.now()

    # 通知老师
    if room.teacher_ws:
        try:
            await room.teacher_ws.send_json({
                "type": "display_joined",
                "display_id": display_id,
                "display_name": display_name,
            })
        except Exception:
            pass

    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        room.displays.pop(display_id, None)
        room.display_names.pop(display_id, None)
        if room.teacher_ws:
            try:
                await room.teacher_ws.send_json({"type": "display_left", "display_id": display_id})
            except Exception:
                pass
        mgr.cleanup_empty()


async def _send_to_displays(room, msg, target_display="", silent=False):
    """向显示屏发送消息"""
    sent = False
    if target_display and target_display in room.displays:
        try:
            await room.displays[target_display].send_json(msg)
            sent = True
        except Exception:
            room.displays.pop(target_display, None)
            room.display_names.pop(target_display, None)
    else:
        dead = []
        for did, ws in room.displays.items():
            try:
                await ws.send_json(msg)
                sent = True
            except Exception:
                dead.append(did)
        for did in dead:
            room.displays.pop(did, None)
            room.display_names.pop(did, None)
    return sent


# ---- 启动 ----

if __name__ == "__main__":
    import uvicorn

    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"无效端口号，使用默认 {DEFAULT_PORT}")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"

    print()
    print("=" * 55)
    print("   课堂喊人传话系统 v3.0 (多教室版)")
    print("=" * 55)
    print(f"   老师控制台: http://{ip}:{port}/teacher")
    print(f"   教室显示屏: http://{ip}:{port}/display")
    print(f"   端口: {port}")
    print("=" * 55)
    print()
    print("提示: 多个老师可同时使用，通过「教室号」区分")
    print("提示: 教室号是4位数字，如 1234")
    print()

    uvicorn.run(app, host="0.0.0.0", port=port)
