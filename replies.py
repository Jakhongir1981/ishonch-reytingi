"""Hisoblangan ovozlarga @ins24uz nomidan minnatdorchilik javobi (havolasiz).

Instagram spam deb bilmasligi uchun himoyalar:
  * faqat "hisoblandi" ovozlarga, har bir akkauntga BIR marta;
  * javoblar orasida tasodifiy 2–5 daqiqa, soatiga 10→15→20 (sekin boshlash), kuniga 150, tunda (00–08) yozilmaydi;
  * Instagram bitta javobni rad etsa — 6 soat pauza;
  * 10 xil matn, nik va kompaniya nomi bilan — bir xil matn ketma-ket takrorlanmaydi;
  * havola yo'q — "@jakhongir_bakiev profilidagi havola" deb yoziladi;
  * javob berishdan oldin izohda ins24uz yoki @jakhongir_bakiev javobi bor-yo'qligi tekshiriladi;
  * Meta limiti 70% dan oshsa (check_usage) — to'xtaydi.

  python replies.py --dry               # kimga nima yozilishini ko'rsatadi, yubormaydi
  python replies.py --max 1             # bitta haqiqiy javob
  python replies.py --budget 530        # GitHub'da: 530 soniya ichida, GAP oralig'i bilan javob beradi

Holat javoblar.json faylida (kimga javob berilgan) — GitHub'da har javobdan keyin commit qilinadi.
"""
import argparse
import datetime as dt
import hashlib
import json
import random
import pathlib
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from report import send as telegram
from vote_counter import GRAPH, ORGANIZERS, api, check_usage, load_companies, read_env

ROOT = pathlib.Path(__file__).parent
STATE = ROOT / "javoblar.json"
ME = "ins24uz"
PER_DAY = 150
RAMP = [("2026-10-28", 10), ("2026-10-30", 15), ("9999-12-31", 20)]  # sekin boshlash: soatiga 10 → 15 → 20
PAUSE_HOURS = 6                  # Instagram javobni rad etsa yoki yashirsa — 6 soat jim turamiz
WARN_USAGE, STOP_USAGE = 25, 50  # 25% — ogohlantirish va sekinlashish, 50% — to'liq to'xtash (vote_counter)
ALERT_EVERY = dt.timedelta(hours=3)
QUIET = range(0, 8)              # Toshkent 00:00–08:00 — javob yozilmaydi
TK = dt.timezone(dt.timedelta(hours=5))

TEMPLATES = [
    "Rahmat, @{u}! 🙏 Ovozingiz {c} uchun qabul qilindi ✅ Jonli natijalar — @jakhongir_bakiev profilidagi havolada 🏆",
    "@{u}, ishonchingiz uchun rahmat! {c} kompaniyasiga ovozingiz hisobga olindi ✅ Reytingni profildagi havoladan kuzatib boring 📊",
    "Ovozingiz qabul qilindi, @{u} ✅ {c} — siz tanlagan kompaniya. Natijalar @jakhongir_bakiev profilidagi havolada 🏆",
    "Katta rahmat, @{u}! {c} uchun berilgan ovoz reytingga qo'shildi 🙌 Jonli reyting — profildagi havolada",
    "@{u}, ovozingiz {c} hisobiga yozildi ✅ Kim oldinda ekanini @jakhongir_bakiev profilidagi havoladan ko'ring 👀",
    "Ishtirokingiz uchun rahmat, @{u}! 🤝 {c} — ovozingiz qabul qilindi. Barcha ovozlar ochiq lavhada, havola profilda",
    "@{u}, rahmat! 💛 {c} kompaniyasiga bergan ovozingiz reytingda. Natijani @jakhongir_bakiev profilidagi havoladan bilib oling",
    "Ovoz qabul qilindi ✅ Rahmat, @{u}! {c} uchun. To'liq reyting profildagi havolada",
    "@{u}, fikringiz biz uchun muhim 🙏 {c} — ovozingiz hisoblandi. Jonli natijalar: @jakhongir_bakiev profilidagi havola",
    "Rahmat, @{u}! ✨ Siz {c} kompaniyasini tanladingiz — ovoz hisobga olindi. Reyting har 10 daqiqada yangilanadi, havola profilda",
]


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"users": [], "comments": [], "last_template": -1}


def save_state(st, push):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    if not push:
        return
    git = ["git", "-c", "user.name=ishonch-bot", "-c", "user.email=bot@users.noreply.github.com"]
    subprocess.run(["git", "add", STATE.name], cwd=ROOT, check=True)
    subprocess.run(git + ["commit", "-qm", "javoblar: holat"], cwd=ROOT, check=False)
    for _ in range(3):
        if subprocess.run(["git", "push", "-q"], cwd=ROOT).returncode == 0:
            return
        subprocess.run(["git", "pull", "-q", "--rebase", "-X", "theirs"], cwd=ROOT)


def pick_template(username, st):
    i = int(hashlib.md5(username.encode()).hexdigest(), 16) % len(TEMPLATES)
    if i == st.get("last_template"):
        i = (i + 1) % len(TEMPLATES)
    st["last_template"] = i
    return TEMPLATES[i]


def already_replied(comment_id, token):
    """@ins24uz bu izohga avval javob bergan bo'lsa — qayta yozmaymiz (tashkilotchining qo'lda javobi to'sqinlik qilmaydi)."""
    r = api(f"{comment_id}/replies", token, fields="username", limit=50)
    return any(x.get("username", "").lower() == ME for x in r.get("data", []))


def limits_ok(st):
    """Soatlik/kunlik chegaralar va tungi soatlar."""
    now = dt.datetime.now(TK)
    if now.hour in QUIET:
        return False, "tungi vaqt"
    if st.get("paused_until") and now < dt.datetime.fromisoformat(st["paused_until"]):
        return False, f"Instagram rad etgani uchun pauza {st['paused_until'][11:16]} gacha"
    per_hour = next(n for day, n in RAMP if now.date().isoformat() < day)
    if st.get("slow_until") and now < dt.datetime.fromisoformat(st["slow_until"]):
        per_hour //= 2
    sent = [dt.datetime.fromisoformat(t) for t in st.get("sent_at", [])]
    if sum(now - t < dt.timedelta(hours=1) for t in sent) >= per_hour:
        return False, "soatlik chegara"
    if sum(now - t < dt.timedelta(days=1) for t in sent) >= PER_DAY:
        return False, "kunlik chegara"
    return True, ""


class Rejected(Exception):
    pass


def alert(st, key, text):
    """Telegram'ga darhol ogohlantirish; bir xil xabar 3 soatda bir martadan ko'p emas."""
    now = dt.datetime.now(TK)
    last = st.setdefault("alerts", {}).get(key)
    if last and now - dt.datetime.fromisoformat(last) < ALERT_EVERY:
        return
    st["alerts"][key] = now.isoformat(timespec="seconds")
    print("OGOHLANTIRISH:", text)
    try:
        telegram("⚠️ <b>Ishonch reytingi</b>\n" + text)
    except Exception as e:  # Telegram ishlamasa ham asosiy ish to'xtamasin
        print("Telegram xatosi:", e)


def health(st, token):
    """Xavf belgilarini oldindan aniqlaydi: yuklama, sayt eskirgani, javoblarimiz yashirilgani."""
    now = dt.datetime.now(TK)
    data = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    peak = data.get("api_usage", {}).get("peak", 0)
    if peak >= STOP_USAGE:
        alert(st, "stop", f"⛔ Instagram yuklamasi {peak}% — hisob va javoblar to'xtatildi, yuklama tushishini kutamiz.")
    elif peak >= WARN_USAGE:
        st["slow_until"] = (now + dt.timedelta(hours=3)).isoformat(timespec="seconds")
        alert(st, "warn", f"Instagram yuklamasi {peak}% (chegara 50%). Javoblar tezligi 3 soatga ikki baravar kamaytirildi.")
    age = now - dt.datetime.fromisoformat(data["updated_at"])
    if age > dt.timedelta(minutes=30):
        alert(st, "stale", f"Sayt {int(age.total_seconds() // 60)} daqiqadan beri yangilanmagan — hisob ishlamayapti.")
    for rid in st.get("reply_ids", [])[-3:]:  # oxirgi javoblarimiz joyidami?
        try:
            r = api(rid, token, fields="hidden,text")
            bad = r.get("hidden") is True
        except SystemExit:
            bad = True
        if bad:
            st["paused_until"] = (now + dt.timedelta(hours=PAUSE_HOURS)).isoformat(timespec="seconds")
            alert(st, "hidden", f"Instagram javoblarimizdan birini yashirdi yoki o'chirdi. Javoblar {PAUSE_HOURS} soatga to'xtatildi.")
            break


def reply(comment_id, token, text):
    body = urllib.parse.urlencode({"message": text, "access_token": token}).encode()
    try:
        with urllib.request.urlopen(f"{GRAPH}/{comment_id}/replies", data=body, timeout=30) as r:
            check_usage(r.headers)
            return json.load(r).get("id")
    except urllib.error.HTTPError as e:
        raise Rejected(e.read().decode(errors="replace")[:300])


def queue(st):
    data = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    done_users, done_comments, seen, out = set(st["users"]), set(st["comments"]), set(), []
    for v in data["votes"]:  # eskisidan yangisiga
        u = v["username"].lower()
        if v["status"] != "hisoblandi" or not v.get("id") or u in done_users or u in seen or v["id"] in done_comments:
            continue
        seen.add(u)
        out.append(v)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true")
    p.add_argument("--max", type=int, default=0, help="nechta javob (0 = budjet bo'yicha)")
    p.add_argument("--budget", type=int, default=0, help="soniya: shuncha vaqt ishlaydi (GitHub tsikli uchun)")
    p.add_argument("--gap", type=int, default=120)
    p.add_argument("--push", action="store_true", help="holatni git'ga yozib push qilish")
    a = p.parse_args()

    start = time.time()
    st = load_state()
    if not a.dry:
        try:
            health(st, read_env()["IG_TOKEN"])
        except Exception as e:
            print("Diagnostika xatosi:", e)
        save_state(st, a.push)
    if not (ROOT / "javoblar_yoqilgan").exists() and not a.dry:
        print("Avtojavoblar o'chirilgan (javoblar_yoqilgan fayli yo'q)")
        if a.budget:
            time.sleep(a.budget)
        return
    load_companies()  # ORGANIZERS ro'yxatini yuklash
    todo = queue(st)
    print(f"Navbatda: {len(todo)} ta javob")
    try:
        if a.dry:
            for v in todo[:10]:
                print(f"  → @{v['username']} ({v['company_name']}): {pick_template(v['username'].lower(), st).format(u=v['username'], c=v['company_name'])}")
            return
        token = read_env()["IG_TOKEN"]
        sent = 0
        for v in todo:
            if a.max and sent >= a.max:
                break
            if a.budget and time.time() - start + 15 > a.budget:
                break
            ok, why = limits_ok(st)
            if not ok:
                print(f"To'xtatildi: {why}")
                break
            u = v["username"].lower()
            if already_replied(v["id"], token):
                print(f"  @{u}: javob allaqachon bor, o'tkazildi")
            else:
                text = pick_template(u, st).format(u=v["username"], c=v["company_name"])
                try:
                    rid = reply(v["id"], token, text)
                except Rejected as e:
                    st["paused_until"] = (dt.datetime.now(TK) + dt.timedelta(hours=PAUSE_HOURS)).isoformat(timespec="seconds")
                    st["last_error"] = str(e)[:200]
                    alert(st, "rejected", f"⛔ Instagram javobni rad etdi — javoblar {PAUSE_HOURS} soatga to'xtatildi.\n{str(e)[:150]}")
                    save_state(st, a.push)
                    print(f"⛔ Instagram rad etdi, {PAUSE_HOURS} soat pauza: {e}")
                    break
                sent += 1
                st.setdefault("sent_at", []).append(dt.datetime.now(TK).isoformat(timespec="seconds"))
                st.setdefault("reply_ids", []).append(rid)
                st["reply_ids"] = st["reply_ids"][-50:]
                st["sent_at"] = st["sent_at"][-300:]
                print(f"  ✅ @{u} → {rid}")
            st["users"].append(u)
            st["comments"].append(v["id"])
            save_state(st, a.push)
            if (a.max and sent >= a.max) or v is todo[-1]:
                break
            pause = random.randint(a.gap, a.gap * 5 // 2)  # tasodifiy: 2–5 daqiqa
            if a.budget and time.time() - start + pause > a.budget:
                break
            time.sleep(pause)
        print(f"Yuborildi: {sent}")
    finally:
        if a.budget:  # tsikl 10 daqiqalik bo'lib qolishi uchun qolgan vaqtni kutamiz
            rest = a.budget - (time.time() - start)
            if rest > 0:
                time.sleep(rest)


if __name__ == "__main__":
    main()
