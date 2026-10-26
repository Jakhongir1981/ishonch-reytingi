"""Token ishlayotganini tekshiradi. Tokenning o'zini hech qachon chiqarmaydi."""
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request

GRAPH = "https://graph.facebook.com/v26.0"
ENV = pathlib.Path(__file__).with_name(".env")


def load_token():
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        if line.strip().startswith("IG_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def get(path, token, **params):
    params["access_token"] = token
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


token = load_token()
if not token:
    raise SystemExit(".env faylida IG_TOKEN bo'sh")
print(f"Token uzunligi: {len(token)} belgi, boshlanishi: {token[:4]}...")

me = get("me", token, fields="id,name")
print("Foydalanuvchi:", me.get("name") or me)

perms = get("me/permissions", token)
if "data" in perms:
    print("Ruxsatlar:", ", ".join(p["permission"] for p in perms["data"] if p["status"] == "granted"))

pages = get("me/accounts", token, fields="name,instagram_business_account{id,username,followers_count}")
if "error" in pages:
    print("Sahifalar xatosi:", pages["error"].get("message"))
else:
    print(f"Facebook sahifalari: {len(pages.get('data', []))} ta")
    for p in pages.get("data", []):
        ig = p.get("instagram_business_account")
        print(" -", p["name"], "->", f"@{ig['username']} (IG ID {ig['id']}, {ig.get('followers_count')} obunachi)" if ig else "Instagram ulanmagan")
