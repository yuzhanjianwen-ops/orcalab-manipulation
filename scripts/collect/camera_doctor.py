"""camera_doctor.py —— 相机体检：一次看清 ncam / 端口 / 推流状态。

用法（OrcaStudio 开着、仿真跑起来之后）：
    & "C:\\Users\\86322\\.conda\\envs\\orcalab\\python.exe" -X utf8 -u camera_doctor.py
"""
from __future__ import annotations
import os, sys, socket, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orca_boot  # noqa

import grpc
from orca_gym.protos import mjc_message_pb2, mjc_message_pb2_grpc

ADDR = "127.0.0.1:50051"


def po(p, t=0.6):
    s = socket.socket(); s.settimeout(t)
    try:
        s.connect(("127.0.0.1", p)); return True
    except Exception:
        return False
    finally:
        s.close()


def main():
    print("=" * 66)
    print("OrcaLab 相机体检")
    print("=" * 66)

    try:
        stub = mjc_message_pb2_grpc.GrpcServiceStub(grpc.insecure_channel(ADDR))
        r = stub.QueryModelInfo(mjc_message_pb2.QueryModelInfoRequest(), timeout=15)
    except Exception as e:
        print("gRPC 连不上 %s: %s" % (ADDR, e))
        print("→ 仿真没跑？先在 OrcaStudio 里点运行。")
        return 1

    print("\n[1] MuJoCo 模型")
    for f in ("nq", "nv", "nu", "nbody", "njnt", "ngeom", "nsite", "nmesh"):
        print("    %-8s = %d" % (f, getattr(r, f)))
    ncam = getattr(r, "ncam", 0)
    print("    %-8s = %d   %s" % ("ncam", ncam, "← 相机数" ))
    print("    %-8s = %d" % ("nlight", r.nlight))

    print("\n[2] 判定")
    if ncam > 0:
        print("    ✅ ncam = %d  > 0 —— 模型里有 MuJoCo 相机了！" % ncam)
        print("       → SetCameraSensorInfo 现在应该能成功")
    else:
        print("    ❌ ncam = 0 —— 模型里没有 <camera> 传感器")
        print("       → SetCameraSensorInfo 必然报 'Camera actor name not found'")
        print("       → 试着跑: python mjcf_camera_inject.py --inject")
        print("         然后重启 OrcaStudio 打开布局")

    print("\n[3] 推流端口")
    for p in (7070, 7071, 7072, 7073, 8971, 8972):
        print("    %-6d %s" % (p, "OPEN" if po(p) else "closed"))
    print("    (注: 7070/7071 是 WebSocket，用 TCP connect 测不出属正常)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
