# Reproduce: cd backend && python3 ../docs/redesign/numbers_check.py  (needs requirements-dev.txt)
import asyncio, random, sqlite3, sys, tempfile, os
sys.path.insert(0, ".")
os.environ.setdefault("HOMEATLAS_KEY_PATH", tempfile.mktemp())
from app import db
db.DB_PATH = tempfile.mktemp(suffix=".db"); db.init_db()
from app.routes import overview
random.seed(7)
kinds = ["router","network","server","nas","container","pc","mobile","printer","smarthome","iot"]
for i in range(57):
    db.create_system({"name": f"Gerät {i}", "kind": random.choice(kinds), "ip": f"192.168.178.{i+2}" if i % 9 else "",
        "status": random.choice(["online","online","offline","unknown"]),
        "importance": "critical" if i < 12 else random.choice(["normal","low"]),
        "descriptionMd": "x" if i % 3 == 0 else ""})
for i in range(5):
    db.create_account({"label": f"Konto {i}", "category": "login"})
d = asyncio.run(overview.dashboard({"id": "x"}))
c = sqlite3.connect(db.DB_PATH)
q = lambda sql: c.execute(sql).fetchone()[0]
checks = {
  "total": q("SELECT COUNT(*) FROM systems"),
  "online": q("SELECT COUNT(*) FROM systems WHERE status='online'"),
  "critical": q("SELECT COUNT(*) FROM systems WHERE importance='critical'"),
  "accounts": q("SELECT COUNT(*) FROM accounts"),
}
ok = True
for k, v in checks.items():
    flag = "OK " if d["counts"][k] == v else "DIFF"; ok &= flag == "OK "
    print(f"{flag} counts.{k:11} api={d['counts'][k]:3} sql={v:3}")
bk = dict(c.execute("SELECT kind, COUNT(*) FROM systems GROUP BY kind").fetchall())
print("OK " if bk == d["byKind"] else "DIFF", "byKind matches GROUP BY kind; sum", sum(d["byKind"].values()), "= total", checks["total"])
print("NOTE criticalSystems listed:", len(d["criticalSystems"]), "of critical", checks["critical"])
mon = q("SELECT COUNT(*) FROM systems WHERE monitored=1")
print("NOTE monitored flag set on", mon, "systems; critical without ip/hostname:",
      q("SELECT COUNT(*) FROM systems WHERE importance='critical' AND ip='' AND hostname=''"))
