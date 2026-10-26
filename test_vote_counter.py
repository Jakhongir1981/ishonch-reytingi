"""Sun'iy izohlar bilan ovoz sanashni tekshiradi: python test_vote_counter.py"""
import datetime as dt

from vote_counter import classify, load_companies, tally

aliases, names = load_companies()

CASES = [  # (username, izoh, kutilgan kompaniya yoki rad sababi)
    ("ali", "Apex", "apex"),
    ("vali", "Apex Life eng zo'ri!", "apex_life"),
    ("gulnora", "АПЕКС", "apex"),
    ("bobur", "O‘zbekinvest 👍", "uzbekinvest"),
    ("dilnoza", "Ўзбекинвест хаёт", "uzbekinvest_hayot"),
    ("sardor", "gross insurance", "gross"),
    ("aziz", "Гросс", "gross"),
    ("kamola", "Kafolat hayot", "kafolat_hayot"),
    ("jasur", "Kafolat sug'urta", "kafolat"),
    ("madina", "O'zagrosug'urta", "uzagro"),
    ("nodir", "Халқ суғурта", "xalq"),
    ("shoxrux", "#temiryol", "temiryol"),
    ("zarina", "zo'r video, rahmat", "nom aniqlanmadi"),
    ("timur", "Apex yoki Gross, bilmadim", "bir nechta nom"),
    ("ali", "Gross", "takroriy"),
    ("ALI", "Kapital", "takroriy"),
    ("feruza", "Kapitalbank emas, Alskom", "alskom"),
    ("otabek", "Alfa Life", "alfa_life"),
    ("laylo", "alfa invest", "alfa_invest"),
    ("rustam", "SQB", "sqb"),
    ("mention", "@apex_fan @gross.uz qarang", "nom aniqlanmadi"),
    ("mention2", "@dostim Hamkor", "hamkor"),
    ("kech", "Apex", "muddatdan keyin"),
]

base = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
comments = [
    {"id": str(i), "username": u, "text": t,
     "timestamp": (base + dt.timedelta(days=30 if u == "kech" else 0, minutes=i)).strftime("%Y-%m-%dT%H:%M:%S+0000")}
    for i, (u, t, _) in enumerate(CASES)
]
rows = classify(comments, aliases, deadline=base + dt.timedelta(days=10))

fails = 0
for (u, t, want), r in zip(CASES, rows):
    got = r["company"] if r["status"] == "hisoblandi" else r["reason"]
    ok = got == want
    fails += not ok
    print(f"{'OK ' if ok else 'XATO'} {u:<9} {t:<28} -> {got}" + ("" if ok else f"  (kutilgan: {want})"))

top = [x for x in tally(rows, names) if x["votes"]]
print("\nReyting:", ", ".join(f"{x['name']} {x['votes']}" for x in top))
print(f"\n{len(CASES) - fails}/{len(CASES)} to'g'ri")
raise SystemExit(1 if fails else 0)
