"""Challenge Reels'ini @ins24uz nomidan rasmiy Instagram API orqali joylaydi.

  python publish_reel.py --check     # sinov: video yuklanadi va tekshiriladi, lekin JOYLANMAYDI
  python publish_reel.py --publish   # haqiqiy joylash + birinchi izoh + jonli hisobni yoqish

Qadamlar: konteyner (REELS, tavsif, soavtor, muqova) → videoni yuklash → Instagram qayta
ishlashini kutish → joylash → birinchi izoh → rejim.txt ga "--media <ID> --days 30" yozib push.
Hammasi faqat rasmiy API: avtomatik layk/obuna/izohlar yo'q, limit check_usage bilan kuzatiladi.
"""
import argparse
import json
import pathlib
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from vote_counter import GRAPH, api, read_env

ROOT = pathlib.Path(__file__).parent
REELS = ROOT / "reels"
VIDEO = REELS / "ishonch_reytingi.mp4"
COLLABORATOR = "jakhongir_bakiev"
COVER_MS = 2000  # muqova: 2-soniyadagi "Challenge" kadri


def post(url, token, data=None, headers=None, body=None):
    if data is not None:
        data["access_token"] = token
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Instagram API xatosi: {e.read().decode(errors='replace')[:500]}")


def create_and_upload(env):
    token, ig = env["IG_TOKEN"], env["IG_USER_ID"]
    caption = (REELS / "caption.txt").read_text(encoding="utf-8").strip()
    c = post(f"{GRAPH}/{ig}/media", token, {
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
        "collaborators": json.dumps([COLLABORATOR]), "share_to_feed": "true", "thumb_offset": str(COVER_MS),
    })
    cid = c["id"]
    print("Konteyner:", cid)
    size = VIDEO.stat().st_size
    up = post(c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v26.0/{cid}", token,
              headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
              body=VIDEO.read_bytes())
    print("Video yuklandi:", up.get("success", up), f"({size // 1024} KB)")
    for _ in range(60):
        st = api(cid, token, fields="status_code,status")
        print("  Instagram holati:", st.get("status_code"))
        if st.get("status_code") == "FINISHED":
            return cid
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise SystemExit(f"Instagram videoni qabul qilmadi: {st.get('status')}")
        time.sleep(10)
    raise SystemExit("Instagram 10 daqiqada videoni qayta ishlab bo'lmadi")


def publish(env, cid):
    token, ig = env["IG_TOKEN"], env["IG_USER_ID"]
    media_id = post(f"{GRAPH}/{ig}/media_publish", token, {"creation_id": cid})["id"]
    info = api(media_id, token, fields="permalink,timestamp")
    print("JOYLANDI:", info["permalink"])
    comment = (REELS / "comment.txt").read_text(encoding="utf-8").strip()
    cm = post(f"{GRAPH}/{media_id}/comments", token, {"message": comment})
    print("Birinchi izoh qoldirildi:", cm.get("id"))
    (ROOT / "rejim.txt").write_text(f"--media {media_id} --days 30\n", encoding="utf-8")
    for cmd in (["git", "add", "rejim.txt"],
                ["git", "-c", "user.name=Jakhongir Bakiev", "-c", "user.email=appleidjbk@gmail.com", "commit", "-qm",
                 f"Start: jonli hisob Reels {media_id} bo'yicha, 30 kun\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"],
                ["git", "push", "-q"]):
        subprocess.run(cmd, cwd=ROOT, check=True)
    print("Jonli hisob yoqildi: sayt ~2 daqiqada yangilanadi")
    return media_id


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="yuklab tekshirish, joylamasdan")
    g.add_argument("--publish", action="store_true", help="haqiqiy joylash")
    a = p.parse_args()
    env = read_env()
    limit = api(f"{env['IG_USER_ID']}/content_publishing_limit", env["IG_TOKEN"], fields="quota_usage,config")["data"][0]
    print(f"Kunlik limit: {limit['quota_usage']}/{limit['config']['quota_total']}")
    cid = create_and_upload(env)
    if a.check:
        print("SINOV TUGADI: video va tavsif qabul qilindi, hech narsa joylanmadi (konteyner 24 soatda o'zi o'chadi).")
    else:
        publish(env, cid)


if __name__ == "__main__":
    main()
