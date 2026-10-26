"""Challenge Reels izohlaridan ovozlarni sanaydi.

Qoidalar:
  * faqat asosiy izohlar hisoblanadi (javoblar emas);
  * 1 akkaunt = 1 ovoz: birinchi to'g'ri izoh hisoblanadi, keyingilari "takroriy";
  * izohda bitta kompaniya nomi bo'lishi kerak; bir nechtasi bo'lsa — rad etiladi;
  * DEADLINE dan keyingi izohlar rad etiladi.

Ishlatish:
  python vote_counter.py --media <MEDIA_ID> [--deadline 2026-11-30T23:59:59+05:00]
  python vote_counter.py --latest-reel
Natija: output/results.json va output/votes.csv
"""
import argparse
import csv
import datetime as dt
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).parent
GRAPH = "https://graph.facebook.com/v26.0"
OUT = ROOT / "output"

CYR_UZ = str.maketrans({"ў": "у", "қ": "к", "ғ": "г", "ҳ": "х", "ё": "е"})
APOSTROPHES = re.compile(r"[ʻʼ'‘’`´ʹ]")
NON_WORD = re.compile(r"[^0-9a-zа-я]+")
MENTIONS_URLS = re.compile(r"@\S+|https?://\S+|www\.\S+")


def normalize(text):
    text = MENTIONS_URLS.sub(" ", text.lower()).translate(CYR_UZ)
    text = APOSTROPHES.sub("", text)
    return " " + NON_WORD.sub(" ", text).strip() + " "


def load_companies():
    data = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))
    aliases = []
    for c in data["companies"]:
        for a in set(c["aliases"]) | {c["name"]}:
            norm = normalize(a).strip()
            if norm:
                aliases.append((norm, c["id"]))
    aliases.sort(key=lambda x: -len(x[0]))  # uzunroq nom birinchi: "apex life" > "apex"
    names = {c["id"]: c["name"] for c in data["companies"]}
    return aliases, names


def match_companies(text, aliases):
    """Izohdagi kompaniya id larini qaytaradi; topilgan qism boshqa nomga qayta ishlatilmaydi."""
    norm = normalize(text)
    found = []
    for alias, cid in aliases:
        needle = f" {alias} "
        while needle in norm:
            found.append(cid)
            norm = norm.replace(needle, " # ", 1)
    return sorted(set(found))


def classify(comments, aliases, deadline=None):
    """comments: [{id, username, text, timestamp}] -> har biriga status va sabab qo'shilgan ro'yxat."""
    voted = {}
    rows = []
    for c in sorted(comments, key=lambda c: c["timestamp"]):
        ids = match_companies(c["text"], aliases)
        row = dict(c, company=None, status="rad etildi", reason="")
        ts = dt.datetime.fromisoformat(c["timestamp"].replace("+0000", "+00:00"))
        if deadline and ts > deadline:
            row["reason"] = "muddatdan keyin"
        elif not ids:
            row["reason"] = "nom aniqlanmadi"
        elif len(ids) > 1:
            row["reason"] = "bir nechta nom"
        elif c["username"].lower() in voted:
            row["reason"] = "takroriy"
            row["company"] = ids[0]
        else:
            voted[c["username"].lower()] = ids[0]
            row.update(company=ids[0], status="hisoblandi")
        rows.append(row)
    return rows


def tally(rows, names):
    counts = {cid: 0 for cid in names}
    for r in rows:
        if r["status"] == "hisoblandi":
            counts[r["company"]] += 1
    ranking = sorted(counts.items(), key=lambda kv: (-kv[1], names[kv[0]]))
    return [{"rank": i + 1, "id": cid, "name": names[cid], "votes": n} for i, (cid, n) in enumerate(ranking)]


# --- Instagram API ---

def read_env():
    """.env fayli (kompyuterda) yoki muhit o'zgaruvchilari (GitHub Actions)."""
    env = {k: os.environ[k] for k in ("IG_TOKEN", "IG_USER_ID") if os.environ.get(k)}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def api(path, token, **params):
    params["access_token"] = token
    url = path if path.startswith("http") else f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Instagram API xatosi: {json.load(e).get('error', {}).get('message')}")


def latest_reel(env):
    media = api(f"{env['IG_USER_ID']}/media", env["IG_TOKEN"], fields="id,media_product_type,timestamp,permalink", limit=25)
    reels = [m for m in media["data"] if m.get("media_product_type") == "REELS"]
    if not reels:
        raise SystemExit("Akkauntda Reels topilmadi")
    return reels[0]["id"]


def fetch_comments(env, media_id):
    page = api(f"{media_id}/comments", env["IG_TOKEN"], fields="id,username,text,timestamp", limit=50)
    comments = []
    while True:
        comments += page.get("data", [])
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            return comments
        page = api(nxt, env["IG_TOKEN"])


SITE = ROOT / "site"


def sample_comments(names):
    """Sahifani ko'rsatish uchun namuna izohlar (haqiqiy ovoz emas)."""
    import random
    rnd = random.Random(7)
    ids = list(names)
    weights = [rnd.random() ** 3 for _ in ids]
    base = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    out = []
    for i in range(420):
        r = rnd.random()
        if r < .08:
            text = rnd.choice(["Zo'r challenge!", "Qachon natija?", "🔥🔥🔥", "@do'stim qara"])
        elif r < .11:
            a, b = rnd.sample(ids, 2)
            text = f"{names[a]} yoki {names[b]}"
        else:
            text = names[rnd.choices(ids, weights)[0]]
        user = f"namuna_{rnd.randint(1, 380):03d}"
        out.append({"id": str(i), "username": user, "text": text,
                    "timestamp": (base + dt.timedelta(minutes=10 * i)).strftime("%Y-%m-%dT%H:%M:%S+0000")})
    return out


def write_outputs(result):
    OUT.mkdir(exist_ok=True)
    SITE.mkdir(exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, indent=1)
    for folder in (OUT, SITE):
        (folder / ("results.json" if folder == OUT else "data.json")).write_text(payload, encoding="utf-8")
        with open(folder / "votes.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["vaqt", "akkaunt", "izoh", "kompaniya", "holat", "sabab"])
            for v in result["votes"]:
                w.writerow([v["timestamp"], v["username"], v["text"], v["company_name"] or "", v["status"], v["reason"]])
    # Joylash uchun to'liq HTML hujjat (page.html — sahifaning o'zi)
    page = (SITE / "page.html").read_text(encoding="utf-8")
    (SITE / "index.html").write_text(
        '<!doctype html>\n<html lang="uz">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"</head>\n<body>\n{page}\n</body>\n</html>\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--media")
    p.add_argument("--latest-reel", action="store_true")
    p.add_argument("--sample", action="store_true", help="namuna ma'lumot bilan sahifa yasash")
    p.add_argument("--deadline", help="ISO vaqt, masalan 2026-11-30T23:59:59+05:00")
    p.add_argument("--days", type=int, help="muddat: joylangan kun 1-kun; N-kun tugashi bilan (tungi 00:00, Toshkent) yopiladi")
    a = p.parse_args()

    aliases, names = load_companies()
    media_id = permalink = None
    posted = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    if a.sample:
        comments = sample_comments(names)
    else:
        env = read_env()
        media_id = a.media or (latest_reel(env) if a.latest_reel else None)
        if not media_id:
            raise SystemExit("--media, --latest-reel yoki --sample kerak")
        info = api(media_id, env["IG_TOKEN"], fields="permalink,timestamp")
        permalink = info.get("permalink")
        posted = dt.datetime.fromisoformat(info["timestamp"].replace("+0000", "+00:00"))
        comments = fetch_comments(env, media_id)
    if a.days and not a.deadline:
        tk = dt.timezone(dt.timedelta(hours=5))
        day = posted.astimezone(tk).date() + dt.timedelta(days=a.days)
        a.deadline = dt.datetime.combine(day, dt.time(0, 0), tk).isoformat()
    deadline = dt.datetime.fromisoformat(a.deadline) if a.deadline else None

    rows = classify(comments, aliases, deadline)
    ranking = tally(rows, names)
    counted = sum(r["status"] == "hisoblandi" for r in rows)
    result = {
        "media_id": media_id,
        "permalink": permalink,
        "sample": a.sample,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "deadline": a.deadline,
        "total_comments": len(rows),
        "counted_votes": counted,
        "ranking": ranking,
        "votes": [{k: r[k] for k in ("timestamp", "username", "text", "company", "status", "reason")} | {"company_name": names.get(r["company"])} for r in rows],
    }
    write_outputs(result)

    print(f"Izohlar: {len(rows)}, hisoblangan ovozlar: {counted}")
    for r in ranking[:10]:
        if r["votes"]:
            print(f"{r['rank']:>2}. {r['name']:<28} {r['votes']}")


if __name__ == "__main__":
    main()
