/* The Opportunity Tracker — static dashboard. Reads data/opportunities.json, keeps personal state in localStorage. */
(function () {
  "use strict";

  const DAY = 86400000;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const SEASON = [8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7]; // Aug → Jul
  const STAGES = [
    { id: "saved", label: "Saved" },
    { id: "applied", label: "Applied" },
    { id: "interview", label: "Interview / Round 2" },
    { id: "result", label: "Result" },
  ];
  const KIND = {
    summer_research: { label: "Summer research", bg: "peri" },
    summer_school: { label: "Summer school", bg: "sand" },
    hackathon: { label: "Hackathon", bg: "coral" },
    challenge: { label: "Innovation", bg: "lime" },
    business_comp: { label: "Business", bg: "yellow" },
    underclassmen: { label: "Year 1–2 program", bg: "peri" },
    insight: { label: "Insight program", bg: "yellow" },
    open_source: { label: "Open source", bg: "lime" },
    scholarship: { label: "Scholarship", bg: "lime" },
    travel_grant: { label: "Travel grant", bg: "coral" },
    contest: { label: "Contest", bg: "peri" },
    internship: { label: "Internship", bg: "sand" },
  };
  const REGION_BG = { asia: "coral", europe: "peri", north_america: "lime", middle_east: "yellow", global: "sand" };
  const REGION_LABEL = { asia: "Asia", europe: "Europe", north_america: "North America", middle_east: "Middle East", global: "Global" };
  const ELIG_LABEL = { eligible: "VN ✓ Eligible", likely: "Likely", check: "Check rules", not_eligible: "Not eligible", ignore: "Ignored" };
  const FUND_LABEL = { fully_funded: "Fully funded", stipend: "Stipend", travel_covered: "Travel covered", free: "Free to enter", fee_required: "Fee" };
  const COMPETE = ["hackathon", "challenge", "business_comp", "contest"];
  const SUMMER = ["summer_research", "summer_school", "scholarship", "travel_grant"];
  const TECH = ["insight", "open_source", "underclassmen", "internship"];

  // ------------------------------------------------------------ persistent personal state
  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem("ot:" + key); return v === null ? fallback : JSON.parse(v); }
      catch (e) { return fallback; }
    },
    set(key, value) { try { localStorage.setItem("ot:" + key, JSON.stringify(value)); } catch (e) { /* private mode */ } },
  };

  const state = {
    data: null,
    eligibleOnly: store.get("eligibleOnly", true),
    year: store.get("year", "profile"),
    tracker: store.get("tracker", {}),      // id -> { stage, note, at }
    decisions: store.get("decisions", {}),  // id -> eligible | not_eligible | ignore
    suggestions: store.get("suggestions", {}),  // id -> accept | dismiss (Claude's proposals)
    verified: store.get("verified", {}),  // id -> { nationality_ok, enrollment_req, class_years, deadline, at } checked by you
    allHackathons: store.get("allHackathons", false),  // include non-featured Devpost hackathons in Review
    items: [],  // the data's items with your local verifications laid over them
    query: "",  // the search box
    ui: { summerFunded: false, summerRegion: "all", competeType: "all", featuredOnly: true, onlineOnly: false, inVietnam: false },
    limits: {},   // list key -> how many items are shown ("Show more")
    groupOpen: {},  // Review group -> open/closed
    layout: store.get("layout", null),  // "cards" | "list"; default depends on screen width
  };
  const PAGE = 12;
  const REVIEW_PAGE = 10;
  function layout() {
    if (state.layout) return state.layout;
    return window.matchMedia && window.matchMedia("(max-width: 640px)").matches ? "list" : "cards";
  }

  // ------------------------------------------------------------ helpers
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const pad = (n) => String(n).padStart(2, "0");

  function nowICT() { return new Date(Date.now() + 7 * 3600000); }
  function thisMonth() { return nowICT().getUTCMonth() + 1; }

  function daysLeft(item) {
    if (!item.deadline) return null;
    const end = Date.parse(item.deadline + "T23:59:00+07:00");
    if (isNaN(end)) return null;
    return Math.ceil((end - Date.now()) / DAY);
  }

  function nextWindowMonth(item) {
    const w = item.window || [];
    if (!w.length) return null;
    const m = thisMonth();
    for (let i = 0; i < 12; i++) { const c = ((m - 1 + i) % 12) + 1; if (w.includes(c)) return c; }
    return null;
  }

  // Your local verification of a curated program, laid over the published data.
  function rebuild() {
    state.items = state.data.items.map((i) => {
      const v = state.verified[i.id];
      if (!v) return i;
      return Object.assign({}, i, {
        nationality_ok: v.nationality_ok, enrollment_req: v.enrollment_req, class_years: v.class_years,
        deadline: v.deadline || null, deadline_confirmed: !!v.deadline, verified: true, verified_local: true,
      });
    });
  }

  // The same rules as tracker/eligibility.py, for programs you verified on this device.
  function localLabel(item) {
    if (["us_canada_only", "host_university_only", "local_only"].includes(item.enrollment_req)) return "not_eligible";
    if (["us_only", "eu_only"].includes(item.nationality_ok)) return "not_eligible";
    if (["other_restriction", "unknown"].includes(item.nationality_ok) || item.enrollment_req === "unknown") return "check";
    const y = state.data && state.data.profile && state.data.profile.year;
    if (y && item.class_years && item.class_years.length && !item.class_years.includes(y)) return "check";
    return "eligible";
  }

  function label(item) {
    if (state.decisions[item.id]) return state.decisions[item.id];
    if (item.verified_local) return localLabel(item);
    return item.eligible_for_me;
  }

  function profileYear() {
    if (state.year === "all") return null;
    if (state.year === "profile") return (state.data && state.data.profile && state.data.profile.year) || null;
    return Number(state.year);
  }

  function isVisible(item) {
    const l = label(item);
    if (l === "ignore") return false;
    if (state.eligibleOnly && l === "not_eligible") return false;
    const y = profileYear();
    if (y && state.eligibleOnly && item.class_years && item.class_years.length && !item.class_years.includes(y)) return false;
    return true;
  }

  function hiddenReason(item) {
    const l = label(item);
    if (l === "not_eligible") return (item.elig_reasons && item.elig_reasons[0]) || "Not open to students in Vietnam";
    const y = profileYear();
    if (y && item.class_years && !item.class_years.includes(y)) return "Not for year " + y;
    return "";
  }

  function items(kinds) {
    return state.items.filter((i) => !kinds || kinds.includes(i.kind));
  }

  function bySoonest(a, b) {
    const da = daysLeft(a), db = daysLeft(b);
    const ka = da == null || da < 0 ? 1e9 : da, kb = db == null || db < 0 ? 1e9 : db;
    if (ka !== kb) return ka - kb;
    if (a.featured !== b.featured) return a.featured ? -1 : 1;
    return a.name.localeCompare(b.name);
  }

  function bigNumber(item) {
    const d = daysLeft(item);
    if (d != null && d >= 0) return { n: pad(d), l: (d === 1 ? "Day left" : "Days left") + (item.deadline_confirmed ? "" : " · unconfirmed") };
    if (item.status === "open") return { n: "OPEN", l: "Now" };
    if (item.status === "closed") return { n: "SHUT", l: "Closed" };
    if (item.window && item.window.length === 12) return { n: "∞", l: "Rolling" };
    const m = nextWindowMonth(item);
    if (m === thisMonth()) return { n: "NOW", l: "In usual window (est.)" };
    if (m) return { n: MONTHS[m - 1].toUpperCase(), l: "Opens (est.)" };
    return { n: "—", l: "Date unknown" };
  }

  function eligTag(item) {
    const l = label(item);
    const title = esc((item.elig_reasons || []).join(" · "));
    return `<span class="tag ${esc(l)}" title="${title}">${esc(ELIG_LABEL[l] || l)}</span>`;
  }
  function statusTag(item) {
    if (!item.status || item.status === "unknown") return "";
    return `<span class="tag ${esc(item.status)}">${esc(item.status)}</span>`;
  }
  function where(item) {
    if (item.format === "online") return "Online";
    return [item.city, item.country].filter(Boolean).join(", ") || REGION_LABEL[item.region] || "";
  }
  function bgFor(item, mode) {
    if (mode === "region") return REGION_BG[item.region] || "sand";
    return (KIND[item.kind] || {}).bg || "white";
  }

  function saveButton(item, extraClass) {
    const t = state.tracker[item.id];
    if (t) return `<a class="go small ${extraClass || ""}" href="#tracker">${esc(STAGES.find((s) => s.id === t.stage).label)}</a>`;
    return `<button class="go small ${extraClass || ""}" data-act="save" data-id="${esc(item.id)}">Save</button>`;
  }
  // ---- calendar
  const ymd = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");
  function calLink(item, cls) {
    const d = daysLeft(item);
    if (d == null || d < 0) return "";
    const start = new Date(item.deadline + "T00:00:00Z"), end = new Date(start.getTime() + DAY);
    const q = new URLSearchParams({
      action: "TEMPLATE",
      text: (item.deadline_confirmed ? "Deadline: " : "Deadline (unconfirmed): ") + item.name,
      dates: ymd(start) + "/" + ymd(end),
      details: `${item.org}. ${ELIG_LABEL[label(item)] || ""}\n${item.url}`,
    });
    return `<a class="go small ${cls || ""}" href="https://calendar.google.com/calendar/render?${esc(q.toString())}" target="_blank" rel="noopener" title="Add this deadline to Google Calendar">+ Calendar</a>`;
  }
  function feedUrl() { return new URL("data/deadlines.ics", location.href).href; }
  function subscribeLinks() {
    const webcal = feedUrl().replace(/^https?:/, "webcal:");
    return `<div class="row" style="margin-top:12px">
      <a class="go small dark" href="https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcal)}" target="_blank" rel="noopener">Subscribe in Google Calendar</a>
      <a class="go small" href="${esc(webcal)}">Apple / Outlook</a></div>
      <p style="font-size:12px;margin:8px 0 0">All deadlines you can enter, updated every 6 hours. Google shows its own default reminders for subscribed calendars; Apple and Outlook use the 14- and 3-day reminders.</p>`;
  }
  function icsFor(list) {
    const esc2 = (t) => String(t || "").replace(/[\\;,]/g, (c) => "\\" + c).replace(/\n/g, "\\n");
    const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
    const out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Opportunity Tracker//Saved//EN"];
    list.forEach((i) => {
      const start = new Date(i.deadline + "T00:00:00Z"), end = new Date(start.getTime() + DAY);
      out.push("BEGIN:VEVENT", `UID:${i.id}@opportunity-tracker-saved`, `DTSTAMP:${stamp}`,
        `DTSTART;VALUE=DATE:${ymd(start)}`, `DTEND;VALUE=DATE:${ymd(end)}`,
        `SUMMARY:${esc2((i.deadline_confirmed ? "Deadline: " : "Deadline (unconfirmed): ") + i.name)}`, `DESCRIPTION:${esc2(i.url)}`, `URL:${i.url}`);
      [14, 3].forEach((n) => out.push("BEGIN:VALARM", "ACTION:DISPLAY", `DESCRIPTION:${esc2(i.name + " closes in " + n + " days")}`, `TRIGGER:-P${n}D`, "END:VALARM"));
      out.push("END:VEVENT");
    });
    out.push("END:VCALENDAR");
    return out.join("\r\n") + "\r\n";
  }

  // ------------------------------------------------------------ shared blocks
  const progHref = (item) => "#p/" + encodeURIComponent(item.id);
  const BOOKMARK = '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 3h12v18l-6-4-6 4z"></path></svg>';

  function saveDot(item) {
    const saved = !!state.tracker[item.id];
    return `<button class="save-dot" data-act="${saved ? "unsave" : "save"}" data-id="${esc(item.id)}" aria-pressed="${saved}" aria-label="${saved ? "Remove from" : "Save to"} tracker: ${esc(item.name)}" title="${saved ? "Saved" : "Save"}">${BOOKMARK}</button>`;
  }

  // Small "↗" link straight to the official page, next to Save.
  function extDot(item, cls) {
    if (!/^https?:\/\//i.test(item.url || "")) return "";
    return `<a class="ext-dot ${cls || ""}" href="${esc(item.url)}" target="_blank" rel="noopener" aria-label="Official page: ${esc(item.name)} (opens a new tab)" title="Official page">↗</a>`;
  }

  // A slim card: the whole card opens the program page; Save and the official-page link sit on top of it.
  function block(item, mode) {
    const big = bigNumber(item);
    const kind = KIND[item.kind] || { label: item.kind };
    const fund = item.funding ? FUND_LABEL[item.funding] || item.funding : "";
    return `
    <div class="slim-wrap" id="item-${esc(item.id)}">
      <a class="slim bg-${bgFor(item, mode)}" href="${progHref(item)}">
        <span class="k">${esc(kind.label)}${where(item) ? " · " + esc(where(item)) : ""}</span>
        <span class="slim-title">${esc(item.name)}</span>
        <span class="row">${eligTag(item)}${fund ? `<span class="tag">${esc(fund)}</span>` : ""}${item.manual_check ? `<span class="tag">Check manually</span>` : ""}</span>
        <span class="slim-foot"><span><span class="big">${esc(big.n)}</span><span class="k">${esc(big.l)}</span></span></span>
      </a>
      <div class="card-acts">${extDot(item)}${saveDot(item)}</div>
    </div>`;
  }

  // One line per program, for the compact list view.
  function line(item) {
    const big = bigNumber(item);
    const meta = [(KIND[item.kind] || {}).label, where(item), item.funding ? FUND_LABEL[item.funding] : ""].filter(Boolean).join(" · ");
    return `<div class="lrow" id="item-${esc(item.id)}">
      <a class="lrow-main" href="${progHref(item)}">
        <span class="dot dot-${esc(label(item))}" title="${esc(ELIG_LABEL[label(item)] || "")}"></span>
        <span class="lrow-body"><span class="lrow-name">${esc(item.name)}</span><span class="lrow-meta">${esc(meta)}</span></span>
        <span class="lrow-big"><span>${esc(big.n)}</span><span class="k muted">${esc(big.l)}</span></span>
      </a>${extDot(item, "inline")}
    </div>`;
  }

  // Cards or lines, PAGE at a time, with a "Show more" button.
  function collection(list, key, mode) {
    if (!list.length) return "";
    const limit = state.limits[key] || PAGE;
    const shown = list.slice(0, limit);
    const body = layout() === "list"
      ? `<div class="lines">${shown.map(line).join("")}</div>`
      : `<div class="grid">${shown.map((i) => block(i, mode)).join("")}</div>`;
    const more = list.length > limit
      ? `<div class="more"><button class="go dark" data-act="more" data-key="${esc(key)}">Show ${Math.min(PAGE, list.length - limit)} more</button><span class="k muted">Showing ${limit} of ${list.length}</span></div>`
      : "";
    return body + more;
  }

  function layoutSwitch() {
    const l = layout();
    return `<div class="row" role="group" aria-label="View">
      <button class="go small" data-act="layout" data-val="cards" aria-pressed="${l === "cards"}">Cards</button>
      <button class="go small" data-act="layout" data-val="list" aria-pressed="${l === "list"}">List</button></div>`;
  }

  function hiddenList(list) {
    if (!state.eligibleOnly) return "";
    const hidden = list.filter((i) => !isVisible(i) && label(i) !== "ignore");
    if (!hidden.length) return "";
    return `<details class="hidden-list"><summary class="k">${hidden.length} hidden · not open to you</summary><ul>${hidden
      .map((i) => `<li><a href="${progHref(i)}"><strong>${esc(i.name)}</strong></a> (${esc(i.org)}): ${esc(hiddenReason(i))}</li>`).join("")}</ul></details>`;
  }

  // The eligibility reason plus the program note, without repeating the note when it is the reason.
  function reasonText(item) {
    if (item.verified_local) return esc("Verified by you on this device. Copy your decisions into overrides.yaml to keep it everywhere.");
    const reason = (item.elig_reasons || [])[0] || "";
    const extra = item.notes && item.notes !== reason ? " — " + item.notes : "";
    return esc(reason + extra);
  }

  function empty(text) { return `<div class="empty">${esc(text)}</div>`; }

  function cover(item, kicker) {
    const big = bigNumber(item);
    return `
    <article class="cover">
      <div class="cover-main">
        <div class="row"><span class="k">${esc(kicker)}</span>${label(item) !== "eligible" ? `<span class="tag" style="background:transparent;border-color:#fff;color:#fff">${esc(ELIG_LABEL[label(item)])}</span>` : ""}</div>
        <div>
          <h2 class="h cover-title"><a href="${progHref(item)}" style="text-decoration:none">${esc(item.name)}</a></h2>
          <p>${esc(item.org)}${where(item) ? " · " + esc(where(item)) : ""}${item.summary ? ". " + esc(item.summary) : ""}</p>
        </div>
        <div class="row"><a class="go small on-dark fill" href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener">Official page ↗</a><a class="go small on-dark" href="${progHref(item)}">Details</a>${saveButton(item, "on-dark")}</div>
      </div>
      <div class="cover-big"><span class="n">${esc(big.n)}</span><span class="k">${esc(big.l)}</span></div>
    </article>`;
  }

  // ------------------------------------------------------------ views
  // Non-featured Devpost hackathons are many and mostly small; keep them out of the Overview and Review
  // unless you switch them on in Review. They always stay listed in Compete.
  function isNoise(i) { return !state.allHackathons && i.source === "devpost" && !i.featured; }

  function viewOverview() {
    const vis = items().filter(isVisible).filter((i) => !isNoise(i));
    const weekAgo = Date.now() - 7 * DAY;
    const recent = state.data.changes.filter((c) => (c.type === "new" || c.type === "opened") && Date.parse(c.at) >= weekAgo);
    const visIds = new Set(vis.map((i) => i.id));
    const freshIds = [...new Set(recent.map((c) => c.id))].filter((id) => visIds.has(id));
    const due = vis.filter((i) => { const d = daysLeft(i); return d != null && d >= 0 && d <= 14; }).sort(bySoonest);
    const openElig = vis.filter((i) => i.status === "open" && ["eligible", "likely"].includes(label(i)));
    const applied = Object.values(state.tracker).filter((t) => t.stage !== "saved").length;
    const coverItem = vis.filter((i) => { const d = daysLeft(i); return d != null && d >= 0; }).sort(bySoonest)[0]
      || vis.filter((i) => i.status === "open" && i.featured)[0] || vis.filter((i) => i.featured)[0];
    const soon = vis.filter((i) => { const d = daysLeft(i); return d != null && d >= 0; }).sort(bySoonest).slice(0, 5);
    const byId = Object.fromEntries(state.items.map((i) => [i.id, i]));
    const fresh = freshIds.slice(0, 8).map((id) => byId[id]);
    const tl = vis.filter((i) => i.featured && i.window && i.window.length && i.window.length < 12).slice(0, 14);
    const nowM = thisMonth();

    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline">This week:<br><em>${fresh.length} new. ${due.length} due.</em></h1>
      <div class="row" role="group" aria-label="Year of study">
        ${["profile", "1", "2", "all"].map((y) => `<button class="go small" data-act="year" data-year="${y}" aria-pressed="${state.year === y}">${y === "profile" ? "My year" : y === "all" ? "All years" : "Year " + y}</button>`).join("")}
      </div>
    </div>
    <div class="stats">
      <div><div class="stat-n">${pad(openElig.length)}</div><div class="k muted">Open &amp; eligible</div></div>
      <div><div class="stat-n">${pad(fresh.length)}</div><div class="k muted">New this week</div></div>
      <div><div class="stat-n">${pad(due.length)}</div><div class="k muted">Due in 14 days</div></div>
      <div><div class="stat-n">${pad(applied)}</div><div class="k muted">Applied</div></div>
    </div>
    <div class="split">
      ${coverItem ? cover(coverItem, daysLeft(coverItem) != null ? "Cover story · Closes first" : "Cover story") : empty("Nothing to feature yet")}
      <aside class="due" aria-labelledby="due-h">
        <h2 class="k" id="due-h" style="margin:0 0 6px">Closing soon</h2>
        ${soon.length ? soon.map((i) => `<a class="due-row" href="${progHref(i)}"><span>${esc(i.name)}</span><span${i.deadline_confirmed ? "" : ' title="Date not confirmed on the official page"'}>${pad(daysLeft(i))}d${i.deadline_confirmed ? "" : "?"}</span></a>`).join("")
          + (soon.some((i) => !i.deadline_confirmed) ? `<p style="font-size:12px;margin:8px 0 0">? = date from public listings, not yet confirmed on the official page</p>` : "")
          : `<p class="k" style="border-top:2px solid #0A0A0A;padding-top:10px">No dated deadlines yet. Add them in programs.yaml as you verify.</p>`}
        ${subscribeLinks()}
      </aside>
    </div>
    <section aria-labelledby="new-h">
      <h2 class="k" id="new-h" style="margin:0 0 8px">Just opened &amp; new</h2>
      ${fresh.length ? fresh.map((i, n) => `
        <article class="list-item">
          <span class="idx">${pad(n + 1)}</span>
          <div class="list-body">
            <div class="row"><span class="tag bg-${bgFor(i)}">${esc((KIND[i.kind] || {}).label || i.kind)}</span><span class="k muted">${esc(i.org)}</span></div>
            <h3 class="h list-title"><a href="${progHref(i)}" style="text-decoration:none">${esc(i.name)}</a></h3>
            <span class="muted" style="font-size:14px">${esc(where(i))}</span>
          </div>
          <div class="list-side">${eligTag(i)}${statusTag(i)}${extDot(i, "inline")}${saveDot(i)}</div>
        </article>`).join("") : empty("Nothing new in the last 7 days")}
    </section>
    <section>
      <div class="section-head"><h2 class="h section-title">The season ahead</h2><span class="k muted">Typical application windows · estimated</span></div>
      <div class="scroll-x" style="margin-top:12px"><div class="timeline">
        <div class="tl-row head"><span></span>${SEASON.map((m) => `<span class="k ${m === nowM ? "tl-now" : "muted"}">${MONTHS[m - 1]}</span>`).join("")}</div>
        ${tl.map((i) => `<div class="tl-row"><a class="tl-name" href="${progHref(i)}">${esc(i.name)}</a>${SEASON.map((m) =>
          `<span class="tl-cell ${i.window.includes(m) ? "bg-" + bgFor(i) : ""} ${m === nowM ? "now-col" : ""}" ${i.window.includes(m) ? `title="${esc(MONTHS[m - 1])}"` : ""}></span>`).join("")}</div>`).join("")}
      </div></div>
      <p class="k" style="color:var(--accent);margin:10px 0 0">Blue line = this month</p>
    </section>`;
  }

  function sectionOf(item) {
    if (SUMMER.includes(item.kind)) return "summer";
    if (COMPETE.includes(item.kind)) return "compete";
    return "bigtech";
  }

  function viewSummer() {
    const all = items(SUMMER);
    let list = all.filter(isVisible);
    if (state.ui.summerFunded) list = list.filter((i) => i.funding === "fully_funded");
    if (state.ui.summerRegion !== "all") list = list.filter((i) => i.region === state.ui.summerRegion);
    list.sort(bySoonest);
    const funded = list.filter((i) => i.funding === "fully_funded").length;
    const countries = new Set(list.map((i) => i.country).filter(Boolean)).size;
    const closing = list.filter((i) => { const d = daysLeft(i); return d != null && d >= 0 && d <= 30; }).length;
    const [first, ...rest] = list;
    const regions = ["all", "asia", "europe", "north_america", "middle_east"];
    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline">Fully funded.<br><em>Open to you.</em></h1>
      ${layoutSwitch()}
    </div>
    <div class="row">
      <span class="k" style="margin-right:6px">Filter</span>
      <button class="go small" data-act="ui" data-key="summerFunded" aria-pressed="${state.ui.summerFunded}">Fully funded only</button>
      ${regions.map((r) => `<button class="go small" data-act="ui" data-key="summerRegion" data-val="${r}" aria-pressed="${state.ui.summerRegion === r}">${r === "all" ? "All regions" : REGION_LABEL[r]}</button>`).join("")}
    </div>
    <div class="stats">
      <div><div class="stat-n">${pad(list.length)}</div><div class="k muted">Programs</div></div>
      <div><div class="stat-n">${pad(funded)}</div><div class="k muted">Fully funded</div></div>
      <div><div class="stat-n">${pad(closing)}</div><div class="k muted">Close in 30 days</div></div>
      <div><div class="stat-n">${pad(countries)}</div><div class="k muted">Countries</div></div>
    </div>
    ${first ? cover(first, daysLeft(first) != null ? "Featured · Closes first" : "Featured") : empty("No programs match these filters")}
    ${collection(rest, "summer", "region")}
    ${hiddenList(all)}`;
  }

  function viewCompete() {
    const all = items(COMPETE);
    let list = all.filter(isVisible);
    const u = state.ui;
    if (u.competeType !== "all") list = list.filter((i) => i.kind === u.competeType);
    if (u.featuredOnly) list = list.filter((i) => i.featured);
    if (u.onlineOnly) list = list.filter((i) => i.format === "online" || i.format === "hybrid");
    if (u.inVietnam) list = list.filter((i) => /viet|hanoi|ho chi minh|da nang/i.test(`${i.country} ${i.city} ${i.summary}`));
    list.sort(bySoonest);
    const types = [["all", "All"], ["hackathon", "Hackathons"], ["challenge", "Innovation"], ["business_comp", "Business"], ["contest", "Contests"]];
    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline">Build. Pitch.<br><em>Win.</em></h1>
      ${layoutSwitch()}
    </div>
    <div class="types" role="group" aria-label="Type">${types.map(([v, l]) => `<button data-act="ui" data-key="competeType" data-val="${v}" aria-pressed="${u.competeType === v}">${l}</button>`).join("")}</div>
    <div class="row">
      <button class="go small" data-act="ui" data-key="featuredOnly" aria-pressed="${u.featuredOnly}">Featured hosts</button>
      <button class="go small" data-act="ui" data-key="onlineOnly" aria-pressed="${u.onlineOnly}">Online</button>
      <button class="go small" data-act="ui" data-key="inVietnam" aria-pressed="${u.inVietnam}">In Vietnam</button>
      <span class="spacer"></span><span class="k muted">${list.length} programs</span>
    </div>
    ${list.length ? collection(list, "compete:" + u.competeType) : empty("Nothing matches. Try turning off “Featured hosts”.")}
    ${hiddenList(all)}`;
  }

  function viewBigTech() {
    const all = items(TECH);
    const vis = all.filter(isVisible).sort(bySoonest);
    const insight = vis.filter((i) => i.kind === "insight");
    const oss = vis.filter((i) => i.kind === "open_source");
    const named = vis.filter((i) => i.source === "registry" && i.kind !== "insight" && i.kind !== "open_source");
    const roles = vis.filter((i) => i.source !== "registry");
    const rolesLimit = state.limits.roles || PAGE;
    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline">Tech &amp; quant.<br><em>Get in early.</em></h1>
      ${layoutSwitch()}
    </div>
    <section><h2 class="k" style="margin:0 0 12px">Insight programs · Year 1–2</h2>
      ${collection(insight, "insight") || empty("No insight programs open to you right now")}
    </section>
    <section><h2 class="k" style="margin:0 0 12px">Open source &amp; remote · paid, from anywhere</h2>
      ${collection(oss, "oss") || empty("No open-source programs right now")}
    </section>
    <section><h2 class="k" style="margin:0 0 12px">Programs &amp; career pages</h2>
      ${collection(named, "named") || empty("No programs match")}
    </section>
    <section>
      <div class="section-head"><h2 class="h section-title">Open roles near you</h2><span class="k muted">Vietnam &amp; Singapore · from job feeds</span></div>
      ${roles.length ? `<div class="lines">${roles.slice(0, rolesLimit).map((i) => `
        <div class="lrow" id="item-${esc(i.id)}">
          <a class="lrow-main" href="${progHref(i)}">
            <span class="dot dot-${esc(label(i))}" title="${esc(ELIG_LABEL[label(i)] || "")}"></span>
            <span class="lrow-body"><span class="lrow-name">${esc(i.org)} · ${esc(i.name)}</span><span class="lrow-meta">${esc(i.city || i.country)} · ${esc(ELIG_LABEL[label(i)] || "")}</span></span>
          </a>${extDot(i, "inline")}
        </div>`).join("")}</div>
        ${roles.length > rolesLimit ? `<div class="more"><button class="go dark" data-act="more" data-key="roles">Show ${Math.min(PAGE, roles.length - rolesLimit)} more</button><span class="k muted">Showing ${rolesLimit} of ${roles.length}</span></div>` : ""}`
        : empty("No open roles in the feeds right now")}
    </section>
    ${hiddenList(all)}`;
  }

  // ------------------------------------------------------------ search
  function haystack(i) {
    return [i.name, i.org, i.country, i.city, i.summary, (i.themes || []).join(" "), (KIND[i.kind] || {}).label,
      REGION_LABEL[i.region], i.funding ? FUND_LABEL[i.funding] : "", i.format === "online" ? "online" : ""].join(" ").toLowerCase();
  }
  function searchResults(q) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    const ql = q.toLowerCase();
    return items().filter((i) => { const h = haystack(i); return words.every((w) => h.includes(w)); })
      .map((i) => {
        const n = i.name.toLowerCase();
        const score = (n.startsWith(ql) ? 4 : 0) + (n.includes(ql) ? 3 : 0) + (i.org.toLowerCase().includes(ql) ? 2 : 0) + (i.featured ? 1 : 0);
        return { i, score };
      })
      .sort((a, b) => b.score - a.score || bySoonest(a.i, b.i)).map((r) => r.i);
  }
  function viewSearch() {
    const q = state.query.trim();
    if (!q) return `<h1 class="h headline">Search.</h1>${empty("Type in the search box: a program, organisation, country or theme (for example “Japan”, “hackathon”, “fully funded”).")}`;
    const all = searchResults(q);
    const vis = all.filter(isVisible);
    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline" style="font-size:clamp(36px,6vw,80px)">${pad(vis.length)} for<br><em>“${esc(q)}”</em></h1>
      ${vis.length ? layoutSwitch() : ""}
    </div>
    ${vis.length ? collection(vis, "search:" + q) : empty(all.length ? "Nothing open to you matches. See the hidden results below." : "Nothing matches. Try fewer or different words.")}
    ${hiddenList(all)}`;
  }

  // ------------------------------------------------------------ program page
  function viewProgram(id) {
    const item = state.items.find((i) => i.id === id);
    if (!item) return `<a class="k" href="#overview">← Overview</a>${empty("This program is no longer listed. It may have closed or been removed from a feed.")}`;
    const big = bigNumber(item);
    const kind = KIND[item.kind] || { label: item.kind };
    const back = { summer: "Summer & study", compete: "Compete", bigtech: "Tech & quant" }[sectionOf(item)];
    const proposal = (state.data.proposals || {})[item.id];
    const openProposal = proposal && proposal.changes && Object.keys(proposal.changes).length && !state.suggestions[item.id];
    const d = daysLeft(item);
    const facts = [
      ["Deadline", item.deadline ? `${item.deadline} · 23:59 Vietnam time${d != null && d >= 0 ? ` · ${d} days left` : ""}${item.deadline_confirmed ? "" : " · unconfirmed: from public listings, check the official page"}` : "Not set yet"],
      ["Usual window", item.window && item.window.length ? (item.window.length === 12 ? "All year (rolling)" : item.window.map((m) => MONTHS[m - 1]).join(", ") + " (estimate)") : ""],
      ["Status", item.status && item.status !== "unknown" ? item.status : ""],
      ["Funding", item.funding ? FUND_LABEL[item.funding] || item.funding : ""],
      ["Prize", item.prize],
      ["Team", item.team_size],
      ["Format", item.format ? item.format.replace("_", " ") : ""],
      ["Where", where(item)],
      ["Years of study", item.class_years && item.class_years.length && item.class_years.length < 4 ? item.class_years.join(", ") : ""],
      ["Source", item.source],
      ["Last checked", item.last_checked ? item.last_checked.slice(0, 10) : ""],
    ].filter(([, v]) => v);
    return `
    <a class="k" href="#${sectionOf(item)}" style="text-decoration:none">← ${esc(back)}</a>
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:20px">
      <div style="flex:999 1 520px;min-width:0">
        <div class="row" style="margin-bottom:12px"><span class="tag bg-${bgFor(item)}">${esc(kind.label)}</span>${eligTag(item)}${statusTag(item)}${item.funding ? `<span class="tag">${esc(FUND_LABEL[item.funding] || item.funding)}</span>` : ""}</div>
        <h1 class="h prog-title">${esc(item.name)}</h1>
        <p style="margin:12px 0 0;font-size:17px">${esc(item.org)}${where(item) ? " · " + esc(where(item)) : ""}</p>
        ${item.summary ? `<p style="margin:8px 0 0;max-width:640px">${esc(item.summary)}</p>` : ""}
      </div>
      <div class="prog-side">
        <div style="text-align:right"><div class="prog-big">${esc(big.n)}</div><div class="k">${esc(big.l)}</div></div>
        <div class="row" style="justify-content:flex-end">${saveButton(item)}${calLink(item)}<button class="go small" data-act="share" data-id="${esc(item.id)}">Share</button><a class="go small dark" href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener">Official page ↗</a></div>
      </div>
    </div>
    <section class="prog-elig bg-${label(item) === "check" ? "yellow" : label(item) === "not_eligible" ? "sand" : "white"}">
      <h2 class="k" style="margin:0 0 6px">Can you enter?</h2>
      <div style="font:900 26px/1.05 Archivo,sans-serif;text-transform:uppercase">${esc(ELIG_LABEL[label(item)] || label(item))}</div>
      <p style="margin:8px 0 0">${reasonText(item)}</p>
      ${item.manual_check ? `<p style="margin:8px 0 0"><strong>Check manually:</strong> this site blocks automatic checks, so open it to see whether applications are open.</p>` : ""}
      ${label(item) === "check" && !state.decisions[item.id] ? `<div class="seg" role="group" aria-label="Decide" style="margin-top:12px">
        <button data-act="decide" data-id="${esc(item.id)}" data-val="eligible">Eligible</button><button data-act="decide" data-id="${esc(item.id)}" data-val="not_eligible">Not eligible</button><button data-act="decide" data-id="${esc(item.id)}" data-val="ignore">Ignore</button></div>` : ""}
    </section>
    ${openProposal ? `<section class="prog-elig bg-peri">
      <h2 class="k" style="margin:0 0 6px">Claude's suggestion · confidence ${esc(proposal.confidence)}</h2>
      <ul style="margin:0;padding-left:18px">${Object.keys(proposal.changes).map((k) => `<li style="margin:6px 0"><strong>${esc(FIELD_LABEL[k] || k)}:</strong> ${esc(fmtVal(item[k]))} → <strong>${esc(fmtVal(proposal.changes[k]))}</strong>${proposal.quotes && proposal.quotes[k] ? `<blockquote style="margin-top:4px">“${esc(proposal.quotes[k])}”</blockquote>` : ""}</li>`).join("")}</ul>
      <div class="seg" role="group" aria-label="Decide suggestion" style="margin-top:12px"><button data-act="suggest" data-id="${esc(item.id)}" data-val="accept">Accept</button><button data-act="suggest" data-id="${esc(item.id)}" data-val="dismiss">Dismiss</button></div>
    </section>` : ""}
    ${verifyBox(item)}
    <section>
      <h2 class="k" style="margin:0 0 4px">Details</h2>
      <dl class="facts">${facts.map(([k, v]) => `<div><dt class="k muted">${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
    </section>
`;
  }

  // ------------------------------------------------------------ verification
  const NAT_OPTS = [["global", "Open to all nationalities"], ["vn_ok", "Vietnam explicitly included"], ["other_restriction", "Limited country list"],
    ["us_only", "US citizens/residents only"], ["eu_only", "EU/EEA only"], ["unknown", "The page doesn't say"]];
  const ENR_OPTS = [["any", "Students at any university"], ["vn_university_ok", "Students at Vietnamese universities"],
    ["local_only", "Only students living or studying in the host country"], ["us_canada_only", "Only US/Canadian universities"],
    ["host_university_only", "Only the host university's own students"], ["unknown", "The page doesn't say"]];

  function verifyBox(item) {
    if (item.source !== "registry") return "";
    const v = state.verified[item.id];
    if (item.verified && !item.verified_local) {
      return `<section class="prog-elig bg-white"><h2 class="k" style="margin:0">Verified</h2><p style="margin:6px 0 0">Checked against the official page and saved in the tracker's data.</p></section>`;
    }
    if (v) {
      return `<section class="prog-elig bg-lime">
        <h2 class="k" style="margin:0 0 6px">Verified by you · ${esc((v.at || "").slice(0, 10))}</h2>
        <p style="margin:0">Saved on this device. Copy your decisions from the Review tab into <code>overrides.yaml</code> to keep it everywhere.</p>
        <div class="row" style="margin-top:12px"><a class="go small dark" href="#review">Go to my decisions</a><button class="go small" data-act="unverify" data-id="${esc(item.id)}">Undo</button></div>
      </section>`;
    }
    const sel = (name, opts, cur) => `<select class="field" name="${name}" id="v-${name}">${opts.map(([val, txt]) =>
      `<option value="${val}"${val === cur ? " selected" : ""}>${esc(txt)}</option>`).join("")}</select>`;
    const years = item.class_years && item.class_years.length ? item.class_years : [1, 2, 3, 4];
    return `<section class="prog-elig bg-white" id="verify">
      <h2 class="k" style="margin:0 0 6px">Verify this program · about 10 minutes</h2>
      <p style="margin:0 0 14px">Open the <a href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener">official page ↗</a>, check each answer against it, then save. Verified programs can show <strong>Eligible</strong>, and their deadlines count as confirmed.</p>
      <form class="verify" data-id="${esc(item.id)}">
        <div class="vgrid">
          <label for="v-nationality_ok"><span class="k">Nationality</span>${sel("nationality_ok", NAT_OPTS, item.nationality_ok)}</label>
          <label for="v-enrollment_req"><span class="k">Who can apply</span>${sel("enrollment_req", ENR_OPTS, item.enrollment_req)}</label>
          <label for="v-deadline"><span class="k">Deadline (leave empty if none or rolling)</span><input class="field" type="date" name="deadline" id="v-deadline" value="${esc(item.deadline || "")}"></label>
        </div>
        <fieldset class="vyears"><legend class="k">Years of study allowed</legend>
          ${[1, 2, 3, 4].map((y) => `<label class="vcheck"><input type="checkbox" name="years" value="${y}"${years.includes(y) ? " checked" : ""}> Year ${y}</label>`).join("")}
        </fieldset>
        <button type="submit" class="go dark">Mark as verified</button>
      </form>
    </section>`;
  }

  function sprintList() {
    return state.items.filter((i) => i.source === "registry" && !i.verified && i.featured && !["not_eligible", "ignore"].includes(label(i)))
      .sort(bySoonest).slice(0, 15);
  }

  // ------------------------------------------------------------ review
  const FIELD_LABEL = { nationality_ok: "Nationality", enrollment_req: "Who can apply", class_years: "Years of study", deadline: "Deadline", funding: "Funding" };
  const fmtVal = (v) => Array.isArray(v) ? (v.length ? v.join(", ") : "—") : (v == null || v === "" ? "—" : String(v).replace(/_/g, " "));

  function yamlScalar(v) {
    if (Array.isArray(v)) return "[" + v.join(", ") + "]";
    if (typeof v === "boolean") return String(v);
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(v))) return JSON.stringify(String(v));  // keep dates as text
    return /^[\w.-]+$/.test(String(v)) ? String(v) : JSON.stringify(String(v));
  }

  function exportYaml() {
    const decided = Object.entries(state.decisions);
    const proposals = (state.data && state.data.proposals) || {};
    const accepted = Object.entries(state.suggestions).filter(([id, d]) => d === "accept" && proposals[id]);
    let out = "";
    if (decided.length) out += "overrides:\n" + decided.map(([id, d]) => `  ${id}:\n    eligible_for_me: ${d}\n    reason: Decided in the review queue`).join("\n") + "\n";
    // Accepted suggestions and your own verifications both become field overrides; your verification wins.
    const fields = {};
    accepted.forEach(([id]) => { fields[id] = Object.assign({}, proposals[id].changes || {}, { verified: true }); });
    Object.entries(state.verified).forEach(([id, v]) => {
      fields[id] = Object.assign(fields[id] || {}, {
        nationality_ok: v.nationality_ok, enrollment_req: v.enrollment_req, class_years: v.class_years,
        deadline: v.deadline || null, deadline_confirmed: !!v.deadline, verified: true,
      });
    });
    const ids = Object.keys(fields);
    if (ids.length) out += (out ? "\n" : "") + "fields:\n" + ids.map((id) => `  ${id}:\n` + Object.entries(fields[id])
      .filter(([, val]) => val !== null && val !== undefined).map(([k, val]) => `    ${k}: ${yamlScalar(val)}`).join("\n")).join("\n") + "\n";
    return out;
  }

  const JOB_SOURCES = ["greenhouse", "lever", "simplify"];
  function reviewQueue() {
    return items().filter((i) => label(i) === "check" && !state.decisions[i.id] && !JOB_SOURCES.includes(i.source)
      && (state.allHackathons || i.source !== "devpost" || i.featured));
  }
  function hiddenHackathons() {
    return items().filter((i) => i.source === "devpost" && !i.featured && label(i) === "check" && !state.decisions[i.id]).length;
  }
  function pendingProposals() {
    const byId = Object.fromEntries(state.items.map((i) => [i.id, i]));
    return Object.entries(state.data.proposals || {})
      .filter(([id, p]) => byId[id] && p.changes && Object.keys(p.changes).length && !state.suggestions[id])
      .map(([id, p]) => ({ item: byId[id], p }));
  }
  const GROUPS = [
    { key: "feeds", title: "Scholarships & programs", sub: "From opportunity sites and student forums", test: (i) => i.source.startsWith("feed") },
    { key: "hackathons", title: "Online hackathons", sub: "From Devpost and MLH · rules differ per event", test: (i) => i.source === "devpost" || i.source === "mlh",
      bulk: { label: "Ignore all but featured", val: "ignore-unfeatured" } },
    { key: "curated", title: "Curated programs with unclear rules", sub: "From the tracker's own list", test: (i) => i.source === "registry" },
    { key: "other", title: "Other sources", sub: "", test: () => true },
  ];

  function decideRow(i) {
    return `<div class="rrow">
      <div class="rrow-body"><a class="rrow-name" href="${progHref(i)}">${esc(i.name)}</a><div class="rrow-meta">${esc((KIND[i.kind] || {}).label || i.kind)} · ${esc(i.org)} · ${reasonText(i)}</div></div>
      ${extDot(i, "inline")}
      <div class="seg" role="group" aria-label="Decide ${esc(i.name)}">
        <button data-act="decide" data-id="${esc(i.id)}" data-val="eligible">Eligible</button><button data-act="decide" data-id="${esc(i.id)}" data-val="not_eligible">Not eligible</button><button data-act="decide" data-id="${esc(i.id)}" data-val="ignore">Ignore</button>
      </div>
    </div>`;
  }

  function group(key, n, title, sub, count, rows, bulkHtml, defaultOpen) {
    const open = state.groupOpen[key] !== undefined ? state.groupOpen[key] : defaultOpen;
    const limit = state.limits["review:" + key] || REVIEW_PAGE;
    return `<details class="rgroup" data-group="${esc(key)}" ${open ? "open" : ""}>
      <summary><span class="idx">${pad(n)}</span><span class="rgroup-title"><span class="h">${esc(title)}</span><span>${esc(sub)}</span></span><span class="k">${count} item${count === 1 ? "" : "s"}</span><span class="chev" aria-hidden="true">›</span></summary>
      ${bulkHtml ? `<div class="row" style="padding:0 0 10px">${bulkHtml}</div>` : ""}
      ${rows.slice(0, limit).join("")}
      ${rows.length > limit ? `<div class="more"><button class="go small dark" data-act="more" data-key="review:${esc(key)}" data-step="${REVIEW_PAGE}">Show ${Math.min(REVIEW_PAGE, rows.length - limit)} more</button><span class="k muted">Showing ${limit} of ${rows.length}</span></div>` : ""}
    </details>`;
  }

  function viewReview() {
    const queue = reviewQueue();
    const pending = pendingProposals();
    const nDecisions = Object.keys(state.decisions).length + Object.values(state.suggestions).filter((d) => d === "accept").length
      + Object.keys(state.verified).length;
    const yaml = exportYaml();
    const sections = [];
    let n = 1;
    const sprint = sprintList();
    if (sprint.length) {
      sections.push(group("sprint", n++, "Verification sprint", "Featured programs nobody has checked yet, closest deadline first", sprint.length,
        sprint.map((i) => `<div class="rrow">
          <div class="rrow-body"><a class="rrow-name" href="${progHref(i)}">${esc(i.name)}</a>
            <div class="rrow-meta">${esc(ELIG_LABEL[label(i)] || label(i))} · ${i.deadline ? esc(i.deadline) + (i.deadline_confirmed ? "" : " (unconfirmed)") : "no deadline set"}</div></div>
          ${extDot(i, "inline")}<a class="go small dark" href="${progHref(i)}">Verify →</a>
        </div>`), "", true));
    }
    if (pending.length) {
      const high = pending.filter(({ p }) => p.confidence === "high").length;
      sections.push(group("claude", n++, "Claude's suggestions", "Read from official pages · quotes checked against the page", pending.length,
        pending.map(({ item, p }) => `<div class="rrow">
          <div class="rrow-body"><a class="rrow-name" href="${progHref(item)}">${esc(item.name)}</a>
            <div class="rrow-meta">${Object.keys(p.changes).map((k) => `${esc(FIELD_LABEL[k] || k)}: ${esc(fmtVal(item[k]))} → <strong>${esc(fmtVal(p.changes[k]))}</strong>${p.quotes && p.quotes[k] ? ` <em>“${esc(p.quotes[k])}”</em>` : ""}`).join(" · ")} · confidence ${esc(p.confidence)}</div></div>
          <div class="seg" role="group" aria-label="Decide suggestion for ${esc(item.name)}"><button data-act="suggest" data-id="${esc(item.id)}" data-val="accept">Accept</button><button data-act="suggest" data-id="${esc(item.id)}" data-val="dismiss">Dismiss</button></div>
        </div>`),
        high ? `<button class="go small dark" data-act="bulk" data-val="accept-high">Accept all high-confidence (${high})</button>` : "", true));
    }
    const left = queue.slice();
    GROUPS.forEach((g) => {
      const mine = left.filter(g.test);
      mine.forEach((i) => left.splice(left.indexOf(i), 1));
      if (!mine.length) return;
      let bulk = "";
      if (g.bulk) {
        const k = mine.filter((i) => !i.featured).length;
        if (k) bulk = `<button class="go small" data-act="bulk" data-val="${g.bulk.val}" data-group="${g.key}">${esc(g.bulk.label)} (${k})</button>`;
      }
      sections.push(group(g.key, n++, g.title, g.sub, mine.length, mine.map(decideRow), bulk, g.key === "feeds"));
    });
    const total = queue.length + pending.length;
    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline">You decide.</h1>
      <div class="row" style="gap:22px"><div><div class="stat-n">${pad(total)}</div><div class="k muted">To review</div></div><div><div class="stat-n">${pad(sections.length)}</div><div class="k muted">Groups</div></div></div>
    </div>
    <p style="margin:0;max-width:640px">Grouped by where items came from. Decisions apply on this device right away; copy them into <code>overrides.yaml</code> to keep them everywhere.</p>
    ${hiddenHackathons() || state.allHackathons ? `<div class="row"><button class="go small" data-act="hackathons">${state.allHackathons
      ? "Hide non-featured online hackathons" : `Also review ${hiddenHackathons()} non-featured online hackathons`}</button>
      <span class="k muted">${state.allHackathons ? "" : "They stay listed in Compete"}</span></div>` : ""}
    ${sections.length ? sections.join("") : empty("Nothing to review. Nice.")}
    ${yaml ? `
    <section>
      <div class="section-head"><h2 class="h section-title">Your decisions (${nDecisions})</h2>
        <div class="row"><button class="go small dark" data-act="copy">Copy for overrides.yaml</button><button class="go small" data-act="undo-all">Undo all</button></div></div>
      <p class="muted" style="font-size:14px">Paste into <code>overrides.yaml</code> in the repo (replacing its contents) and commit, so the digest, the calendar and your other devices use them too.</p>
      <textarea class="export" readonly aria-label="Decisions as YAML">${esc(yaml)}</textarea>
    </section>` : ""}`;
  }

  // ------------------------------------------------------------ backup / restore
  function hasPersonalData() {
    return [state.tracker, state.decisions, state.suggestions, state.verified].some((o) => Object.keys(o).length);
  }
  function backupBox() {
    const last = store.get("lastBackup", null);
    const days = last ? Math.floor((Date.now() - Date.parse(last)) / DAY) : null;
    const stale = hasPersonalData() && (days == null || days >= 14);
    return `<section class="backup ${stale ? "bg-yellow" : ""}" aria-labelledby="bk-h">
      <div style="flex:999 1 320px">
        <h2 class="k" id="bk-h" style="margin:0 0 4px">Your data lives only in this browser</h2>
        <p style="margin:0;font-size:14px">Saved programs, notes, decisions and verifications are kept on this device. Clearing browser data deletes them. ${last ? `Last backup: ${days === 0 ? "today" : days + " day" + (days === 1 ? "" : "s") + " ago"}.` : "No backup yet."}</p>
      </div>
      <div class="row">
        <button class="go small dark" data-act="backup">Back up my data</button>
        <label class="go small" for="restore-file" style="cursor:pointer">Restore from backup</label>
        <input type="file" id="restore-file" accept="application/json,.json" class="sr">
      </div>
    </section>`;
  }
  function downloadFile(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  function backup() {
    const data = { app: "opportunity-tracker", version: 1, exported_at: new Date().toISOString(),
      tracker: state.tracker, decisions: state.decisions, suggestions: state.suggestions, verified: state.verified,
      prefs: { layout: state.layout, eligibleOnly: state.eligibleOnly, year: state.year, allHackathons: state.allHackathons } };
    downloadFile(`opportunity-tracker-backup-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(data, null, 1), "application/json");
    store.set("lastBackup", data.exported_at);
    toast("Backup downloaded");
  }
  const isObj = (o) => o && typeof o === "object" && !Array.isArray(o);
  function restore(file) {
    const reader = new FileReader();
    reader.onload = () => {
      let data;
      try { data = JSON.parse(reader.result); } catch (e) { toast("That file is not a backup from this app"); return; }
      if (!isObj(data) || data.app !== "opportunity-tracker" || !["tracker", "decisions", "suggestions", "verified"].every((k) => data[k] === undefined || isObj(data[k]))) {
        toast("That file is not a backup from this app"); return;
      }
      const when = (data.exported_at || "").slice(0, 10) || "an unknown date";
      if (hasPersonalData() && !window.confirm(`Replace the saved data on this device with the backup from ${when}?`)) return;
      state.tracker = data.tracker || {}; state.decisions = data.decisions || {};
      state.suggestions = data.suggestions || {}; state.verified = data.verified || {};
      const p = isObj(data.prefs) ? data.prefs : {};
      if (p.layout === "cards" || p.layout === "list") state.layout = p.layout;
      if (typeof p.eligibleOnly === "boolean") state.eligibleOnly = p.eligibleOnly;
      if (typeof p.allHackathons === "boolean") state.allHackathons = p.allHackathons;
      ["tracker", "decisions", "suggestions", "verified", "layout", "eligibleOnly", "allHackathons"].forEach((k) => store.set(k, state[k]));
      rebuild(); render(true); toast("Restored backup from " + when);
    };
    reader.readAsText(file);
  }

  function viewTracker() {
    const byId = Object.fromEntries(state.items.map((i) => [i.id, i]));
    const entries = Object.entries(state.tracker);
    const cols = STAGES.map((s) => ({ ...s, cards: entries.filter(([, t]) => t.stage === s.id) }));
    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline">Your season.</h1>
      <div style="max-width:420px;display:flex;flex-direction:column;gap:10px">
        <p style="margin:0">${entries.length} saved on this device. Use the arrows to move a card along.</p>
        ${entries.some(([id]) => byId[id] && daysLeft(byId[id]) != null && daysLeft(byId[id]) >= 0)
          ? `<button class="go small dark" data-act="ics" style="align-self:flex-start">Download my deadlines (.ics)</button>` : ""}
      </div>
    </div>
    ${backupBox()}
    ${entries.length ? `<div class="scroll-x"><div class="board">${cols.map((c, ci) => `
      <section class="col" aria-label="${esc(c.label)}">
        <div class="col-head"><h2 class="k" style="margin:0;font-size:13px">${esc(c.label)}</h2><span class="col-n">${pad(c.cards.length)}</span></div>
        ${c.cards.map(([id, t]) => {
          const i = byId[id];
          if (!i) return `<div class="tcard bg-sand"><span class="k">No longer listed</span><button class="go small" data-act="remove" data-id="${esc(id)}">Remove</button></div>`;
          const big = bigNumber(i);
          return `<article class="tcard bg-${bgFor(i)}">
            <span class="k">${esc((KIND[i.kind] || {}).label)} · ${esc(big.n)} ${esc(big.l)}</span>
            <h3 class="h" style="font-size:22px;line-height:1">${esc(i.name)}</h3>
            <label class="sr" for="note-${esc(id)}">Note</label>
            <input id="note-${esc(id)}" data-act="note" data-id="${esc(id)}" value="${esc(t.note || "")}" placeholder="Add a note">
            <div class="row">
              ${ci > 0 ? `<button class="go small" data-act="move" data-id="${esc(id)}" data-dir="-1" aria-label="Move back">←</button>` : ""}
              ${ci < STAGES.length - 1 ? `<button class="go small dark" data-act="move" data-id="${esc(id)}" data-dir="1" aria-label="Move forward">→</button>` : ""}
              <a class="go small" href="${progHref(i)}">Details</a>
              <button class="go small" data-act="remove" data-id="${esc(id)}">Remove</button>
            </div>
          </article>`;
        }).join("")}
      </section>`).join("")}</div></div>` : empty("Save something from another tab to start your season")}`;
  }

  const VIEWS = { overview: viewOverview, summer: viewSummer, compete: viewCompete, bigtech: viewBigTech, review: viewReview, tracker: viewTracker, p: viewProgram, search: viewSearch };

  // ------------------------------------------------------------ rendering & routing
  function route() {
    const raw = location.hash.replace(/^#/, "") || "overview";
    const cut = raw.indexOf("/");
    const name = cut < 0 ? raw : raw.slice(0, cut);
    let focus = cut < 0 ? "" : raw.slice(cut + 1);
    try { focus = decodeURIComponent(focus); } catch (e) { /* keep raw */ }
    return { name: VIEWS[name] ? name : "overview", focus };
  }

  function render(keepScroll) {
    const { name, focus } = route();
    const y = window.scrollY;
    document.getElementById("view").innerHTML = VIEWS[name](focus);
    let section = name;
    if (name === "p") { const it = state.items.find((i) => i.id === focus); section = it ? sectionOf(it) : ""; }
    document.querySelectorAll(".nav a").forEach((a) => {
      if (a.getAttribute("href") === "#" + section) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    const reviewCount = reviewQueue().length + pendingProposals().length;
    document.querySelector('.nav a[href="#review"] .count').textContent = reviewCount ? ` (${reviewCount})` : "";
    const toggle = document.getElementById("elig-toggle");
    toggle.setAttribute("aria-pressed", String(state.eligibleOnly));
    toggle.classList.toggle("dark", state.eligibleOnly);
    toggle.textContent = state.eligibleOnly ? "Eligible for me · VN" : "Showing everything";
    if (keepScroll) window.scrollTo(0, y);
    else if (focus && name !== "p") { const el = document.getElementById("item-" + focus); if (el) el.scrollIntoView({ block: "center" }); }
    else window.scrollTo(0, 0);
  }

  function toast(text) {
    const t = document.createElement("div");
    t.className = "toast"; t.setAttribute("role", "status"); t.textContent = text;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2200);
  }

  function saveTracker() { store.set("tracker", state.tracker); }

  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-act]");
    if (!el || el.tagName === "INPUT") return;
    const { act, id } = el.dataset;
    if (act === "save") { state.tracker[id] = { stage: "saved", note: "", at: new Date().toISOString() }; saveTracker(); toast("Saved to your tracker"); }
    else if (act === "backup") { backup(); return; }
    else if (act === "share") { share(id); return; }
    else if (act === "hackathons") { state.allHackathons = !state.allHackathons; store.set("allHackathons", state.allHackathons); }
    else if (act === "unverify") { delete state.verified[id]; store.set("verified", state.verified); rebuild(); toast("Verification removed"); }
    else if (act === "unsave") { delete state.tracker[id]; saveTracker(); toast("Removed from your tracker"); }
    else if (act === "more") { const k = el.dataset.key; state.limits[k] = (state.limits[k] || Number(el.dataset.step || PAGE)) + Number(el.dataset.step || PAGE); }
    else if (act === "layout") { state.layout = el.dataset.val; store.set("layout", state.layout); }
    else if (act === "bulk") {
      if (el.dataset.val === "accept-high") {
        pendingProposals().filter(({ p }) => p.confidence === "high").forEach(({ item }) => { state.suggestions[item.id] = "accept"; });
        store.set("suggestions", state.suggestions); toast("Accepted high-confidence suggestions");
      } else if (el.dataset.val === "ignore-unfeatured") {
        const g = GROUPS.find((x) => x.key === el.dataset.group);
        const n = reviewQueue().filter((i) => g.test(i) && !i.featured).map((i) => { state.decisions[i.id] = "ignore"; return i; }).length;
        store.set("decisions", state.decisions); toast(n + " ignored");
      }
    }
    else if (act === "remove") { delete state.tracker[id]; saveTracker(); }
    else if (act === "move") {
      const t = state.tracker[id]; const idx = STAGES.findIndex((s) => s.id === t.stage) + Number(el.dataset.dir);
      t.stage = STAGES[Math.max(0, Math.min(STAGES.length - 1, idx))].id; t.at = new Date().toISOString(); saveTracker();
    }
    else if (act === "decide") { state.decisions[id] = el.dataset.val; store.set("decisions", state.decisions); toast("Decision saved"); }
    else if (act === "ics") {
      const byId = Object.fromEntries(state.items.map((i) => [i.id, i]));
      const list = Object.keys(state.tracker).map((k) => byId[k]).filter((i) => i && daysLeft(i) != null && daysLeft(i) >= 0);
      const url = URL.createObjectURL(new Blob([icsFor(list)], { type: "text/calendar" }));
      const a = document.createElement("a"); a.href = url; a.download = "my-deadlines.ics"; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast(list.length + " deadline" + (list.length === 1 ? "" : "s") + " downloaded");
      return;
    }
    else if (act === "undo-all") {
      if (Object.keys(state.verified).length && !window.confirm("Also remove your verifications on this device?")) return;
      state.decisions = {}; state.suggestions = {}; state.verified = {};
      ["decisions", "suggestions", "verified"].forEach((k) => store.set(k, {})); rebuild();
    }
    else if (act === "suggest") { state.suggestions[id] = el.dataset.val; store.set("suggestions", state.suggestions); toast(el.dataset.val === "accept" ? "Accepted" : "Dismissed"); }
    else if (act === "copy") {
      const text = document.querySelector("textarea.export").value;
      (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(() => toast("Copied"), () => { document.querySelector("textarea.export").select(); toast("Press Ctrl+C to copy"); });
      return;
    }
    else if (act === "ui") {
      const key = el.dataset.key;
      state.ui[key] = el.dataset.val !== undefined ? el.dataset.val : !state.ui[key];
    }
    else if (act === "year") { state.year = el.dataset.year; store.set("year", state.year); }
    render(true);
  });

  document.addEventListener("submit", (ev) => {
    const form = ev.target;
    if (!form.classList || !form.classList.contains("verify")) return;
    ev.preventDefault();
    const f = new FormData(form);
    const deadline = String(f.get("deadline") || "");
    state.verified[form.dataset.id] = {
      nationality_ok: String(f.get("nationality_ok")), enrollment_req: String(f.get("enrollment_req")),
      class_years: f.getAll("years").map(Number).sort(), deadline: /^\d{4}-\d{2}-\d{2}$/.test(deadline) ? deadline : "",
      at: new Date().toISOString(),
    };
    store.set("verified", state.verified); rebuild(); toast("Marked as verified on this device"); render(true);
  });

  document.addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.id === "restore-file" && el.files && el.files[0]) { restore(el.files[0]); el.value = ""; return; }
    if (el.dataset && el.dataset.act === "note" && state.tracker[el.dataset.id]) { state.tracker[el.dataset.id].note = el.value; saveTracker(); }
  });

  document.getElementById("elig-toggle").addEventListener("click", () => {
    state.eligibleOnly = !state.eligibleOnly; store.set("eligibleOnly", state.eligibleOnly); render(true);
  });
  window.addEventListener("hashchange", () => { state.limits = {}; render(false); });
  // Remember which Review groups are open across re-renders.
  document.addEventListener("toggle", (ev) => {
    const d = ev.target;
    if (d.classList && d.classList.contains("rgroup")) state.groupOpen[d.dataset.group] = d.open;
  }, true);

  // ---- search box (header, every tab)
  const qInput = document.getElementById("q");
  let qTimer = null;
  qInput.addEventListener("input", () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => {
      state.query = qInput.value;
      if (route().name !== "search") location.hash = "#search"; else { state.limits = {}; render(false); }
    }, 150);
  });
  document.getElementById("search-form").addEventListener("submit", (ev) => {
    ev.preventDefault(); state.query = qInput.value; qInput.blur();
    if (route().name !== "search") location.hash = "#search"; else render(false);
  });
  qInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { qInput.value = ""; state.query = ""; if (route().name === "search") render(false); }
  });
  document.addEventListener("keydown", (ev) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName);
    if (ev.key === "/" && !typing && !ev.metaKey && !ev.ctrlKey) { ev.preventDefault(); qInput.focus(); }
  });

  // ---- theme: auto (device) → dark → light
  const ICON = (body) => `<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">${body}</svg>`;
  const THEMES = {
    auto: [ICON('<circle cx="12" cy="12" r="8.5"></circle><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor"></path>'), "Theme: follows your device"],
    dark: [ICON('<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z" fill="currentColor"></path>'), "Theme: dark"],
    light: [ICON('<circle cx="12" cy="12" r="4.2" fill="currentColor"></circle><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"></path>'), "Theme: light"],
  };
  function applyTheme(t) {
    if (t === "dark" || t === "light") document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    const b = document.getElementById("theme-toggle");
    b.innerHTML = THEMES[t][0]; b.setAttribute("aria-label", THEMES[t][1] + ". Tap to change"); b.title = THEMES[t][1];
  }
  let theme = store.get("theme", "auto");
  if (!THEMES[theme]) theme = "auto";
  applyTheme(theme);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    theme = { auto: "dark", dark: "light", light: "auto" }[theme];
    store.set("theme", theme); applyTheme(theme); toast(THEMES[theme][1]);
  });

  // ---- share a program (phone share sheet, else copy the link)
  function share(id) {
    const item = state.items.find((i) => i.id === id);
    if (!item) return;
    const url = location.href.split("#")[0] + "#p/" + encodeURIComponent(id);
    const text = `${item.name} (${item.org})`;
    if (navigator.share) { navigator.share({ title: item.name, text, url }).catch(() => {}); return; }
    (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject())
      .then(() => toast("Link copied"), () => toast("Copy this link: " + url));
  }

  // ---- install as an app, offline support
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    window.addEventListener("load", () => { navigator.serviceWorker.register("sw.js").catch(() => {}); });
  }
  let installPrompt = null;
  const installBtn = document.getElementById("install");
  window.addEventListener("beforeinstallprompt", (ev) => { ev.preventDefault(); installPrompt = ev; installBtn.hidden = false; });
  installBtn.addEventListener("click", () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    installPrompt.userChoice.finally(() => { installPrompt = null; installBtn.hidden = true; });
  });
  window.addEventListener("appinstalled", () => { installBtn.hidden = true; toast("Installed. Find it on your home screen."); });
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const iosHint = /iphone|ipad|ipod/i.test(navigator.userAgent) && !standalone
    ? `<p class="muted" style="font-size:13px">Use it like an app: in Safari tap <strong>Share</strong> → <strong>Add to Home Screen</strong>.</p>` : "";
  function updateOnline() { document.getElementById("offline").hidden = navigator.onLine !== false; }
  window.addEventListener("online", updateOnline);
  window.addEventListener("offline", updateOnline);
  updateOnline();

  function ago(iso) {
    const mins = Math.round((Date.now() - Date.parse(iso)) / 60000);
    if (isNaN(mins)) return "unknown";
    if (mins < 60) return mins + "m ago";
    if (mins < 2880) return Math.round(mins / 60) + "h ago";
    return Math.round(mins / 1440) + "d ago";
  }

  fetch("data/opportunities.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then((data) => {
      data.changes = data.changes || [];
      state.data = data;
      rebuild();
      const d = nowICT();
      document.getElementById("issue").textContent = `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()} · Updated ${ago(data.generated_at)}`;
      const problems = data.source_problems || [];
      const srcs = Object.entries(data.sources || {});
      document.getElementById("footer").innerHTML = `${problems.length ? `<p class="k" style="background:var(--yellow);color:#0A0A0A;padding:8px 12px;border-radius:4px">Source trouble: ${esc(problems.join(" · "))}</p>` : ""}
        <details><summary class="k" style="cursor:pointer;min-height:28px">${srcs.length} sources · ${srcs.filter(([, v]) => String(v).startsWith("FAILED")).length} failed this run</summary>
        <ul style="columns:2 240px;font-size:13px;padding-left:18px">${srcs.map(([k, v]) => `<li>${esc(k)}: ${esc(v)}</li>`).join("")}</ul></details>
        ${iosHint}<p class="muted">Always confirm dates and eligibility on the official page. Deadlines are shown in Vietnam time (UTC+7). Labels: <strong>Eligible</strong> = verified, <strong>Likely</strong> = rules look open but unverified, <strong>Check rules</strong> = unclear.</p>`;
      render(false);
    })
    .catch((err) => {
      document.getElementById("view").innerHTML = empty("Could not load data (" + err.message + "). Run python -m tracker.run first.");
    });
})();
