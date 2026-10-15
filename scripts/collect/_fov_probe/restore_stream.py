import os, sys, io
sys.path.insert(0, r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import grpc
from orca_gym.protos import mjc_message_pb2 as pb, mjc_message_pb2_grpc as pbg
stub = pbg.GrpcServiceStub(grpc.insecure_channel("127.0.0.1:50051"))
for n in ["camera_head", "camera_left", "camera_right"]:
    r = stub.SetStreamingEnabled(pb.SetStreamingEnabledRequest(camera_name=n, enabled=True), timeout=10)
    p = stub.GetCameraProperties(pb.GetCameraPropertiesRequest(camera_name=n), timeout=10)
    print("%-13s set_streaming=%s(%s) -> streaming=%s rgb=%s fov=%s" % (n, r.status, r.error_message, p.streaming_enabled, p.capture_rgb, p.vertical_fov))