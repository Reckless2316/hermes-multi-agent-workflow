from __future__ import annotations
import json,sqlite3,time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
@dataclass(frozen=True)
class QuoteState: symbol:str;bid:float|None;ask:float|None;bid_size:int|None;ask_size:int|None;exchange_bid:str|None;exchange_ask:str|None;event_ts_ms:int|None;received_ts_ms:int
@dataclass(frozen=True)
class TradeState: symbol:str;price:float|None;size:int|None;exchange:str|None;event_ts_ms:int|None;received_ts_ms:int
def _f(v):
    try:return None if v in (None,"") else float(v)
    except (TypeError,ValueError):return None
def _i(v):
    try:return None if v in (None,"") else int(float(v))
    except (TypeError,ValueError):return None
class MarketStateStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.conn=sqlite3.connect(self.path,timeout=10);self.conn.row_factory=sqlite3.Row;self.conn.execute("PRAGMA journal_mode=WAL");self.conn.execute("PRAGMA synchronous=NORMAL");self.conn.executescript("""CREATE TABLE IF NOT EXISTS latest_quotes(symbol TEXT PRIMARY KEY,bid REAL,ask REAL,bid_size INTEGER,ask_size INTEGER,exchange_bid TEXT,exchange_ask TEXT,event_ts_ms INTEGER,received_ts_ms INTEGER NOT NULL,payload_json TEXT NOT NULL);CREATE TABLE IF NOT EXISTS latest_trades(symbol TEXT PRIMARY KEY,price REAL,size INTEGER,exchange TEXT,event_ts_ms INTEGER,received_ts_ms INTEGER NOT NULL,payload_json TEXT NOT NULL);CREATE TABLE IF NOT EXISTS stream_status(id INTEGER PRIMARY KEY CHECK(id=1),connected INTEGER NOT NULL,last_event_ts_ms INTEGER,updated_ts_ms INTEGER NOT NULL,note TEXT);""");self.conn.commit()
    def __enter__(self):return self
    def __exit__(self,*exc):self.conn.close()
    def apply_event(self,event:dict[str,Any]):
        typ=str(event.get("type") or "").lower();sym=str(event.get("symbol") or "").upper().strip()
        if not sym:return
        now=int(time.time()*1000);payload=json.dumps(event,separators=(",",":"),sort_keys=True);evt=None
        if typ=="quote":
            evt=_i(event.get("askdate") or event.get("biddate") or event.get("date"));self.conn.execute("""INSERT INTO latest_quotes(symbol,bid,ask,bid_size,ask_size,exchange_bid,exchange_ask,event_ts_ms,received_ts_ms,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET bid=excluded.bid,ask=excluded.ask,bid_size=excluded.bid_size,ask_size=excluded.ask_size,exchange_bid=excluded.exchange_bid,exchange_ask=excluded.exchange_ask,event_ts_ms=excluded.event_ts_ms,received_ts_ms=excluded.received_ts_ms,payload_json=excluded.payload_json""",(sym,_f(event.get("bid")),_f(event.get("ask")),_i(event.get("bidsz")),_i(event.get("asksz")),event.get("bidexch"),event.get("askexch"),evt,now,payload))
        elif typ in {"trade","timesale","tradex"}:
            evt=_i(event.get("date"));self.conn.execute("""INSERT INTO latest_trades(symbol,price,size,exchange,event_ts_ms,received_ts_ms,payload_json) VALUES(?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET price=excluded.price,size=excluded.size,exchange=excluded.exchange,event_ts_ms=excluded.event_ts_ms,received_ts_ms=excluded.received_ts_ms,payload_json=excluded.payload_json""",(sym,_f(event.get("price",event.get("last"))),_i(event.get("size")),event.get("exch"),evt,now,payload))
        else:return
        self.conn.execute("""INSERT INTO stream_status(id,connected,last_event_ts_ms,updated_ts_ms,note) VALUES(1,1,?,?,NULL) ON CONFLICT(id) DO UPDATE SET connected=1,last_event_ts_ms=excluded.last_event_ts_ms,updated_ts_ms=excluded.updated_ts_ms,note=NULL""",(evt,now));self.conn.commit()
    def set_stream_status(self,connected,note=None):
        now=int(time.time()*1000);self.conn.execute("""INSERT INTO stream_status(id,connected,last_event_ts_ms,updated_ts_ms,note) VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET connected=excluded.connected,updated_ts_ms=excluded.updated_ts_ms,note=excluded.note""",(1 if connected else 0,None,now,note));self.conn.commit()
    def quote(self,symbol):
        r=self.conn.execute("SELECT * FROM latest_quotes WHERE symbol=?",(symbol.upper(),)).fetchone();return None if r is None else QuoteState(r["symbol"],r["bid"],r["ask"],r["bid_size"],r["ask_size"],r["exchange_bid"],r["exchange_ask"],r["event_ts_ms"],r["received_ts_ms"])
    def trade(self,symbol):
        r=self.conn.execute("SELECT * FROM latest_trades WHERE symbol=?",(symbol.upper(),)).fetchone();return None if r is None else TradeState(r["symbol"],r["price"],r["size"],r["exchange"],r["event_ts_ms"],r["received_ts_ms"])
    def quote_is_fresh(self,symbol,*,max_age_seconds=10):
        q=self.quote(symbol);return False if q is None else time.time()*1000-q.received_ts_ms<=max_age_seconds*1000
    def stream_status(self):
        r=self.conn.execute("SELECT * FROM stream_status WHERE id=1").fetchone();return None if r is None else dict(r)
