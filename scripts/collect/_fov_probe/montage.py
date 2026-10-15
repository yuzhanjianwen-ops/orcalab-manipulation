import os, io, sys
from PIL import Image, ImageDraw
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
D = r"D:\OTHERS\projects\orcalab-manipulation\scripts\collect\_fov_probe"
cams = ["head", "left", "right"]
rows = [("fov90", "vertical_fov = 90 (original)"), ("fov60", "vertical_fov = 60 (narrower)")]
imgs = {}
for pre, _ in rows:
    for c in cams:
        p = os.path.join(D, "%s_%s.png" % (pre, c))
        imgs[(pre, c)] = Image.open(p).convert("RGB")
gap, lab, head = 8, 20, 24
w = sum(imgs[(rows[0][0], c)].width for c in cams) + gap * (len(cams) + 1)
h = head + len(rows) * (imgs[(rows[0][0], cams[0])].height + lab) + gap
M = Image.new("RGB", (w, h), (18, 18, 18))
d = ImageDraw.Draw(M)
d.text((gap, 6), "ORCA robot cameras: vertical_fov 90 vs 60", fill=(255, 220, 0))
y = head
for pre, title in rows:
    d.text((gap, y + 3), title, fill=(255, 255, 0))
    y += lab
    x = gap
    for c in cams:
        im = imgs[(pre, c)]
        M.paste(im, (x, y))
        d.text((x + 4, y + 4), c, fill=(0, 255, 128))
        x += im.width + gap
    y += imgs[(pre, cams[0])].height + gap
out = os.path.join(D, "fov_compare.png")
M.save(out)
print("saved", out, M.size)