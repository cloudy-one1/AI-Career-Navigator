import os, sys

files = [
    r"F:/Downloads/学号_姓名_Project Start Report_V1.0.doc",
    r"C:/Users/33197/OneDrive/文档/1组余权20243968-项目立项报告.docx",
]

for f in files:
    print("=" * 60)
    print("FILE:", f)
    print("EXISTS:", os.path.exists(f))
    if not os.path.exists(f):
        continue
    size = os.path.getsize(f)
    print("SIZE:", size)
    with open(f, "rb") as fh:
        head = fh.read(16)
    print("HEX:", head.hex())
    try:
        print("ASCII:", head.decode("ascii", errors="replace"))
    except Exception as e:
        print("decode err", e)
