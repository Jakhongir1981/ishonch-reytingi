"""Telegram'ga qisqa hisobot: reyting, so'nggi 2 soatdagi ovozlar, e'tibor talab qiladigan izohlar va tizim holati.

  python report.py            # site/data.json asosida hisobot yuboradi
  python report.py --print    # yubormasdan ekranga chiqaradi
  python report.py --error "matn"   # hisob ishlamay qolsa — ogohlantirish

Kerak: TELEGRAM_BOT_TOKEN va TELEGRAM_CHAT_ID (muhit o'zgaruvchilari yoki .env).
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).parent
TK = dt.timezone(dt.timedelta(hours=5))
SITE_URL = "https://jakhongir1981.github.io/ishonch-reytingi"


def env(name):
    if os.environ.get(name):
        return os.environ[name]
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return ""


def build(data):
    now = dt.datetime.now(TK)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
    votes = data["votes"]
    ok = [v for v in votes if v["status"] == "hisoblandi"]
    fresh = [v for v in ok if dt.datetime.fromisoformat(v["timestamp"].replace("+0000", "+00:00")) >= since]
    unknown = [v for v in votes if v["reason"] == "nom aniqlanmadi"]
    approx = [v for v in ok if v.get("approx")]
    top = [r for r in data["ranking"] if r["votes"]][:5]
    usage = data.get("api_usage", {})

    lines = [f"🏆 <b>Ishonch reytingi</b> — {now:%d.%m %H:%M}", ""]
    lines.append(f"Голоса: <b>{data['counted_votes']}</b> (+{len(fresh)} за 2 ч) · комментарии: {data['total_comments']}")
    if top:
        lines.append("")
        lines += [f"{r['rank']}. {r['name']} — {r['votes']}" for r in top]
    if unknown or approx:
        lines.append("")
        lines.append(f"Проверить: {len(unknown)} не распознано, {len(approx)} приблизительно")
        for v in (unknown[-3:] + approx[-2:]):
            lines.append(f"  · @{v['username']}: «{v['text'][:40]}»" + (f" → {v['company_name']}" if v.get("company_name") else ""))
    if data.get("deadline"):
        left = dt.datetime.fromisoformat(data["deadline"]) - dt.datetime.now(TK)
        tail = f"осталось {left.days} дн." if left.total_seconds() > 0 else "голосование завершено"
    else:
        tail = "срок не задан"
    peak = usage.get("peak", 0)
    state = "✅ работает" if peak < 50 else ("⚠️ нагрузка высокая" if peak < 70 else "⛔ подсчёт приостановлен")
    lines += ["", f"Система: {state}, нагрузка Instagram {peak}% (запросов: {usage.get('calls', 0)}), {tail}", SITE_URL]
    return "\n".join(lines)


def send(text):
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN yoki TELEGRAM_CHAT_ID hali qo'shilmagan — hisobot yuborilmadi")
        return
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=30) as r:
        print("Telegram:", json.load(r).get("ok"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--print", action="store_true")
    p.add_argument("--error")
    a = p.parse_args()
    if a.error:
        text = f"⚠️ <b>Ishonch reytingi</b>: подсчёт не прошёл\n{a.error[:300]}\nСайт показывает последние успешные данные."
    else:
        data = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
        text = build(data)
    print(text) if a.print else send(text)


if __name__ == "__main__":
    main()
