"""MT5 -> Cloudflare journal sync (versi 3)."""

import argparse
import csv
import glob
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    sys.exit("MetaTrader5 belum terpasang. Jalankan: pip install MetaTrader5")

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "history_jurnal.csv")
FMT = "%Y-%m-%d %H:%M:%S"

ENDPOINT = os.getenv("JOURNAL_ENDPOINT", "").strip()
TOKEN = os.getenv("JOURNAL_TOKEN", "").strip()


def find_terminal():
    env = os.getenv("MT5_TERMINAL", "").strip()
    if env and os.path.exists(env):
        return env
    bases = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    for base in bases:
        for path in glob.glob(os.path.join(base, "*MetaTrader*", "terminal64.exe")):
            return path
    return None


TERMINAL = find_terminal()


def mask(text, *secrets):
    for s in secrets:
        if s:
            text = text.replace(str(s), "***")
    return text


def kill_terminal():
    # Hanya di GitHub Actions. Di PC sendiri JANGAN matikan terminal yang dipakai.
    if os.getenv("GITHUB_ACTIONS", "").lower() != "true":
        return
    subprocess.run(["taskkill", "/F", "/IM", "terminal64.exe"], capture_output=True)
    time.sleep(3)


KEYS = ("authoriz", "login", "connect", "network", "fail", "invalid", "error",
        "server", "account", "timeout", "denied")


def read_log(path):
    try:
        with open(path, "r", encoding="utf-16", errors="replace") as f:
            return f.read().splitlines()
    except Exception:
        return []


def show_diag(login, password):
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
                           capture_output=True, text=True)
        print("Proses terminal64:", "ada" if "terminal64.exe" in r.stdout else "TIDAK ADA")
    except Exception as e:
        print(f"Gagal cek proses: {e}")

    dirs = glob.glob(os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "*"))
    if TERMINAL:
        dirs.append(os.path.dirname(TERMINAL))

    cands = []
    for d in dirs:
        cands += glob.glob(os.path.join(d, "logs", "*.log"))
        cands += glob.glob(os.path.join(d, "MQL5", "Logs", "*.log"))
    main = [p for p in cands if re.fullmatch(r"\d{8}\.log", os.path.basename(p))]
    main.sort(key=os.path.getmtime, reverse=True)

    if not main:
        print("Log harian terminal tidak ditemukan.")
        for p in cands[:5]:
            print("  ada:", p)
        return

    for path in main[:2]:
        lines = read_log(path)
        print(f"--- log: {os.path.basename(os.path.dirname(path))}\\{os.path.basename(path)} ({len(lines)} baris)")
        hits = [ln for ln in lines if any(k in ln.lower() for k in KEYS)]
        print("[baris penting]")
        for ln in hits[:40]:
            print(mask(ln, login, password))
        print("[25 baris terakhir]")
        for ln in lines[-25:]:
            print(mask(ln, login, password))


def try_init(**kw):
    try:
        ok = mt5.initialize(**kw)
    except Exception as e:
        print(f"initialize exception: {e}")
        return False
    if not ok:
        print(f"initialize gagal: {mt5.last_error()}")
        mt5.shutdown()
    return ok


def init_terminal(login, password, server):
    if not TERMINAL:
        print("terminal64.exe tidak ditemukan. Cek step install MT5 di workflow.")
        return False
    print(f"Terminal: {TERMINAL}")

    for attempt in (1, 2):
        kill_terminal()
        print(f"Percobaan {attempt}: initialize dengan kredensial...")
        if try_init(path=TERMINAL, login=login, password=password,
                    server=server, timeout=120000):
            print(f"MT5 terinisialisasi (percobaan {attempt})")
            return True
        time.sleep(15)

    print("Percobaan 3: luncurkan terminal lewat file config...")
    kill_terminal()
    cfg = os.path.join(tempfile.gettempdir(), "mt5_login.ini")
    try:
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(
                "[Common]\n"
                f"Login={login}\n"
                f"Password={password}\n"
                f"Server={server}\n"
                "KeepPrivate=1\n"
                "NewsEnable=0\n"
            )
        subprocess.Popen([TERMINAL, f"/config:{cfg}"])
        time.sleep(60)
        if try_init(path=TERMINAL, timeout=120000):
            print("MT5 terinisialisasi (percobaan 3, via config)")
            return True
    finally:
        try:
            os.remove(cfg)
        except OSError:
            pass

    show_diag(login, password)
    return False


def connect(login, password, server):
    if not init_terminal(login, password, server):
        sys.exit("Tidak bisa membuka terminal MT5.")

    info = mt5.account_info()
    if info is None or info.login != login:
        if not mt5.login(login, password=password, server=server):
            err = mt5.last_error()
            show_diag(login, password)
            mt5.shutdown()
            sys.exit(f"Login gagal: {err}")
        info = mt5.account_info()

    if info:
        print(f"Login OK @ {info.server}")
    else:
        print("Terminal terbuka tapi info akun belum tersedia, lanjut mencoba.")


def connect_attach():
    """Mode attach: pakai terminal MT5 yang SUDAH terbuka dan login di PC ini."""
    print("Mode attach: memakai terminal MT5 yang sudah login.")
    kw = {"path": TERMINAL} if TERMINAL else {}
    if not try_init(timeout=60000, **kw):
        sys.exit("Tidak bisa terhubung. Pastikan MT5 sudah terbuka dan login.")
    info = mt5.account_info()
    if info is None:
        mt5.shutdown()
        sys.exit("Terminal terbuka tapi belum login ke akun.")
    print(f"Terhubung @ {info.server} (akun {info.login})")


def ts(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime(FMT)


def build_rows(days):
    end = datetime.now(timezone.utc) + timedelta(days=2)
    start = datetime.now(timezone.utc) - timedelta(days=days)
    deals = mt5.history_deals_get(start, end)
    if deals is None:
        print(f"history_deals_get gagal: {mt5.last_error()}")
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
        profit = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0)
                     for d in ins + outs)

        rows.append({
            "Position": pid,
            "Symbol": ins[0].symbol,
            "Type": "Buy" if ins[0].type == mt5.DEAL_TYPE_BUY else "Sell",
            "Lots": round(vin, 2),
            "Opening time": ts(min(d.time for d in ins)),
            "Closing time": ts(max(d.time for d in outs)),
            "Open price": round(open_price, 5),
            "Close price": round(close_price, 5),
            "Profit": round(profit, 2),
        })

    rows.sort(key=lambda r: r["Closing time"])
    return rows


def wait_for_history(days, tries=15, delay=12):
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
            # Cloudflare memblokir User-Agent bawaan Python-urllib (error 1010)
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JurnalSync/3.0",
            "Accept": "*/*",
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
    print("sync_ci versi 3 (User-Agent fix)")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--tries", type=int, default=15)
    ap.add_argument("--delay", type=int, default=12)
    a = ap.parse_args()

    if os.getenv("MT5_MODE", "").strip().lower() == "attach":
        connect_attach()
    else:
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
            sys.exit("MT5_LOGIN harus berupa angka.")

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
