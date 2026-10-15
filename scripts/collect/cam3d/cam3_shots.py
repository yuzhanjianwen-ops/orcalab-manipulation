# -*- coding: utf-8 -*-
"""三相机取图（已打通，实测可用）

原理：
  1. 通过 50151 编辑服务 GetCameras 列出场景里所有相机
  2. 用 SetActiveCamera(index) 切换到目标相机
  3. 用 MCP get_viewport_camera_info(index) 让 Studio 渲染一帧并落盘
  4. 把落盘 PNG 拷贝到 out_final/

默认抓 G1 的三个相机：/head_camera_1, /wrist_camera_l, /wrist_camera_r
用法:
  python cam3_shots.py            # 抓三个默认相机
  python cam3_shots.py --list     # 只列相机
"""
import sys, os, json, time, shutil, argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import orca_boot  # noqa: F401
import grpc
import orcalab.protos.edit_service_pb2 as ep
import orcalab.protos.edit_service_pb2_grpc as epg
from orca_mcp import OrcaMcp, call_text

EDIT_ADDR = '127.0.0.1:50151'
VIEWPORT_DIR = r'C:\Users\86322\.orcalab\viewport_image'
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out_final')

DEFAULT_CAMS = [
    ('/head_camera_1', 'head'),
    ('/wrist_camera_l', 'wrist_l'),
    ('/wrist_camera_r', 'wrist_r'),
]


def list_cameras(stub):
    r = stub.GetCameras(ep.GetCamerasRequest(), timeout=15)
    return [(c.index, c.name, c.actor_path, c.source) for c in r.cameras]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true', help='只列出相机')
    ap.add_argument('--all', action='store_true', help='抓所有 actor 相机')
    args = ap.parse_args()

    stub = epg.GrpcServiceStub(grpc.insecure_channel(EDIT_ADDR))
    cams = list_cameras(stub)
    print('场景相机 (%d):' % len(cams))
    for idx, name, ap_, src in cams:
        print('   [%d] %-14s actor=%s (%s)' % (idx, name, ap_, src))
    if args.list:
        return

    m = OrcaMcp(timeout=900)
    m.connect()
    os.makedirs(OUT_DIR, exist_ok=True)

    if args.all:
        targets = [(i, nm, ap_) for i, nm, ap_, src in cams if src == 'actor']
    else:
        targets = []
        for want, tag in DEFAULT_CAMS:
            for i, nm, ap_, src in cams:
                if ap_ == want:
                    targets.append((i, tag, ap_))
                    break

    print('\n抓取 %d 路相机:' % len(targets))
    for idx, tag, ap_ in targets:
        stub.SetActiveCamera(ep.SetActiveCameraRequest(index=idx), timeout=15)
        time.sleep(1.5)
        r = call_text(m, 'get_viewport_camera_info', {'index': idx})
        d = json.loads(r)
        cp = d.get('color_path', '')
        if cp and os.path.exists(cp):
            dst = os.path.join(OUT_DIR, 'cam_%s_idx%d.png' % (tag, idx))
            shutil.copy2(cp, dst)
            print('   [%d] %-10s -> %s (%d bytes)' % (idx, tag, dst, os.path.getsize(dst)))
        else:
            print('   [%d] %-10s -> 无图 (color_path=%s)' % (idx, tag, cp))


if __name__ == '__main__':
    main()
