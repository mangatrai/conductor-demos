import json, os, subprocess, sys, uuid

def fail(msg):
    print("FAIL: " + msg.replace("\n", " ")[:300])
    sys.exit(1)

root = os.path.join(os.getcwd(), "convo-agent")
data_path = os.path.join(root, "v5", "data", "portfolios.json")
if not os.path.isfile(data_path):
    fail("v5/data/portfolios.json missing")
data = json.load(open(data_path))

def find_jane(o):
    if isinstance(o, dict):
        if any(isinstance(v, str) and v.lower() == "jane doe" for v in o.values()):
            return o
        for k, v in o.items():
            if k.lower() == "jane doe":
                return v
            r = find_jane(v)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_jane(v)
            if r is not None:
                return r
    return None

jane = find_jane(data)
if jane is None:
    fail("Jane Doe not in portfolios.json")

def holding_names(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and k.lower() in ("symbol", "ticker", "name", "asset", "security", "fund") \
                    and v.lower() != "jane doe":
                out.add(v)
            holding_names(v, out)
    elif isinstance(o, list):
        for v in o:
            holding_names(v, out)
    return out

names = {n for n in holding_names(jane, set()) if len(n) >= 2}
if not names:
    fail("no Jane Doe holdings found in portfolios.json")

try:
    p = subprocess.run(
        [sys.executable, "-m", "v5.chat", "--session", "P-" + uuid.uuid4().hex[:8],
         "What's in Jane Doe's portfolio?"],
        cwd=root, capture_output=True, text=True, timeout=240)
except FileNotFoundError:
    fail("convo-agent directory missing")
except subprocess.TimeoutExpired:
    fail("v5.chat did not finish within 240s")
if p.returncode != 0:
    fail("v5.chat exit %d: %s" % (p.returncode, (p.stderr or p.stdout)[-200:]))

out = p.stdout
res = None
dec = json.JSONDecoder()
for i, ch in enumerate(out):
    if ch == "{":
        try:
            o, _ = dec.raw_decode(out[i:])
        except ValueError:
            continue
        if isinstance(o, dict) and "reply" in o:
            res = o
            break
if res is None:
    fail("no JSON with reply in output")

reply = str(res.get("reply", "")).lower()
if not any(n.lower() in reply for n in names):
    fail("reply names no Jane Doe holding")
tc = res.get("toolCalls")
if "get_portfolio" not in json.dumps(tc):
    fail("toolCalls lacks get_portfolio")
print("OK")
