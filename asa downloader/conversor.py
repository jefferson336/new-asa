#!/usr/bin/env python3
import os
import struct
import zlib

INPUT_DIR  = "out"     # where your .lib files live
OUTPUT_DIR = "final"   # where you want the .swf’s

os.makedirs(OUTPUT_DIR, exist_ok=True)

for fname in os.listdir(INPUT_DIR):
    if not fname.lower().endswith(".lib"):
        continue

    in_path  = os.path.join(INPUT_DIR, fname)
    base     = os.path.splitext(fname)[0]
    out_path = os.path.join(OUTPUT_DIR, base + ".swf")

    data = open(in_path, "rb").read()
    if not data.startswith(b"CWS") and not data.startswith(b"ZWS"):
        print(f":warning:  {fname} is not a compressed SWF, skipping")
        continue

    sig     = data[:3]       # b"CWS" or b"ZWS"
    ver     = data[3:4]      # version byte
    length  = struct.unpack("<I", data[4:8])[0]
    body    = data[8:]

    if sig == b"CWS":
        # zlib‐compressed body
        decompressed = zlib.decompress(body)
    else:
        # ZWS (LZMA) case — if you hit one of these, add the LZMA logic
        raise NotImplementedError("ZWS decompression not shown here")

    # build an uncompressed SWF (FWS) header
    new_length = len(decompressed) + 8
    fws_header = b"FWS" + ver + struct.pack("<I", new_length)

    with open(out_path, "wb") as f:
        f.write(fws_header)
        f.write(decompressed)

    print(f"✓ {fname} → {base}.swf")