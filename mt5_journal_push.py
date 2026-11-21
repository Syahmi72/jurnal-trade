@echo off
set MT5_LOGIN=452048016
set MT5_SERVER=Exness-MT5Real48
set MT5_PASSWORD=Syahmi88@
set JOURNAL_ENDPOINT=https://jurnal-trade.philipsyahmi82.workers.dev/api/ingest
set JOURNAL_TOKEN=jt_zm2iisnek4u22droa7l4xaqyejnij16ux0dnmdze
py -3.12 "C:\Users\Lisha\jurnal-github-actions\mt5_journal_push.py" --days 365 --loop 5
