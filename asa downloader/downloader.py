import os, json, zlib, requests
from Cryptodome.Cipher import DES

DES_KEY  = bytes.fromhex("6bc89fe7d5a0f35f")
BASE_URL = "https://res-mspt.gamesow.com"
LOGIN_URL = (
    "https://res-mspt.gamesow.com/bin/WebLaucher.html"
    "?userid=XXXXXX&username=XXXXXX&cm=X"
    "&server_id=XXX&time=XXXXXXXXXXXX"
    "&flag=XXXXXXXXXXXXXXXXXXXXXXXXXXXX"
)
des = DES.new(DES_KEY, DES.MODE_ECB)

def decrypt_blob(raw: bytes) -> bytes:
    first, rest = raw[:8], raw[8:]
    patched     = des.decrypt(first) + rest
    # first try zlib, then raw deflate, else just patched
    for w in (15, -15):
        try:
            return zlib.decompress(patched, wbits=w)
        except zlib.error:
            pass
    return patched

def swf_decompress(raw: bytes) -> bytes:
    sig, hdr8, body = raw[:3], raw[3:8], raw[8:]
    if sig == b"CWS":
        return b"FWS" + hdr8 + zlib.decompress(body)
    # add ZWS/LZMA if you need it...
    return raw

def load_all():
    # 1) login
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "ShockwaveFlash/27.0.0.187",
        "Referer":  LOGIN_URL
    })
    r = sess.get(LOGIN_URL)
    r.raise_for_status()
    print(":white_check_mark: logged in, cookies:", sess.cookies.get_dict())

    # 2) read manifest
    manifest = json.load(open("data2.json", encoding="utf-8"))
    os.makedirs("out", exist_ok=True)

    for res in manifest["resources"]:
        print("→", res["id"], res["url"])
        blob = sess.get(BASE_URL + manifest["baseURL"] + res["url"]).content
        data = decrypt_blob(blob)
        ext  = "." + res["type"]
        if res["type"] == "swf":
            data = swf_decompress(data)
        with open(os.path.join("out", res["id"] + ext), "wb") as f:
            f.write(data)

if __name__ == "__main__":
    load_all()