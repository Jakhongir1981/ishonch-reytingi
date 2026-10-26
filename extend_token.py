"""Qisqa tokenni uzoq muddatli foydalanuvchi tokeniga, undan esa muddatsiz sahifa tokeniga almashtiradi.
Natija .env ga yoziladi; tokenlar ekranga chiqarilmaydi."""
import datetime
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request

GRAPH = "https://graph.facebook.com/v26.0"
ENV = pathlib.Path(__file__).with_name(".env")


def read_env():
    env = {}
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def write_env(env):
    ENV.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")


def get(path, **params):
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


env = read_env()
long_user = get("oauth/access_token", grant_type="fb_exchange_token", client_id=env["APP_ID"],
                client_secret=env["APP_SECRET"], fb_exchange_token=env["IG_TOKEN"])
if "access_token" not in long_user:
    raise SystemExit(f"Almashtirish xatosi: {long_user.get('error', {}).get('message', long_user)}")
print("Uzoq muddatli foydalanuvchi tokeni olindi, amal qilish:",
      f"{long_user.get('expires_in', 0) // 86400} kun" if long_user.get("expires_in") else "muddatsiz")

page = get(env["FB_PAGE_ID"], fields="access_token,name", access_token=long_user["access_token"])
if "access_token" not in page:
    raise SystemExit(f"Sahifa tokeni xatosi: {page.get('error', {}).get('message', page)}")

app_token = f"{env['APP_ID']}|{env['APP_SECRET']}"
info = get("debug_token", input_token=page["access_token"], access_token=app_token).get("data", {})
exp = info.get("expires_at", 0)
print(f"Sahifa tokeni ({page['name']}):", "muddatsiz" if not exp else datetime.datetime.fromtimestamp(exp))

env["USER_TOKEN_LONG"] = long_user["access_token"]
env["IG_TOKEN"] = page["access_token"]
write_env(env)
print(".env yangilandi:", ", ".join(env))
