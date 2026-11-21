"""MT5 -> Cloudflare journal sync, versi CI (GitHub Actions).

Berbeda dari mt5_journal_push.py:
  - tidak ada loop (runner hidup sebentar lalu mati)
  - meluncurkan terminal lebih dulu dan menunggu IPC siap
  - menunggu history selesai diunduh dari server broker
  - exit code non-zero kalau upload gagal, supaya GitHub menandai run merah
"""

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

try:
    import MetaTrader5 as mt5
except ImportError:
    sys.exit("MetaTrader5 belum terpasang. Jalankan: pip install MetaTrader5")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "history_jurnal.csv")
FMT = "%Y-%m-%d %H:%M:%S"

ENDPOINT = os.getenv("JOURNAL_ENDPOINT", "").strip()
TOKEN = os.getenv("JOURNAL_TOKEN", "").strip()

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"


def init_terminal():
    """Luncurkan terminal dulu, lalu tunggu IPC-nya siap.

    Install MT5 yang masih baru menampilkan wizard 'Open an Account' saat
    pertama dibuka, dan itu membuat initialize() kehabisan waktu.
    """
    if os.path.exists(TERMINAL):
        print("Meluncurkan terminal MT5...")
        try:
            subprocess.Popen([TERMINAL])
        except Exception as e:
            print(f"Gagal meluncurkan terminal: {e}")
        time.sleep(45)

    for attempt in range(1, 4):
        try:
            if os.path.exists(TERMINAL):
                ok = mt5.initialize(TERMINAL, timeout=180000)
            else:
                ok = mt5.initialize(timeout=180000)
        except Exception as e:
            print(f"initialize exception: {e}")
            ok = False

        if ok:
            print(f"MT5 terinisialisasi (percobaan {attempt})")
            return True

        print(f"initialize gagal (percobaan {attempt}): {mt5.last_error()}")
        time.sleep(20)

    return False


def connect(login, password, server):
    if not init_terminal():
        sys.exit("Tidak bisa membuka terminal MT5.")

    if not mt5.login(login, password=password, server=server):
        err = mt5.last_error()
        mt5.shutdown()
        sys.exit(f"Login gagal: {err}")

    info = mt5.account_info()
    if info:
        print(f"Login OK: akun {info.login} @ {info.server}")


def build_rows(days):
    start = datetime.now() - timedelta(days=days)
    end = datetime.now() + timedelta(days=1)
    deals = mt5.history_deals_get(start, end)
    if deals is None:
        return []

    pos = {}
    for d in deals:
        if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            continue
        p = pos.setdefault(d.position_id, {"in": [], "out": []})
        if d.entry == mt5.DEAL_ENTRY_IN:
            p["in"].append(d)
        elif d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT):
            p["out"].append(d)

    rows = []
    for pid, p in pos.items():
        if not p["in"] or not p["out"]:
            continue

        ins, outs = p["in"], p["out"]
        vin = sum(d.volume for d in ins)
        vout = sum(d.volume for d in outs)
        if vout < vin - 1e-9:
            continue

        open_price = sum(d.price * d.volume for d in ins) / vin
        close_price = sum(d.price * d.volume for d in outs) / vout
        profit = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in ins + outs)

        rows.append({
            "Position": pid,
            "Symbol": ins[0].symbol,
            "Type": "Buy" if ins[0].type == mt5.DEAL_TYPE_BUY else "Sell",
            "Lots": round(vin, 2),
            "Opening time": datetime.fromtimestamp(min(d.time for d in ins)).strftime(FMT),
            "Closing time": datetime.fromtimestamp(max(d.time for d in outs)).strftime(FMT),
            "Open price": round(open_price, 5),
            "Close price": round(close_price, 5),
            "Profit": round(profit, 2),
        })

    rows.sort(key=lambda r: r["Closing time"])
    return rows


def wait_for_history(days, tries=15, delay=12):
    """Terminal baru butuh waktu mengunduh history dari server broker."""
    for i in range(1, tries + 1):
        rows = build_rows(days)
        if rows:
            print(f"History siap: {len(rows)} trade (percobaan {i})")
            return rows
        print(f"History belum tersedia, tunggu {delay}s ({i}/{tries})")
        time.sleep(delay)
    return []


def write_csv(rows):
    cols = ["Position", "Symbol", "Type", "Lots", "Opening time",
            "Closing time", "Open price", "Close price", "Profit"]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def push():
    import urllib.error
    import urllib.request

    if not ENDPOINT or not TOKEN:
        return 0, "JOURNAL_ENDPOINT / JOURNAL_TOKEN belum di-set"

    with open(OUT, "rb") as f:
        data = f.read()

    req = urllib.request.Request(
        ENDPOINT,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "text/csv; charset=utf-8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace").strip()
    except Exception as e:
        return 0, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--tries", type=int, default=15)
    ap.add_argument("--delay", type=int, default=12)
    a = ap.parse_args()

    login = os.getenv("MT5_LOGIN", "").strip()
    server = os.getenv("MT5_SERVER", "").strip()
    password = os.getenv("MT5_PASSWORD", "").strip()

    missing = [n for n, v in (("MT5_LOGIN", login), ("MT5_SERVER", server),
                              ("MT5_PASSWORD", password)) if not v]
    if missing:
        sys.exit(f"Secret belum di-set: {', '.join(missing)}")

    try:
        account = int(login)
    except ValueError:
        sys.exit(f"MT5_LOGIN harus berupa angka, isinya: {login!r}")

    connect(account, password, server)

    try:
        rows = wait_for_history(a.days, a.tries, a.delay)
        if not rows:
            sys.exit("Tidak ada trade yang bisa dibaca. Cek investor password dan server.")

        write_csv(rows)
        net = sum(r["Profit"] for r in rows)
        code, msg = push()
        print(f"{len(rows)} trade, net {net:,.2f} -> HTTP {code} {msg}")

        if code != 200:
            sys.exit(f"Upload gagal: HTTP {code} {msg}")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
