"""Challenge Reels izohlaridan ovozlarni sanaydi.

Qoidalar:
  * faqat asosiy izohlar hisoblanadi (javoblar emas);
  * 1 akkaunt = 1 ovoz: birinchi to'g'ri izoh hisoblanadi, keyingilari "takroriy";
  * izohda bitta kompaniya nomi bo'lishi kerak; bir nechtasi bo'lsa — rad etiladi;
  * DEADLINE dan keyingi izohlar rad etiladi.

Ishlatish:
  python vote_counter.py --media <MEDIA_ID> [--deadline 2026-11-30T23:59:59+05:00]
  python vote_counter.py --latest-reel
Natija: site/data.json (sayt) · output/results.json va output/votes.csv (faqat kompyuterda)
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
    """aliases: {so'zlar soni: [(so'zlar tuple, id), ...]}"""
    data = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))
    aliases = {}
    for c in data["companies"]:
        for a in set(c["aliases"]) | {c["name"]}:
            words = tuple(normalize(a).split())
            if words:
                aliases.setdefault(len(words), []).append((words, c["id"]))
    names = {c["id"]: c["name"] for c in data["companies"]}
    WEAK.update(normalize(w).strip() for w in data.get("weak_words", []))
    ORGANIZERS.update(u.lower() for u in data.get("organizers", []))
    return aliases, names


WEAK = set()        # oddiy so'z ham bo'lgan nomlar ("ishonch" = ishonch, "inson" = odam)
ORGANIZERS = set()  # tashkilotchilar akkauntlari — ularning izohi ovoz emas
INDUSTRY = ("sugurt", "insur", "страх", "сугурт", "kompaniya", "компани")


def weak_ok(tokens, i, words):
    """Oddiy so'z-nom faqat qisqa izohda yoki yonida "sug'urta/insurance" bo'lsa nom sifatida olinadi."""
    if not (len(words) == 1 and words[0] in WEAK):
        return True
    nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
    return len(tokens) <= 3 or nxt.startswith(INDUSTRY)


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def close_word(w, a, multi=False):
    """Qisqartma yoki xato yozuv: "inso" ~ "inson", "kapitall" ~ "kapital". Qisqa nomlar (sqb, apex) faqat aniq.
    multi: ko'p so'zli nomning bir qismi ("apex lif" ~ "apex life") — 3 harfli qisqartma ham yetadi."""
    if w == a:
        return True
    if multi and len(w) >= 3 and a.startswith(w):
        return True
    if len(a) < 5 or len(w) < 4:
        return False
    if a.startswith(w) and len(w) * 2 >= len(a):
        return True
    return edit_distance(w, a) <= (1 if len(a) < 8 else 2)


def match_companies(text, aliases):
    """Izohdagi kompaniyalarni topadi: (id lar, taxminiy_bo'lgan_so'zlar).

    Avval uzun nomlar ("apex life" > "apex"). 1-bosqich: aniq nomlar va ko'p so'zli nomlarning
    taxminiy yozilishi; hech narsa topilmasa, 2-bosqich: bitta so'zli nomlarning taxminiy yozilishi.
    """
    tokens = normalize(text).split()

    def scan(fuzzy_single):
        used, found, approx = [False] * len(tokens), set(), []
        for n in sorted(aliases, reverse=True):
            for i in range(len(tokens) - n + 1):
                if any(used[i:i + n]):
                    continue
                gram = tuple(tokens[i:i + n])
                cands = {cid for words, cid in aliases[n] if words == gram and weak_ok(tokens, i, words)}
                if not cands and (n > 1 or fuzzy_single):
                    cands = {cid for words, cid in aliases[n]
                             if all(close_word(w, a, n > 1) for w, a in zip(gram, words))
                             and (n == 1 or any(w == a for w, a in zip(gram, words)))
                             and weak_ok(tokens, i, words)}
                    if cands:
                        approx.append(" ".join(gram))
                if cands:
                    found |= cands
                    used[i:i + n] = [True] * n
        return found, approx

    found, approx = scan(fuzzy_single=False)
    if not found:
        found, approx = scan(fuzzy_single=True)
    return sorted(found), approx


def classify(comments, aliases, deadline=None):
    """comments: [{id, username, text, timestamp}] -> har biriga status va sabab qo'shilgan ro'yxat."""
    voted = {}
    rows = []
    for c in sorted(comments, key=lambda c: c["timestamp"]):
        ids, approx = match_companies(c["text"], aliases)
        row = dict(c, company=None, status="rad etildi", reason="", approx=", ".join(approx))
        ts = dt.datetime.fromisoformat(c["timestamp"].replace("+0000", "+00:00"))
        if c["username"].lower() in ORGANIZERS:
            row["reason"] = "tashkilotchi"
        elif deadline and ts > deadline:
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
            USAGE["calls"] += 1
            check_usage(r.headers)
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Instagram API xatosi: {json.load(e).get('error', {}).get('message')}")


USAGE = {"peak": 0, "calls": 0}  # hisobot uchun: Meta limitining eng yuqori foizi va so'rovlar soni
USAGE_LIMIT = 50  # foiz: Meta limitining yarmiga yetsak to'xtaymiz (ogohlantirish 25% da replies.py da) — sayt eski raqamlar bilan qoladi


def check_usage(headers):
    """Meta har javobda limitdan qancha foiz ishlatilganini aytadi; chegaraga yetmasdan to'xtaymiz."""
    raw = headers.get("x-business-use-case-usage") or headers.get("x-app-usage")
    if not raw:
        return
    data = json.loads(raw)
    entries = [e for v in data.values() for e in v] if isinstance(data, dict) and all(isinstance(v, list) for v in data.values()) else [data]
    peak = max((max(e.get("call_count", 0), e.get("total_cputime", 0), e.get("total_time", 0)) for e in entries), default=0)
    USAGE["peak"] = max(USAGE["peak"], peak)
    if peak >= USAGE_LIMIT:
        raise SystemExit(f"Instagram limiti {peak}% ishlatilgan — bu safar hisob o'tkazib yuborildi")


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
    (OUT / "results.json").write_text(payload, encoding="utf-8")
    (SITE / "data.json").write_text(payload, encoding="utf-8")
    # To'liq CSV ro'yxat faqat kompyuterda (output/) — saytga va GitHub'ga chiqmaydi
    with open(OUT / "votes.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["vaqt", "akkaunt", "izoh", "kompaniya", "holat", "sabab", "taxminiy"])
        for v in result["votes"]:
            w.writerow([v["timestamp"], v["username"], v["text"], v["company_name"] or "", v["status"], v["reason"], v["approx"]])
    (SITE / "votes.csv").unlink(missing_ok=True)
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
    p.add_argument("--empty", action="store_true", help="challenge boshlanishidan oldin: hamma joyda 0")
    p.add_argument("--deadline", help="ISO vaqt, masalan 2026-11-30T23:59:59+05:00")
    p.add_argument("--days", type=int, help="muddat: joylangan kun 1-kun; N-kun tugashi bilan (tungi 00:00, Toshkent) yopiladi")
    a = p.parse_args()

    aliases, names = load_companies()
    media_id = permalink = None
    posted = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    if a.empty:
        comments = []
    elif a.sample:
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
    if a.days and not a.deadline and not a.empty:
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
        "pending": a.empty,
        "api_usage": USAGE,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "deadline": a.deadline,
        "total_comments": len(rows),
        "counted_votes": counted,
        "ranking": ranking,
        "votes": [{k: r.get(k) for k in ("id", "timestamp", "username", "text", "company", "status", "reason", "approx")} | {"company_name": names.get(r["company"])} for r in rows],
    }
    write_outputs(result)

    print(f"Izohlar: {len(rows)}, hisoblangan ovozlar: {counted}")
    for r in ranking[:10]:
        if r["votes"]:
            print(f"{r['rank']:>2}. {r['name']:<28} {r['votes']}")


if __name__ == "__main__":
    main()
