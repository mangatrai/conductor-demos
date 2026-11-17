"""Generate deterministic synthetic data: 4 cardholder personas, ~40 transactions each.

Dates are relative to today so the dispute window logic always works.
Merchants are fictional; MCC codes are real.

    python -m bank.seed        (from dispute_demo/)  -- wipes and recreates bank.db
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from bank.db import DB_PATH, connect, init_schema

# id, name, mcc, mcc description, category, city, sim behaviour, evidence if it contests
MERCHANTS = [
    ("M-STREAM", "StreamMax", "4899", "Cable & streaming services", "DIGITAL", "Online", "auto_accept", None),
    ("M-TUNE", "TuneWave Music", "5815", "Digital media", "DIGITAL", "Online", "auto_accept", None),
    ("M-CLOUD", "CloudVault Storage", "5817", "Digital software", "DIGITAL", "Online", "auto_accept", None),
    ("M-VOLT", "VoltCity Electronics", "5732", "Electronics stores", "ELECTRONICS", "Austin, TX", "contest",
     "Carrier scan shows package delivered to front door; tracking 1Z84A0..."),
    ("M-GADGET", "GadgetHub Online", "5964", "Catalog merchant", "ELECTRONICS", "Online", "silent", None),
    ("M-FRESH", "FreshCart Grocery", "5411", "Grocery stores", "GROCERY", "Austin, TX", "auto_accept", None),
    ("M-BEAN", "Corner Bean Coffee", "5814", "Fast food & coffee", "DINING", "Austin, TX", "auto_accept", None),
    ("M-BELLA", "Bella Notte Trattoria", "5812", "Restaurants", "DINING", "Austin, TX", "contest",
     "Itemized receipt signed by cardholder, table 12."),
    ("M-FUEL", "QuickFuel", "5541", "Service stations", "FUEL", "Austin, TX", "auto_accept", None),
    ("M-THREADS", "UrbanThreads Apparel", "5651", "Clothing stores", "RETAIL", "Online", "contest",
     "Return window expired; item shipped and delivered."),
    ("M-NEST", "HomeNest Furniture", "5712", "Furniture stores", "RETAIL", "Round Rock, TX", "contest",
     "Delivery receipt signed; custom order non-refundable per terms."),
    ("M-BOOKS", "PageTurner Books", "5942", "Book stores", "RETAIL", "Austin, TX", "auto_accept", None),
    ("M-PET", "PetPal Supplies", "5995", "Pet shops", "RETAIL", "Austin, TX", "auto_accept", None),
    ("M-GYM", "FitLife Gym", "7997", "Membership clubs", "MEMBERSHIP", "Austin, TX", "silent", None),
    ("M-ACE", "Ace Rapid Plumbing", "1711", "Plumbing & HVAC contractors", "CONTRACTOR", "Austin, TX", "contest",
     "Technician on site 2.5 hrs; invoice #4471 signed by customer."),
    ("M-SPARK", "BrightSpark Electric", "1731", "Electrical contractors", "CONTRACTOR", "Austin, TX", "contest",
     "Permit pulled and inspection passed; photos attached."),
    ("M-LEAF", "GreenLeaf Landscaping", "0780", "Landscaping services", "HOME_SERVICES", "Austin, TX", "auto_accept", None),
    ("M-MAID", "SparkleClean Maids", "7349", "Cleaning services", "HOME_SERVICES", "Austin, TX", "silent", None),
    ("M-SALON", "Shear Elegance Salon", "7230", "Beauty & barber shops", "PERSONAL_SERVICES", "Austin, TX", "manual",
     "Service completed; customer signed off at checkout."),
    ("M-FIXIT", "FixIt Phone Repair", "7622", "Electronics repair", "REPAIR", "Austin, TX", "contest",
     "Screen replaced; 30-day warranty offered, customer declined."),
    ("M-LEGAL", "Harper & Cole Legal", "8111", "Legal services", "PROFESSIONAL_SERVICES", "Austin, TX", "contest",
     "Engagement letter signed; 4 billable hours logged."),
    ("M-SKY", "SkyBridge Airlines", "4511", "Airlines", "TRAVEL", "Online", "contest",
     "Fare is non-refundable; passenger checked in."),
    ("M-HARBOR", "Harborview Hotel", "7011", "Hotels & lodging", "TRAVEL", "San Diego, CA", "auto_accept", None),
    ("M-ROAD", "RoadRunner Car Rental", "7512", "Car rental", "TRAVEL", "San Diego, CA", "contest",
     "Fuel surcharge per rental agreement section 7."),
    ("M-METRO", "MetroRide", "4121", "Taxis & rideshare", "TRANSPORT", "Online", "auto_accept", None),
]

CARDHOLDERS = [
    ("CH-1001", "Priya Shah", "priya.shah@example.com", "4821", "everyday"),
    ("CH-1002", "Marcus Johnson", "marcus.j@example.com", "7710", "homeowner"),
    ("CH-1003", "Elena Rossi", "elena.rossi@example.com", "3398", "traveler"),
    ("CH-1004", "Jordan Lee", "jordan.lee@example.com", "5562", "repeat_disputer"),
]

# Everyday filler: merchant, (min, max) amount, how many per ~100 days
FILLER = {
    "everyday": [("M-FRESH", (38, 160), 12), ("M-BEAN", (4.5, 9), 10), ("M-FUEL", (32, 61), 6),
                 ("M-METRO", (11, 34), 5), ("M-BOOKS", (12, 45), 2), ("M-PET", (18, 70), 2)],
    "homeowner": [("M-FRESH", (55, 210), 12), ("M-FUEL", (40, 75), 8), ("M-BEAN", (4.5, 8), 6),
                  ("M-PET", (25, 90), 3), ("M-BELLA", (60, 140), 3)],
    "traveler": [("M-FRESH", (30, 110), 8), ("M-METRO", (14, 48), 10), ("M-BEAN", (5, 11), 8),
                 ("M-BELLA", (70, 190), 4), ("M-BOOKS", (10, 30), 2)],
    "repeat_disputer": [("M-FRESH", (25, 95), 10), ("M-BEAN", (4.5, 8), 9), ("M-METRO", (9, 29), 8),
                        ("M-FUEL", (28, 55), 5)],
}

MONTHLY = {  # subscriptions billed monthly
    "everyday": [("M-TUNE", 10.99), ("M-CLOUD", 2.99)],
    "homeowner": [("M-STREAM", 15.99), ("M-CLOUD", 9.99)],
    "traveler": [("M-TUNE", 10.99), ("M-STREAM", 15.99)],
    "repeat_disputer": [("M-GYM", 39.99), ("M-TUNE", 10.99)],
}

# Hand-placed charges that drive the demo scenarios: (merchant, amount, days ago, description)
SCRIPTED = {
    "everyday": [
        ("M-STREAM", 15.99, 9, "StreamMax Premium monthly"),        # cancelled -> auto-approve
        ("M-VOLT", 649.00, 19, "VoltCity 65in 4K TV"),               # not received -> review; the console's outage targets it
        ("M-ACE", 85.00, 12, "Ace Rapid Plumbing service call"),     # work not done -> labor category
        ("M-SALON", 64.00, 26, "Shear Elegance cut & color"),
        ("M-SKY", 389.40, 85, "SkyBridge AUS-SEA"),                  # outside the dispute window
    ],
    "homeowner": [
        ("M-ACE", 240.00, 8, "Ace Rapid Plumbing water heater"),
        ("M-SPARK", 380.00, 22, "BrightSpark panel upgrade deposit"),
        ("M-LEAF", 65.00, 15, "GreenLeaf monthly lawn care"),
        ("M-MAID", 120.00, 6, "SparkleClean deep clean"),
        ("M-NEST", 1250.00, 33, "HomeNest sectional sofa"),
        ("M-FIXIT", 89.00, 40, "FixIt screen replacement"),
        ("M-LEGAL", 450.00, 90, "Harper & Cole consultation"),       # outside window
    ],
    "traveler": [
        ("M-SKY", 412.80, 18, "SkyBridge AUS-JFK round trip"),
        ("M-HARBOR", 289.00, 14, "Harborview Hotel 2 nights"),
        ("M-HARBOR", 289.00, 14, "Harborview Hotel 2 nights"),      # duplicate charge
        ("M-ROAD", 176.25, 13, "RoadRunner 3-day rental"),
        ("M-ROAD", 42.00, 11, "RoadRunner fuel surcharge"),
        ("M-METRO", 24.60, 5, "MetroRide airport trip"),
        ("M-BELLA", 96.40, 88, "Bella Notte dinner"),               # outside window
    ],
    "repeat_disputer": [
        ("M-GADGET", 49.99, 7, "GadgetHub wireless earbuds"),
        ("M-THREADS", 79.00, 16, "UrbanThreads jacket"),
        ("M-GADGET", 24.99, 21, "GadgetHub phone case"),
        ("M-SALON", 45.00, 10, "Shear Elegance haircut"),
        ("M-THREADS", 119.00, 87, "UrbanThreads boots"),             # outside window
    ],
}

# Jordan's history of earlier disputes (makes him a repeat disputer): (days ago, merchant, amount, decision)
HISTORY = {
    "CH-1004": [(15, "M-GADGET", 34.99, "APPROVE"), (33, "M-THREADS", 59.00, "REJECT"),
                (51, "M-GYM", 39.99, "APPROVE"), (70, "M-GADGET", 19.99, "APPROVE")],
    "CH-1003": [(160, "M-SKY", 120.00, "APPROVE")],
}


def statement_date_for(posted: date, today: date) -> str | None:
    """Statements close on the 5th. Returns None if the charge is still in the open cycle."""
    if posted.day <= 5:
        stmt = posted.replace(day=5)
    else:
        y, m = (posted.year + 1, 1) if posted.month == 12 else (posted.year, posted.month + 1)
        stmt = date(y, m, 5)
    return stmt.isoformat() if stmt <= today else None


def seed() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        p = DB_PATH.with_name(DB_PATH.name + suffix)
        if p.exists():
            p.unlink()

    rnd = random.Random(42)
    today = date.today()
    now = datetime.now(timezone.utc)
    with connect() as c:
        init_schema(c)
        c.executemany("INSERT INTO merchants VALUES (?,?,?,?,?,?,?,?)", MERCHANTS)
        c.executemany(
            "INSERT INTO cardholders VALUES (?,?,?,?,'ACTIVE',?,?)",
            [(cid, n, e, l4, rnd.choice([8000, 12000, 15000, 20000]), p) for cid, n, e, l4, p in CARDHOLDERS],
        )
        merchant_desc = {m[0]: m[1] for m in MERCHANTS}
        txn_no = 50000
        for cid, _, _, _, persona in CARDHOLDERS:
            txns = []
            for mid, (lo, hi), count in FILLER[persona]:
                for _ in range(count):
                    txns.append((mid, round(rnd.uniform(lo, hi), 2), rnd.randint(1, 98), merchant_desc[mid]))
            for mid, amt in MONTHLY[persona]:
                for days_ago in (3, 33, 63, 93):
                    txns.append((mid, amt, days_ago, f"{merchant_desc[mid]} subscription"))
            txns.extend(SCRIPTED[persona])
            txns.sort(key=lambda t: -t[2])
            for mid, amt, days_ago, desc in txns:
                txn_no += rnd.randint(1, 9)
                posted = today - timedelta(days=days_ago)
                c.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?)",
                          (f"T-{txn_no}", cid, mid, amt, posted.isoformat(),
                           statement_date_for(posted, today), desc))
        # historical closed cases (no workflow) for dispute-history rules
        for cid, hist in HISTORY.items():
            for i, (days_ago, mid, amt, decision) in enumerate(hist, start=1):
                opened = (now - timedelta(days=days_ago)).replace(microsecond=0)
                c.execute("""INSERT INTO cases(id,dispute_id,cardholder_id,txn_id,reason_code,amount,
                             opened_at,closed_at,decision,approved_amount,decided_by,historical)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,1)""",
                          (f"HIST-{cid[-4:]}-{i}", f"HIST-{cid[-4:]}", cid, None, "NOT_RECEIVED", amt,
                           opened.isoformat(), (opened + timedelta(days=9)).isoformat(), decision,
                           amt if decision == "APPROVE" else 0, "ANALYST"))
        c.execute("INSERT INTO settings VALUES ('network_outage','off')")
        counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("cardholders", "merchants", "transactions", "cases")}
    print(f"Seeded {DB_PATH}: {counts}")


if __name__ == "__main__":
    seed()
