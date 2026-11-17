// Shared helpers for the three demo pages.
async function api(path, opts = {}) {
  const init = { headers: { "Content-Type": "application/json" }, ...opts };
  if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
  const r = await fetch(path, init);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!r.ok) throw new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : `HTTP ${r.status}`);
  return data;
}

const money = (v) => (v === null || v === undefined || v === "") ? "—" :
  Number(v).toLocaleString("en-US", { style: "currency", currency: "USD" });

const fmtDate = (s) => s ? new Date(s.length === 10 ? s + "T12:00:00" : s)
  .toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";

const fmtTime = (s) => s ? new Date(s).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" }) : "";

function timeAgo(s) {
  if (!s) return "";
  const sec = Math.max(0, Math.round((Date.now() - new Date(s).getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function countdown(s) {
  if (!s) return "";
  const sec = Math.round((new Date(s).getTime() - Date.now()) / 1000);
  if (sec <= 0) return "deadline passed";
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")} left`;
}

// Tailwind classes for case stages
const STAGE_STYLE = {
  RESOLVED: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  PENDING_REVIEW: "bg-violet-100 text-violet-800 ring-violet-600/20",
  AWAITING_MERCHANT: "bg-sky-100 text-sky-800 ring-sky-600/20",
  AWAITING_CARDHOLDER: "bg-amber-100 text-amber-900 ring-amber-600/30",
  RETRYING: "bg-orange-100 text-orange-800 ring-orange-600/20",
  ERROR: "bg-rose-600 text-white ring-rose-700",
  OPS_EXCEPTION: "bg-fuchsia-100 text-fuchsia-800 ring-fuchsia-600/20",
  CANCELLED: "bg-slate-100 text-slate-600 ring-slate-500/20",
};
const OUTCOME_STYLE = { REJECT: "bg-rose-100 text-rose-800 ring-rose-600/20", PARTIAL: "bg-amber-100 text-amber-900 ring-amber-600/30" };
const stageClass = (st, decision) => "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset " +
  ((st === "RESOLVED" && OUTCOME_STYLE[decision]) || STAGE_STYLE[st] || "bg-slate-100 text-slate-700 ring-slate-500/20");

const DECISION_STYLE = {
  APPROVE: "text-emerald-700", PARTIAL: "text-amber-700", REJECT: "text-rose-700",
};

const EVENT_DOT = {
  done: "bg-slate-400", warn: "bg-orange-500", wait: "bg-sky-500 animate-pulse",
  action: "bg-amber-500 animate-pulse", final: "bg-emerald-500", error: "bg-rose-600",
};

const CATEGORY_LABEL = {
  DIGITAL: "Digital", ELECTRONICS: "Electronics", GROCERY: "Grocery", DINING: "Dining", FUEL: "Fuel",
  RETAIL: "Retail", MEMBERSHIP: "Membership", CONTRACTOR: "Contractor", HOME_SERVICES: "Home services",
  PERSONAL_SERVICES: "Personal services", REPAIR: "Repair", PROFESSIONAL_SERVICES: "Professional services",
  TRAVEL: "Travel", TRANSPORT: "Transport",
};

// Staff-facing wording for timeline events written from the cardholder's point of view
const staff = (s) => (s || "")
  .replace("Waiting for your answer", "Waiting for cardholder's answer")
  .replace("You answered", "Cardholder answered")
  .replace("Posted to your account", "Posted to cardholder's account")
  .replace("Reviewing your claim", "Reviewing the claim");
