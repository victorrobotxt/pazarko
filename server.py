#!/usr/bin/env python3
"""
Price-comparison web app: JSON API + static frontend over prices.db (built by ingest.py + derive.py).

  python3 server.py [--db prices.db] [--port 8080]

API (all GET unless noted, JSON). Every listing takes the location scope
  area=<municipality code, e.g. SOF46>   only what is sold there (and its local prices)
  online=0|1                            include online-only chains that deliver (default 1)

  /api/stats
  /api/stores
  /api/areas                           municipalities with outlets, for the location picker
  /api/search?q=&store=&dept=&discounts=1&card=1&min_stores=2
             &sort=relevance|price|unit|discount|drop&collapse=family|group|none&page=1&per_page=24
  /api/deals?store=&limit=24&collapse=family&honest=1&expiring=1
                                      honest=1 drops promos whose 'regular' price is inflated (EU Omnibus 30-day
                                      check); expiring=1 only promos ending within 2 days
  /api/drops?store=&limit=24          price fell vs. ~a week ago
  /api/upcoming?store=&limit=48       promotions that start later (next week's leaflets)
  /api/shrinkflation?store=&limit=48  smaller pack, same or higher price per kg/l
  /api/product/{id}
  /api/family/{id}?cards=lidl,kaufland  variants x chains matrix (cards: loyalty-card prices count for these chains)
  POST /api/basket   {"items": [{"product_id": 1, "qty": 2}, {"family_id": 7}, {"product_id": 3,
                                 "allow_family_substitute": 1}], "area": "SOF46", "online": 1,
                      "max_stores": 2, "min_savings_per_store": 2.5, "cards": ["lidl"]}
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import mimetypes
import queue
import re
import sqlite3
import threading
import urllib.parse
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import taxonomy

log = logging.getLogger("server")
WEB_DIR = Path(__file__).with_name("web")
DB_PATH = "prices.db"
_local = threading.local()
# ThreadingHTTPServer runs each request on a new thread, so a connection per thread would be opened and dropped on
# every request. Requests borrow one from this pool instead and hand it back when done (Handler.handle).
_pool: queue.SimpleQueue = queue.SimpleQueue()
POOL_MAX = 16

# Queries use named parameters; :area is '' when no location is chosen, so the area joins match nothing.
# Price a shopper can get without a loyalty card: promo if active, else the cheapest outlet price -- in the
# chosen municipality when one is set.
LOCAL_MIN = "COALESCE(pa.price_min, c.price_min)"
# "Моите карти": :cards is ',lidl,billa,' (',*,' = every chain); a chain's loyalty-card price counts for its card holders.
CARD = "CASE WHEN c.card_eur IS NOT NULL AND (:cards = ',*,' OR instr(:cards, ',' || s.slug || ',') > 0) THEN c.card_eur END"
NO_CARD = f"MIN({LOCAL_MIN}, COALESCE(c.promo_eur, {LOCAL_MIN}))"
EFFECTIVE = f"MIN({NO_CARD}, COALESCE({CARD}, {LOCAL_MIN}))"
# Sold in the chosen place: an online chain (if wanted), a KZP price from an outlet there, or a chain-wide
# catalogue price from a chain that has a shop there.
AVAILABLE = """(CASE WHEN si.channel = 'online' THEN :online = 1
                     WHEN :area = '' THEN 1
                     ELSE pa.product_id IS NOT NULL OR (c.outlets = 0 AND sa.store_id IS NOT NULL) END)"""

PRODUCT_COLS = f"""
    p.id, p.name, p.brand, p.unit_text, COALESCE(p.image_url, g.image_url, f.image_url) AS image_url,
    p.product_url, p.category_path,
    s.id AS store_id, s.slug AS store_slug, s.name AS store_name,
    si.channel, si.n_areas AS store_areas, si.area_names AS store_area_names, sa.outlets AS store_area_outlets,
    c.price, {LOCAL_MIN} AS price_min, COALESCE(pa.price_max, c.price_max) AS price_max, c.regular,
    COALESCE(pa.outlets, c.outlets) AS outlets, c.outlets AS outlets_total,
    c.promo_eur, c.promo_to, c.promo_label, c.card_eur, c.card_label, c.min_quantity, c.discount_pct,
    CASE WHEN c.size_g >= 10 THEN ROUND({EFFECTIVE} / c.size_g * 1000, 2) END AS unit_price,
    CASE WHEN c.size_g >= 10 THEN CASE c.size_unit WHEN 'ml' THEN 'l' ELSE 'kg' END END AS unit_per,
    CASE WHEN c.pieces > 1 THEN ROUND({EFFECTIVE} / c.pieces, 3) END AS piece_price, c.pieces, c.observed_on,
    c.prev_price, c.prev_day, c.change_pct,
    {EFFECTIVE} AS effective, CASE WHEN {CARD} < {NO_CARD} THEN 1 ELSE 0 END AS with_card, c.group_id, g.n_stores AS group_stores, g.min_price AS group_min,
    c.dept, c.kind, c.family_id, c.variant, c.variant_row,
    c.prior_price, c.prior_median, c.real_discount_pct, c.fake_promo, c.size_g,
    f.name AS family_name, f.size_text AS family_size_text, f.n_groups AS family_groups,
    {AVAILABLE} AS available
"""
PRODUCT_FROM = """
    FROM product_current c
    JOIN products p ON p.id = c.product_id
    JOIN stores s ON s.id = c.store_id
    JOIN store_info si ON si.store_id = c.store_id
    LEFT JOIN product_groups g ON g.id = c.group_id
    LEFT JOIN product_families f ON f.id = c.family_id
    LEFT JOIN product_area pa ON pa.product_id = c.product_id AND pa.area = :area
    LEFT JOIN store_area sa ON sa.store_id = c.store_id AND sa.area = :area
"""
DELIVERY = "'glovo_delivery'"             # derive.DELIVERY_SOURCES, as an SQL list
COLLAPSE_KEY = {"family": "family_id", "group": "group_id", "none": "id"}
# Full-text hits, computed once per query and joined (a per-row bm25 subquery re-runs the MATCH per product).
# Column weights name:brand:category:alt = 10:4:1:3, so a category-path hit ranks below a name hit.
FTS_HITS = """JOIN (SELECT rowid AS hid, bm25(products_fts, 10.0, 4.0, 1.0, 3.0) AS score FROM products_fts
                    WHERE products_fts MATCH :match) h ON h.hid = c.product_id"""
FTS_HEAD = """LEFT JOIN (SELECT rowid AS hh FROM products_fts WHERE products_fts MATCH :head) hd ON hd.hh = c.product_id"""


def db() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        try:
            conn = _pool.get_nowait()
        except queue.Empty:
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def release_db():
    """Return this thread's connection to the pool (or close it when the pool is full)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        return
    _local.conn = None
    if conn.in_transaction:
        conn.rollback()
    if _pool.qsize() < POOL_MAX:
        _pool.put(conn)
    else:
        conn.close()


def rows(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in db().execute(sql, args)]


MAX_WORDS = 10                  # each word adds OR'ed FTS alternatives; a pasted paragraph must not blow up the query


def _words(q: str) -> list[str]:
    words = re.findall(r"[\wА-Яа-я]+", q, re.UNICODE)
    return [w for w in words if len(w) >= 2 or w.isdigit()][:MAX_WORDS]   # keep sizes like 'pampers 4'


def fts_query(q: str, phonetic: bool = True, typos: bool = False, strict: bool = False) -> str | None:
    """User text -> FTS5 query. Every word must prefix-match the name/brand/category, or match the
    transliterated/skeleton forms in 'alt', so 'roshen' finds 'РОШЕН', 'mlqko' finds 'мляко' and 'монстър' finds
    'Monster'. A bare number matches whole words only ('pampers 4' is not '48 бр.').
    phonetic=False leaves out the consonant skeletons (see _phonetic_scope); typos=True adds the vowel-less
    taxonomy.typo_key, for when nothing else matched ('кашкавл'). strict=True is the 'spelled out' query of
    _phonetic_scope: other-script spellings must be whole words there, since 'monster*' in Latin also starts
    'МОНСТЕРА' (a houseplant) and 'fit*' starts 'ФИТНЕС'."""
    words = _words(q)
    parts = [_fts_word(w, phonetic, typos, strict) for w in words]
    # Two words typed apart may be one in the name: 'fit spo' is 'FitSpo', '7 days' is '7Days'.
    out, i = [], 0
    while i < len(parts):
        if i + 1 < len(parts) and len(words[i] + words[i + 1]) >= 5 and not words[i + 1].isdigit():
            out.append(f"(({parts[i]} AND {parts[i + 1]}) OR "
                       f"{_fts_word(words[i] + words[i + 1], phonetic, typos, strict)})")
            i += 2
        else:
            out.append(parts[i])
            i += 1
    return " AND ".join(out) or None


def _fts_word(w: str, phonetic: bool, typos: bool, strict: bool) -> str:
    """One query word -> its FTS5 alternatives (see fts_query)."""
    star = "" if w.isdigit() else "*"
    alts = [f'{{name brand category_path}} : "{w}"{star}']
    forms = dict.fromkeys([w, taxonomy.shlyokavitsa(w)])          # 'aqua' stays, 'mlqko' adds 'mlyako'
    for lat in dict.fromkeys(taxonomy.latin_key(f) for f in forms):
        if len(lat) >= 3:
            alts.append(f'alt : "{lat}"{"" if strict else star}')
    for f in forms:
        sk = taxonomy.skeleton(f)
        if phonetic and taxonomy.phonetic_ok(sk):
            alts.append(f'alt : "{sk}"')
        tk = taxonomy.typo_key(f)
        if phonetic and typos and tk:
            alts.append(f'alt : "{tk}"')
    return "(" + " OR ".join(dict.fromkeys(alts)) + ")"


def head_query(word: str) -> str:
    """'Name starts with the first query word', also in Cyrillic for a Latin-typed word ('mlqko' -> 'МЛЯКО',
    'roshen' -> 'РОШЕН'), so 'Мляко ...' outranks 'Кашкавал от краве мляко' for either spelling."""
    forms = [word]
    if re.fullmatch(r"[A-Za-z]*[A-Za-z][A-Za-z0-9]*", word):
        forms.append(taxonomy.to_cyrillic(taxonomy.shlyokavitsa(word)))
    return " OR ".join(f'name : ^ "{f}"*' for f in dict.fromkeys(forms))


def _fts_any(match: str) -> bool:
    return db().execute("SELECT 1 FROM products_fts WHERE products_fts MATCH ? LIMIT 1", (match,)).fetchone() is not None


# A skeleton drops the vowels, so 'dallmayr' also sounds like 'ДАЛМОР' (whisky). A hit found only by its skeleton
# is kept when it is in a department the spelled-out hits are in, and is not another brand: 'монстър' still
# finds 'Monster' energy drinks, 'dallmayr' no longer finds The Dalmore.
FTS_STRICT = """LEFT JOIN (SELECT rowid AS sh FROM products_fts WHERE products_fts MATCH :strict) st
                ON st.sh = c.product_id"""


def _phonetic_scope(strict: str, where: list, args: dict) -> str:
    """Restrict skeleton-only hits to the departments/brands of the literal hits; returns the extra join.
    A department counts only when it holds a real share of the literal hits (the _intent rule), so one stray
    'Dallmayr' in spirits does not let every Dalmore whisky in."""
    found = db().execute("""SELECT c.dept, c.brand, COUNT(*) FROM products_fts f
                            JOIN product_current c ON c.product_id = f.rowid
                            WHERE products_fts MATCH ? GROUP BY c.dept, c.brand""", (strict,)).fetchall()
    if not found:
        return ""                     # nothing spelled like the query: the skeleton is all we have (typos)
    per_dept = Counter()
    for d, _b, n in found:
        per_dept[d] += n
    top = max(per_dept.values())
    depts = sorted(d for d, n in per_dept.items() if d and n >= min(top, max(2, 0.25 * top)))
    brands = sorted({b for d, b, _n in found if b and d in depts})
    args.update({"strict": strict, **{f"pd{i}": d for i, d in enumerate(depts)},
                 **{f"pb{i}": b for i, b in enumerate(brands)}})
    dept_in = ",".join(f":pd{i}" for i in range(len(depts))) or "NULL"
    brand_in = ",".join(f":pb{i}" for i in range(len(brands))) or "NULL"
    where.append(f"(st.sh IS NOT NULL OR (c.dept IN ({dept_in}) AND (c.brand IS NULL OR c.brand IN ({brand_in}))))")
    return FTS_STRICT


def _int(q: dict, key: str, default: int, lo: int, hi: int) -> int:
    """An integer parameter clamped to [lo, hi] (SQLite overflows past 2**63, and LIMIT -1 means no limit)."""
    try:
        v = int(q.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be an integer")
    return max(lo, min(hi, v))


def scope(q: dict) -> dict:
    """Named parameters for the location scope and the shopper's loyalty cards."""
    area = str(q.get("area") or "").strip().upper()
    cards = card_stores(q)
    return {"area": area if re.fullmatch(r"[A-Z]{3}\d{2}", area) else "",
            "online": 0 if str(q.get("online", "1")) in ("0", "false") else 1,
            "cards": "," + ",".join(sorted(cards)) + "," if cards else ""}


def card_stores(q: dict) -> set[str] | None:
    """The shopper's loyalty cards ("Моите карти"): 'cards=lidl,kaufland' (a list in a POST body), 'cards=*' for
    every chain. None = no card prices count (card=1 alone only adds card offers to the discounts filter)."""
    v = q.get("cards")
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, list):
        return None
    out = {x for x in (str(c).strip().lower() for c in v[:80]) if re.fullmatch(r"[\w*-]{1,40}", x)}
    return {"*"} if "*" in out or "all" in out else (out or None)


# --------------------------------------------------------------------------- handlers

def api_stats(_q):
    r = db().execute("""SELECT
        (SELECT COUNT(*) FROM product_current) AS products,
        (SELECT COUNT(DISTINCT store_id) FROM product_current) AS stores,
        (SELECT COUNT(*) FROM outlets) AS outlets,
        (SELECT COUNT(*) FROM areas) AS areas,
        (SELECT COUNT(*) FROM product_groups WHERE n_stores > 1) AS compared,
        (SELECT COUNT(*) FROM product_current WHERE promo_eur IS NOT NULL OR card_eur IS NOT NULL) AS promos,
        (SELECT MAX(observed_on) FROM product_current) AS last_updated""").fetchone()
    runs = rows("""SELECT source, status, items, finished_at FROM ingest_runs
                   WHERE id IN (SELECT MAX(id) FROM ingest_runs GROUP BY source) ORDER BY source""")
    return {**dict(r), "sources": runs}


def api_stores(_q):
    return {"stores": rows("""
        SELECT s.id, s.slug, s.name, s.website, si.channel, si.outlets, si.n_areas, si.area_names,
               COUNT(c.product_id) AS products, SUM(c.promo_eur IS NOT NULL OR c.card_eur IS NOT NULL) AS promos
        FROM stores s JOIN product_current c ON c.store_id = s.id JOIN store_info si ON si.store_id = s.id
        GROUP BY s.id ORDER BY products DESC""")}


def api_areas(_q):
    return {"areas": rows("SELECT code, name, province, outlets, stores FROM areas ORDER BY outlets DESC, name"),
            "online_stores": rows("""SELECT s.slug, s.name FROM store_info si JOIN stores s ON s.id = si.store_id
                                     WHERE si.channel = 'online'""")}


def _filters(q: dict, where: list, args: dict):
    if q.get("store"):
        ids = [x for x in q["store"].split(",") if x][:80]
        where.append(f"s.slug IN ({','.join(f':st{i}' for i in range(len(ids)))})")
        args.update({f"st{i}": x for i, x in enumerate(ids)})
    if q.get("discounts") in ("1", "true"):
        where.append("(c.promo_eur IS NOT NULL OR c.discount_pct > 0"
                     + (" OR c.card_eur IS NOT NULL)" if q.get("card") in ("1", "true") else ")"))
    if q.get("min_stores"):
        where.append("g.n_stores >= :min_stores")
        args["min_stores"] = _int(q, "min_stores", 1, 1, 1000)
    where.append(AVAILABLE)


def _listing(q: dict, where: list, args: dict, *, rank: str = "0", order: str, rep_order: str = "effective ASC",
             collapse: str = "family", page: int = 1, per_page: int = 24, intent: set | None = None, join: str = ""):
    """Shared by search/deals/drops: filter, collapse to one row per family/group, page, and attach the
    per-chain price strip of each family on the page."""
    off = (f"CASE WHEN c.dept IN ({','.join(f':in{i}' for i in range(len(intent)))}) THEN 0 ELSE 1 END"
           if intent else "0")
    if intent:
        args.update({f"in{i}": d for i, d in enumerate(sorted(intent))})
    base = f"SELECT {PRODUCT_COLS}, {rank} AS rank, {off} AS off {PRODUCT_FROM} {join} WHERE {' AND '.join(where)}"
    key = COLLAPSE_KEY.get(collapse, "family_id")
    # One row per family/group: the best member by rep_order, ranked by the family's best member.
    coll = f"""SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY {key} ORDER BY {rep_order}) AS rn,
                   MIN(rank) OVER (PARTITION BY {key}) AS krank, MIN(off) OVER (PARTITION BY {key}) AS koff,
                   COUNT(*) OVER (PARTITION BY {key}) AS kcount FROM ({base})) WHERE rn = 1"""
    # COUNT(*) OVER () is computed before LIMIT, so one pass gives both the page and the total.
    items = rows(f"SELECT *, COUNT(*) OVER () AS total_ FROM ({coll}) ORDER BY {order} LIMIT :lim OFFSET :off_",
                 {**args, "lim": per_page, "off_": (page - 1) * per_page})
    if items:
        total = items[0]["total_"]
        for it in items:
            del it["total_"]
    elif page > 1:                # past the last page: no row carries the total
        total = db().execute(f"SELECT COUNT(*) FROM ({coll})", args).fetchone()[0]
    else:
        total = 0
    fams = [it["family_id"] for it in items if collapse == "family" and it["kcount"] > 1]
    if fams:
        fargs = {**args, **{f"f{i}": f for i, f in enumerate(fams)}}
        fin = ",".join(f":f{i}" for i in range(len(fams)))
        # unit_min is the price per kg/l of the chain's cheapest offer (the price shown next to it), not the
        # lowest of any of its packs.
        strip = collections_by(rows(f"""
            SELECT family_id, store_slug, store_name, channel, MIN(effective) AS min, COUNT(*) AS n,
                   MAX(COALESCE(discount_pct, 0)) AS disc, MAX(CASE WHEN rn_ = 1 THEN unit_price END) AS unit_min,
                   MAX(with_card) AS with_card
            FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY family_id, store_id
                                               ORDER BY effective, unit_price IS NULL, unit_price) AS rn_
                  FROM ({base}) WHERE family_id IN ({fin}))
            GROUP BY family_id, store_id ORDER BY min""", fargs),
            "family_id")
        nvar = dict(db().execute(f"""SELECT family_id, COUNT(DISTINCT variant_row) FROM ({base})
                                     WHERE family_id IN ({fin}) GROUP BY family_id""", fargs).fetchall())
        for it in items:
            if it["family_id"] in strip:
                units = [s_["unit_min"] for s_ in strip[it["family_id"]] if s_["unit_min"]]
                it["family"] = {"id": it["family_id"], "name": it["family_name"], "size_text": it["family_size_text"],
                                "variants": nvar.get(it["family_id"], 1), "variants_total": it["family_groups"],
                                "products": it["kcount"], "stores": strip[it["family_id"]],
                                "unit_min": min(units) if units else None, "unit_per": it["unit_per"]}
    return items, total


def collections_by(items: list[dict], key: str) -> dict:
    out: dict = {}
    for it in items:
        out.setdefault(it.pop(key), []).append(it)
    return out


def _intent(where: list, args: dict, join: str) -> tuple[set, list[dict]]:
    """Department mix of the matches. The departments holding most of them are what the query is about
    ('monster' -> drinks); the rest (toys, cloths, toothbrushes) is ranked below as 'other results'."""
    counts = rows(f"""SELECT c.dept, COUNT(*) AS n {PRODUCT_FROM} {join}
                      WHERE {' AND '.join(where)} GROUP BY c.dept ORDER BY n DESC""", args)
    if not counts:
        return set(), []
    top = counts[0]["n"]
    total = sum(r["n"] for r in counts)
    primary = {r["dept"] for r in counts if r["n"] >= max(2, 0.25 * top)}
    # Only call something off-topic when the main intent is clear and the rest is a minority.
    if sum(r["n"] for r in counts if r["dept"] in primary) < 0.6 * total:
        primary = set()
    facets = sorted(({"dept": r["dept"], "label": taxonomy.DEPTS.get(r["dept"], r["dept"]), "count": r["n"],
                      "primary": r["dept"] in primary} for r in counts), key=lambda f: not f["primary"])
    return primary, facets


def gtin_query(q: str) -> str | None:
    """A scanned barcode ('5449000004840', EAN-8/UPC-A padded to 13 digits) when the query is one, else None."""
    code = q.strip()
    if not re.fullmatch(r"\d{8}|\d{12,14}", code):
        return None
    return code.zfill(13) if len(code) in (8, 12) else code


def api_search(q):
    page = _int(q, "page", 1, 1, 10_000)
    per_page = _int(q, "per_page", 24, 1, 100)
    args = scope(q)
    where, join = [], ""
    gtin = gtin_query(q.get("q", ""))
    if gtin and db().execute("SELECT 1 FROM ean_mappings WHERE gtin = ?", (gtin,)).fetchone():
        # Barcode scan: the products carrying it, and everything matched to them across chains.
        _filters(q, where, args)
        where.append("""(c.product_id IN (SELECT product_id FROM ean_mappings WHERE gtin = :gtin) OR c.group_id IN
                         (SELECT c2.group_id FROM ean_mappings e JOIN product_current c2 ON c2.product_id = e.product_id
                          WHERE e.gtin = :gtin))""")
        args["gtin"] = gtin
        items, total = _listing(q, where, args, order="effective ASC", collapse="group", page=page, per_page=per_page)
        return {"items": items, "total": total, "page": page, "per_page": per_page,
                "pages": (total + per_page - 1) // per_page, "query": None, "barcode": gtin, "facets": [],
                "intent": []}
    match = fts_query(q.get("q", ""))
    if match and not _fts_any(match):
        match = fts_query(q.get("q", ""), typos=True)
    if not (match or q.get("store") or q.get("discounts") in ("1", "true") or q.get("dept")):
        return {"error": "give q, store, dept or discounts"}, HTTPStatus.BAD_REQUEST
    _filters(q, where, args)
    sort = q.get("sort", "relevance")
    rank = "0"
    if match:
        join = FTS_HITS
        args["match"] = match
        strict = fts_query(q.get("q", ""), phonetic=False, strict=True)
        if strict != match:
            join += " " + _phonetic_scope(strict, where, args)
        if sort == "relevance":
            # Names that *start* with the first query word ('Банани ...') beat ones that merely contain it
            # ('Пюре ... банани ...').
            join += " " + FTS_HEAD
            args["head"] = head_query(_words(q["q"])[0])
            rank = "(h.score - CASE WHEN hd.hh IS NOT NULL THEN 8 ELSE 0 END)"
    intent, facets = _intent(where, args, join) if match else (set(), [])
    if q.get("dept"):
        where.append("c.dept = :dept")
        args["dept"] = q["dept"]
        intent = set()
    order = {
        "price": "koff, effective ASC",
        "discount": "koff, COALESCE(discount_pct, 0) DESC, effective ASC",
        "unit": "koff, unit_price IS NULL, unit_price ASC",
        "drop": "koff, COALESCE(change_pct, 0) ASC, effective ASC",
        # bm25 is negative (lower = better); products stocked by many chains are what people compare.
    }.get(sort, "koff, krank - 0.25 * MIN(COALESCE(group_stores, 1), 25) - 0.5 * MIN(kcount, 10) ASC, effective ASC")
    rep = {"discount": "COALESCE(discount_pct, 0) DESC, effective ASC",
           "drop": "COALESCE(change_pct, 0) ASC, effective ASC"}.get(sort, "effective ASC")
    collapse = {"1": "group", "true": "group", "0": "none", "false": "none"}.get(q.get("collapse", ""),
                                                                                q.get("collapse") or "family")
    items, total = _listing(q, where, args, rank=rank, order=order, rep_order=rep, collapse=collapse, page=page,
                            per_page=per_page, intent=intent, join=join)
    return {"items": items, "total": total, "page": page, "per_page": per_page,
            "pages": (total + per_page - 1) // per_page, "query": match, "facets": facets,
            "intent": sorted(intent)}


def api_deals(q):
    limit = _int(q, "limit", 24, 1, 100)
    args = scope(q)
    where = ["c.promo_eur IS NOT NULL", "c.discount_pct BETWEEN 5 AND 90"]
    if q.get("honest") in ("1", "true"):        # the claimed regular price was really charged before the promo
        where.append("COALESCE(c.fake_promo, 0) = 0")
    if q.get("expiring") in ("1", "true"):      # last chance: ends today, tomorrow or the day after
        where.append("c.promo_to BETWEEN date('now', 'localtime') AND date('now', 'localtime', '+2 days')")
    _filters(q, where, args)
    items, _ = _listing(q, where, args, order="(group_stores > 1) DESC, discount_pct DESC",
                        rep_order="discount_pct DESC, effective ASC", collapse=q.get("collapse") or "family",
                        per_page=limit)
    return {"items": items}


def api_drops(q):
    """Products whose shelf price fell vs. about a week ago (needs KZP history: ingest --kzp-backfill)."""
    limit = _int(q, "limit", 24, 1, 100)
    args = scope(q)
    where = ["c.change_pct <= -5", "c.change_pct >= -80", "c.promo_eur IS NULL"]   # a promo is a deal, not a drop
    _filters(q, where, args)
    items, _ = _listing(q, where, args, order="(group_stores > 1) DESC, change_pct ASC",
                        rep_order="change_pct ASC, effective ASC", collapse=q.get("collapse") or "family",
                        per_page=limit)
    return {"items": items}


def api_upcoming(q):
    """Promotions announced for later days (next week's leaflets: Lidl, Kaufland, Billa's 'Предстояща брошура'),
    soonest first. A chain counts as in the area when it has a shop there (or is online)."""
    limit = _int(q, "limit", 48, 1, 200)
    args = {**scope(q), "lim": limit}
    where = ["m.valid_from > date('now', 'localtime')",
             "(:area = '' OR si.channel = 'online' AND :online = 1 OR sa.store_id IS NOT NULL)"]
    if q.get("store"):
        ids = [x for x in q["store"].split(",") if x][:80]
        where.append(f"s.slug IN ({','.join(f':st{i}' for i in range(len(ids)))})")
        args.update({f"st{i}": x for i, x in enumerate(ids)})
    items = rows(f"""
        SELECT p.id, p.name, p.brand, p.unit_text, COALESCE(p.image_url, g.image_url) AS image_url,
               s.slug AS store_slug, s.name AS store_name, si.channel,
               MIN(m.promo_eur) AS promo_eur, COALESCE(m.regular_eur, c.regular, c.price) AS regular, m.discount_pct, m.valid_from,
               m.valid_to, m.requires_loyalty, m.min_quantity, m.label, c.family_id, c.group_id, c.price AS price_now
        FROM promotions m JOIN products p ON p.id = m.product_id JOIN stores s ON s.id = p.store_id
        JOIN store_info si ON si.store_id = s.id
        LEFT JOIN product_current c ON c.product_id = p.id LEFT JOIN product_groups g ON g.id = c.group_id
        LEFT JOIN store_area sa ON sa.store_id = s.id AND sa.area = :area
        WHERE {' AND '.join(where)} AND m.source <> 'glovo_delivery'
        GROUP BY m.product_id                     -- SQLite: bare columns come from the MIN(promo_eur) row
        ORDER BY m.valid_from, COALESCE(m.discount_pct, 0) DESC LIMIT :lim""", args)
    return {"items": items}


def api_shrinkflation(q):
    """Smaller packs whose price per kg/l did not fall (derive.build_shrinkflation), biggest per-kg rise first."""
    limit = _int(q, "limit", 48, 1, 200)
    args = scope(q)
    where = [AVAILABLE]
    if q.get("store"):
        ids = [x for x in q["store"].split(",") if x][:80]
        where.append(f"s.slug IN ({','.join(f':st{i}' for i in range(len(ids)))})")
        args.update({f"st{i}": x for i, x in enumerate(ids)})
    items = rows(f"""SELECT {PRODUCT_COLS}, sh.method AS shrink_method, sh.old_product_id, sh.old_name, sh.old_size,
                            sh.new_size, sh.size_unit AS shrink_unit, sh.old_unit_price, sh.new_unit_price,
                            sh.size_change_pct, sh.unit_change_pct, sh.changed_on
                     {PRODUCT_FROM} JOIN shrinkflation sh ON sh.product_id = c.product_id
                     WHERE {' AND '.join(where)}
                     ORDER BY sh.unit_change_pct DESC, sh.size_change_pct ASC LIMIT :lim""", {**args, "lim": limit})
    return {"items": items}


def _availability(item: dict, args: dict) -> dict:
    """Where a product can be bought: online delivery, the municipalities with a KZP price for it, or (for a
    chain-wide catalogue price) the municipalities where its chain has shops."""
    if item["channel"] == "online":
        return {"type": "online"}
    if item["outlets_total"]:
        places = rows("""SELECT a.code, a.name, pa.outlets, pa.price_min AS min, pa.price_max AS max
                         FROM product_area pa JOIN areas a ON a.code = pa.area WHERE pa.product_id = :id
                         ORDER BY pa.area = :area DESC, pa.outlets DESC, a.outlets DESC""",
                      {"id": item["id"], "area": args["area"]})
        return {"type": "outlets", "areas": places}
    places = rows("""SELECT a.code, a.name, sa.outlets FROM store_area sa JOIN areas a ON a.code = sa.area
                     WHERE sa.store_id = :sid ORDER BY sa.area = :area DESC, sa.outlets DESC""",
                  {"sid": item["store_id"], "area": args["area"]})
    return {"type": "chain", "areas": places}


def _shelf_rows(alias: str) -> str:
    """Price rows to show for product :id: delivery-app prices (Glovo) only stand in when no shelf source prices
    it, as in derive.py -- otherwise today's Glovo row would hide yesterday's KZP outlets."""
    return (f"({alias}.source NOT IN ({DELIVERY}) OR NOT EXISTS (SELECT 1 FROM prices x "
            f"WHERE x.product_id = :id AND x.source NOT IN ({DELIVERY})))")


def api_product(pid: int, q: dict):
    args = {**scope(q), "id": pid}
    found = rows(f"SELECT {PRODUCT_COLS} {PRODUCT_FROM} WHERE p.id = :id", args)
    if not found:
        return {"error": "not found"}, HTTPStatus.NOT_FOUND
    item = found[0]
    item["promotions"] = rows("""SELECT promo_eur, regular_eur, discount_pct, valid_from, valid_to,
                                        requires_loyalty, min_quantity, label, source
                                 FROM promotions WHERE product_id = :id
                                 ORDER BY COALESCE(valid_to, '9999') DESC LIMIT 20""", args)
    item["history"] = rows(f"""SELECT observed_on AS day, MIN(price_eur) AS min, MAX(price_eur) AS max,
                                      MAX(regular_eur) AS regular
                               FROM prices WHERE product_id = :id AND {_shelf_rows("prices")}
                               GROUP BY observed_on ORDER BY observed_on""", args)
    item["availability"] = _availability(item, args)
    # Outlets: in the chosen municipality, else the cheapest anywhere (with their town).
    item["outlets_list"] = rows(f"""
        SELECT o.external_name AS outlet, oa.settlement, pr.price_eur AS price, pr.regular_eur AS regular
        FROM prices pr JOIN outlets o ON o.id = pr.outlet_id LEFT JOIN outlet_area oa ON oa.outlet_id = o.id
        WHERE pr.product_id = :id AND {_shelf_rows("pr")}
              AND pr.observed_on = (SELECT MAX(observed_on) FROM prices
                                    WHERE product_id = :id AND outlet_id IS NOT NULL AND {_shelf_rows("prices")})
              {"AND oa.area = :area" if args["area"] else ""}
        ORDER BY pr.price_eur ASC, o.external_name LIMIT 30""", args)
    item["compare"] = rows(f"""SELECT {PRODUCT_COLS}, m.score, m.method {PRODUCT_FROM}
                               JOIN group_members m ON m.product_id = p.id
                               WHERE c.group_id = :gid ORDER BY available DESC, effective ASC""",
                           {**args, "gid": item["group_id"]})
    return item


def api_family(fid: int, q: dict):
    """A family as a matrix: one row per variant (flavour), one column per chain, cheapest offer per cell. Pack sizes
    may differ within a family (80 g vs 100 g), so each cell carries its price per kg/l; best_unit marks the lowest
    per row and family['best_unit_price'] the lowest of all."""
    args = {**scope(q), "fid": fid}
    fam = rows("SELECT * FROM product_families WHERE id = :fid", args)
    if not fam:
        return {"error": "not found"}, HTTPStatus.NOT_FOUND
    members = rows(f"SELECT {PRODUCT_COLS} {PRODUCT_FROM} WHERE c.family_id = :fid ORDER BY effective", args)
    stores, variants = {}, {}
    for m in members:
        st = stores.setdefault(m["store_slug"], {"slug": m["store_slug"], "name": m["store_name"],
                                                 "channel": m["channel"], "area_names": m["store_area_names"],
                                                 "area_outlets": m["store_area_outlets"], "min": None,
                                                 "available": False, "variants": 0, "min_unit": None})
        if m["available"]:
            st["available"] = True
            # The header's price per kg/l is the cheapest offer's own, not the lowest of another pack.
            if st["min"] is None or m["effective"] < st["min"]:
                st["min"], st["min_unit"] = m["effective"], m.get("unit_price") or m.get("piece_price")
        row = variants.setdefault(m["variant_row"] or 1, {"row": m["variant_row"] or 1, "label": m["variant"],
                                                          "name": m["name"], "image_url": m["image_url"],
                                                          "cells": {}, "min": None})
        cell = row["cells"].get(m["store_slug"])
        better = cell is None or (m["available"], -m["effective"]) > (cell["available"], -cell["effective"])
        if better:
            if cell is None:
                st["variants"] += 1
            row["cells"][m["store_slug"]] = {k: m.get(k) for k in (
                "id", "name", "unit_text", "effective", "regular", "promo_eur", "card_eur", "with_card", "discount_pct",
                "available", "min_quantity", "outlets", "unit_price", "unit_per", "piece_price", "size_g", "fake_promo",
                "real_discount_pct")}
        if m["available"]:
            row["min"] = m["effective"] if row["min"] is None else min(row["min"], m["effective"])
        row["image_url"] = row["image_url"] or m["image_url"]
    # Price per kg/l, or per piece for count packs ('10 бр.' capsules): what to compare when pack sizes differ.
    def unit(c):
        return c.get("unit_price") or c.get("piece_price")
    best_unit = None
    for row in variants.values():
        units = [unit(c) for c in row["cells"].values() if c["available"] and unit(c)]
        row["min_unit"] = min(units) if units else None
        for c in row["cells"].values():
            c["best_unit"] = bool(row["min_unit"] and c["available"] and unit(c) == row["min_unit"] and len(units) > 1)
        if row["min_unit"] and (best_unit is None or row["min_unit"] < best_unit):
            best_unit = row["min_unit"]
    cols = sorted(stores.values(), key=lambda s: (not s["available"], s["min"] if s["min"] is not None else 1e9))
    rows_ = sorted(variants.values(), key=lambda r: (-sum(c["available"] for c in r["cells"].values()),
                                                     r["min"] if r["min"] is not None else 1e9))
    unit_per = next((m["unit_per"] for m in members if m.get("unit_per")), None) or (
        "pc" if any(m.get("piece_price") for m in members) else None)
    return {"family": {**fam[0], "best_unit_price": best_unit, "unit_per": unit_per}, "stores": cols,
            "variants": rows_, "area": args["area"], "cards": args["cards"].strip(",").split(",") if args["cards"] else []}


BASKET_CANDIDATES = 14         # chains considered for multi-store plans (combinations grow fast)


def _basket_item(i: dict) -> tuple:
    """One request line -> (key, product_id, group_id, family_id, substitute, qty). key identifies the line in the
    response: the product id, else 'group:<id>' / 'family:<id>'."""
    def ident(k):
        v = i.get(k)
        if v in (None, ""):
            return None
        v = int(v)
        if not 0 < v < 2**53:
            raise ValueError(f"bad {k}")
        return v
    pid, gid, fid = ident("product_id"), ident("group_id"), ident("family_id")
    if not (pid or gid or fid):
        raise ValueError("each item needs product_id, group_id or family_id")
    qty = min(999, max(1, int(i.get("qty", 1))))
    sub = str(i.get("allow_family_substitute", "")).lower() in ("1", "true")
    return (pid or (f"group:{gid}" if gid else f"family:{fid}")), pid, gid, fid, sub, qty


def _line_offers(pid, gid, fid, sub, qty, args) -> tuple[str | None, list[dict]]:
    """(name, offers) for one basket line: one offer per chain, its cheapest. The exact product (its cross-chain group)
    comes first; with a family (family_id, or allow_family_substitute) a chain without it offers a sibling -- the same
    flavour in another pack before another flavour -- marked substitute."""
    want_row = None
    if pid:
        found = db().execute("SELECT group_id, family_id, variant_row FROM product_current WHERE product_id = ?",
                             (pid,)).fetchone()
        if not found:
            return None, []
        gid, fam_of, want_row = found
        fid = fid or (fam_of if sub else None)
    exact = []
    if pid or gid:
        exact = rows(f"""SELECT {PRODUCT_COLS} {PRODUCT_FROM}
                         WHERE (c.group_id = :gid OR (:gid IS NULL AND c.product_id = :pid)) AND {AVAILABLE}""",
                     {**args, "gid": gid, "pid": pid})
    family = rows(f"SELECT {PRODUCT_COLS} {PRODUCT_FROM} WHERE c.family_id = :fid AND {AVAILABLE}",
                  {**args, "fid": fid}) if fid else []
    exact_ids = {o["id"] for o in exact}
    offers = [dict(o, substitute=False) for o in exact]
    offers += [dict(o, substitute=bool(pid or gid)) for o in family if o["id"] not in exact_ids]
    for o in offers:
        if o["min_quantity"] and o["min_quantity"] > qty and o["promo_eur"] and not o["with_card"]:
            o["effective"] = o["price_min"]       # a multibuy promo only applies when the quantity reaches it
    offers.sort(key=lambda o: (o["substitute"], o["variant_row"] != want_row if o["substitute"] else 0, o["effective"]))
    best: dict[str, dict] = {}
    for o in offers:                  # sorted by preference: one per chain, exact first, else the closest sibling
        best.setdefault(o["store_slug"], o)
    chosen = sorted(best.values(), key=lambda o: o["effective"])
    name = (exact[0]["name"] if exact else (family[0]["family_name"] if family else None))
    if pid and exact:
        name = next((o["name"] for o in exact if o["id"] == pid), name)
    return name, chosen


def _plans(sellable: list[dict], max_stores: int, min_savings: float) -> tuple[dict | None, list[dict]]:
    """Best basket per number of chains (1..max_stores) and the one to recommend: more lines covered always wins;
    otherwise each extra chain must save at least min_savings (a trip to another shop has a cost)."""
    cost: dict[str, dict] = {}
    for i, l in enumerate(sellable):
        for o in l["offers"]:
            cost.setdefault(o["store"], {})[i] = o
    n = len(sellable)
    # Candidates: the best-covering chains plus each line's cheapest chain.
    ranked = sorted(cost, key=lambda st: (-len(cost[st]), sum(o["total"] for o in cost[st].values())))
    cands = list(dict.fromkeys(ranked[:BASKET_CANDIDATES // 2]
                               + [l["offers"][0]["store"] for l in sellable] + ranked))[:BASKET_CANDIDATES]
    best_k = []
    for k in range(1, max_stores + 1):
        best = None
        for combo in itertools.combinations(cands, k):
            picks, used = {}, set()
            for i in range(n):
                o = min((cost[st][i] for st in combo if i in cost[st]), key=lambda o: o["total"], default=None)
                if o:
                    picks[i] = o
                    used.add(o["store"])
            if len(used) < k:
                continue                      # a chain that wins no line adds a trip for nothing
            key = (-len(picks), round(sum(o["total"] for o in picks.values()), 2))
            if best is None or key < best[0]:
                best = (key, combo, picks)
        if best:
            (neg_cov, total), combo, picks = best
            best_k.append({"stores": sorted(combo), "trips": k, "total": total, "covers": -neg_cov,
                           "missing": [sellable[i]["product_id"] for i in range(n) if i not in picks],
                           "items": [{**picks[i], "product_id": sellable[i]["product_id"], "qty": sellable[i]["qty"],
                                      "offer_product_id": picks[i]["product_id"]} for i in sorted(picks)]})
    if not best_k:
        return None, []
    plan = best_k[0]
    for p in best_k[1:]:
        if p["covers"] > plan["covers"] or (
                p["covers"] == plan["covers"] and plan["total"] - p["total"] >= min_savings * (p["trips"] - plan["trips"])):
            plan = p
    one = best_k[0]
    plan = {**plan, "savings_vs_one_store": round(one["total"] - plan["total"], 2) if one["covers"] == plan["covers"]
            else None}
    return plan, [{k: v for k, v in p.items() if k != "items"} for p in best_k]


def api_basket(body: dict):
    """Cheapest way to buy a list, limited to what is sold in the chosen municipality (+ online chains):
      single_store    chains that stock every line, cheapest first
      split           the cheapest offer for every line, however many chains that takes
      plan            the recommended trip: at most max_stores chains (default 2), an extra chain only when it saves
                      at least min_savings_per_store (default 2.50 €); plans = the best plan per number of chains
    A line is a product_id (its cross-chain group), a group_id or a family_id (any variant); allow_family_substitute
    lets a chain without the exact product offer a sibling (marked substitute). cards: chains whose loyalty-card
    prices count ('*' = all)."""
    items = body.get("items", [])
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError("items must be a list of objects")
    want = [_basket_item(i) for i in items][:60]
    if not want:
        return {"error": "items required"}, HTTPStatus.BAD_REQUEST
    args = scope(body)
    max_stores = _int(body, "max_stores", 2, 1, 4)
    try:
        min_savings = max(0.0, min(1000.0, float(body.get("min_savings_per_store", 2.5))))
    except (TypeError, ValueError):
        raise ValueError("min_savings_per_store must be a number")
    lines, per_store = [], {}
    for key, pid, gid, fid, sub, qty in want:
        name, offers = _line_offers(pid, gid, fid, sub, qty, args)
        lines.append({"product_id": key, "qty": qty, "name": name, "offers": [
            {"store": o["store_slug"], "store_name": o["store_name"], "product_id": o["id"], "name": o["name"],
             "channel": o["channel"], "unit": o["effective"], "total": round(o["effective"] * qty, 2),
             "substitute": o["substitute"], "with_card": bool(o.get("with_card"))}
            for o in offers]})
        for o in offers:
            per_store.setdefault(o["store_slug"], {"store": o["store_slug"], "store_name": o["store_name"],
                                                   "channel": o["channel"], "total": 0.0, "items": 0,
                                                   "substitutes": 0})
            per_store[o["store_slug"]]["total"] += round(o["effective"] * qty, 2)
            per_store[o["store_slug"]]["items"] += 1
            per_store[o["store_slug"]]["substitutes"] += o["substitute"]
    sellable = [l for l in lines if l["offers"]]
    n = len(sellable)
    complete = sorted((dict(v, total=round(v["total"], 2)) for v in per_store.values() if v["items"] == n),
                      key=lambda v: v["total"])
    partial = sorted((dict(v, total=round(v["total"], 2)) for v in per_store.values() if v["items"] < n),
                     key=lambda v: (-v["items"], v["total"]))[:8]
    # product_id stays the requested one (the client maps lines by it); offer_product_id is what to buy.
    split = [{**l["offers"][0], "offer_product_id": l["offers"][0]["product_id"], "product_id": l["product_id"],
              "qty": l["qty"]} for l in sellable]
    plan, plans = _plans(sellable, max_stores, min_savings)
    return {"lines": lines, "single_store": complete[:10], "partial_stores": partial,
            "unavailable": [l["product_id"] for l in lines if not l["offers"]],
            "split": {"total": round(sum(x["total"] for x in split), 2), "items": split,
                      "stores": sorted({x["store"] for x in split})},
            "plan": plan, "plans": plans, "max_stores": max_stores, "min_savings_per_store": min_savings,
            "cards": args["cards"].strip(",").split(",") if args["cards"] else []}


# --------------------------------------------------------------------------- HTTP plumbing

class Handler(BaseHTTPRequestHandler):
    server_version = "PazarClone/0.1"

    def handle(self):
        try:
            super().handle()
        finally:
            release_db()

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes, ctype: str, cache: str = "no-store"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, result):
        status = HTTPStatus.OK
        if isinstance(result, tuple):
            result, status = result
        self._send(status, json.dumps(result, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            routes = {"/api/stats": api_stats, "/api/stores": api_stores, "/api/areas": api_areas,
                      "/api/search": api_search, "/api/deals": api_deals, "/api/drops": api_drops,
                      "/api/upcoming": api_upcoming, "/api/shrinkflation": api_shrinkflation}
            if url.path in routes:
                return self._json(routes[url.path](q))
            m = re.fullmatch(r"/api/(product|family)/(\d{1,12})", url.path)
            if m:
                return self._json((api_product if m.group(1) == "product" else api_family)(int(m.group(2)), q))
            if url.path.startswith("/api/"):
                return self._json(({"error": "not found"}, HTTPStatus.NOT_FOUND))
            return self._static(url.path)
        except (ValueError, OverflowError, sqlite3.OperationalError) as e:
            log.warning("bad request %s: %s", self.path, e)
            return self._json(({"error": str(e)}, HTTPStatus.BAD_REQUEST))
        except Exception:
            log.exception("GET %s failed", self.path)
            return self._json(({"error": "internal error"}, HTTPStatus.INTERNAL_SERVER_ERROR))

    def do_POST(self):
        if self.path != "/api/basket":
            return self._json(({"error": "not found"}, HTTPStatus.NOT_FOUND))
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 100_000)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            return self._json(api_basket(body))
        except (ValueError, OverflowError, KeyError, TypeError) as e:
            return self._json(({"error": str(e)}, HTTPStatus.BAD_REQUEST))
        except Exception:
            log.exception("POST %s failed", self.path)
            return self._json(({"error": "internal error"}, HTTPStatus.INTERNAL_SERVER_ERROR))

    def _static(self, path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents or not target.is_file():
            target = WEB_DIR / "index.html"          # SPA fallback
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(HTTPStatus.OK, target.read_bytes(), ctype, "no-cache")


def main(argv=None):
    global DB_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="prices.db")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args(argv)
    DB_PATH = a.db
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    with ThreadingHTTPServer((a.host, a.port), Handler) as srv:
        log.info("serving http://%s:%d (db=%s)", a.host, a.port, a.db)
        srv.serve_forever()


if __name__ == "__main__":
    main()
