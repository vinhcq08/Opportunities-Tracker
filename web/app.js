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
    internship: { label: "Internship", bg: "sand" },
  };
  const REGION_BG = { asia: "coral", europe: "peri", north_america: "lime", middle_east: "yellow", global: "sand" };
  const REGION_LABEL = { asia: "Asia", europe: "Europe", north_america: "North America", middle_east: "Middle East", global: "Global" };
  const ELIG_LABEL = { eligible: "VN ✓ Eligible", likely: "Likely", check: "Check rules", not_eligible: "Not eligible", ignore: "Ignored" };
  const FUND_LABEL = { fully_funded: "Fully funded", stipend: "Stipend", travel_covered: "Travel covered", free: "Free to enter", fee_required: "Fee" };
  const COMPETE = ["hackathon", "challenge", "business_comp"];
  const SUMMER = ["summer_research", "summer_school"];
  const TECH = ["insight", "underclassmen", "internship"];

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
    ui: { summerFunded: false, summerRegion: "all", competeType: "all", featuredOnly: true, onlineOnly: false, inVietnam: false },
  };

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

  function label(item) {
    return state.decisions[item.id] || item.eligible_for_me;
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
    return state.data.items.filter((i) => !kinds || kinds.includes(i.kind));
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
    if (d != null && d >= 0) return { n: pad(d), l: d === 1 ? "Day left" : "Days left" };
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
  function openLink(item, cls) {
    return `<a class="go small ${cls || "dark"}" href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener">Open ↗</a>`;
  }

  // ------------------------------------------------------------ shared blocks
  function block(item, mode) {
    const big = bigNumber(item);
    const kind = KIND[item.kind] || { label: item.kind };
    const topRight = item.funding ? FUND_LABEL[item.funding] || item.funding : (item.prize || "");
    const details = [];
    if (item.team_size) details.push(["Team", item.team_size]);
    if (item.prize && item.funding) details.push(["Prize", item.prize]);
    return `
    <article class="block bg-${bgFor(item, mode)}" id="item-${esc(item.id)}">
      <div class="block-top"><span class="k">${esc(mode === "region" ? REGION_LABEL[item.region] || "" : kind.label)}</span><span class="k">${esc(topRight)}</span></div>
      <div>
        <h3 class="h block-title">${esc(item.name)}</h3>
        <p>${esc(item.org)}${where(item) ? " · " + esc(where(item)) : ""}</p>
        ${item.summary ? `<p>${esc(item.summary)}</p>` : ""}
      </div>
      ${details.length ? `<dl>${details.map(([k, v]) => `<div><dt class="k">${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : ""}
      <div class="row">${eligTag(item)}${statusTag(item)}</div>
      ${label(item) === "check" || label(item) === "not_eligible" ? `<p class="reason">${reasonText(item)}</p>` : ""}
      ${item.manual_check ? `<p class="reason"><strong>Check manually:</strong> this site blocks automatic checks, so open it to see whether applications are open.</p>` : ""}
      <div class="block-foot">
        <div><div class="big">${esc(big.n)}</div><div class="k">${esc(big.l)}</div></div>
        <div class="row">${saveButton(item)}${openLink(item)}</div>
      </div>
    </article>`;
  }

  function hiddenList(list) {
    if (!state.eligibleOnly) return "";
    const hidden = list.filter((i) => !isVisible(i) && label(i) !== "ignore");
    if (!hidden.length) return "";
    return `<details class="hidden-list"><summary class="k">${hidden.length} hidden · not open to you</summary><ul>${hidden
      .map((i) => `<li><strong>${esc(i.name)}</strong> (${esc(i.org)}): ${esc(hiddenReason(i))}</li>`).join("")}</ul></details>`;
  }

  // The eligibility reason plus the program note, without repeating the note when it is the reason.
  function reasonText(item) {
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
          <h2 class="h cover-title">${esc(item.name)}</h2>
          <p>${esc(item.org)}${where(item) ? " · " + esc(where(item)) : ""}${item.summary ? ". " + esc(item.summary) : ""}</p>
        </div>
        <div class="row">${openLink(item, "on-dark fill")}${saveButton(item, "on-dark")}</div>
      </div>
      <div class="cover-big"><span class="n">${esc(big.n)}</span><span class="k">${esc(big.l)}</span></div>
    </article>`;
  }

  // ------------------------------------------------------------ views
  function viewOverview() {
    const vis = items().filter(isVisible);
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
    const byId = Object.fromEntries(state.data.items.map((i) => [i.id, i]));
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
        ${soon.length ? soon.map((i) => `<a class="due-row" href="#${sectionOf(i)}/${esc(i.id)}"><span>${esc(i.name)}</span><span>${pad(daysLeft(i))}d</span></a>`).join("")
          : `<p class="k" style="border-top:2px solid #0A0A0A;padding-top:10px">No dated deadlines yet. Add them in programs.yaml as you verify.</p>`}
      </aside>
    </div>
    <section aria-labelledby="new-h">
      <h2 class="k" id="new-h" style="margin:0 0 8px">Just opened &amp; new</h2>
      ${fresh.length ? fresh.map((i, n) => `
        <article class="list-item">
          <span class="idx">${pad(n + 1)}</span>
          <div class="list-body">
            <div class="row"><span class="tag bg-${bgFor(i)}">${esc((KIND[i.kind] || {}).label || i.kind)}</span><span class="k muted">${esc(i.org)}</span></div>
            <h3 class="h list-title">${esc(i.name)}</h3>
            <span class="muted" style="font-size:14px">${esc(where(i))}</span>
          </div>
          <div class="list-side">${eligTag(i)}${statusTag(i)}${saveButton(i)}${openLink(i)}</div>
        </article>`).join("") : empty("Nothing new in the last 7 days")}
    </section>
    <section>
      <div class="section-head"><h2 class="h section-title">The season ahead</h2><span class="k muted">Typical application windows · estimated</span></div>
      <div class="scroll-x" style="margin-top:12px"><div class="timeline">
        <div class="tl-row head"><span></span>${SEASON.map((m) => `<span class="k ${m === nowM ? "tl-now" : "muted"}">${MONTHS[m - 1]}</span>`).join("")}</div>
        ${tl.map((i) => `<div class="tl-row"><a class="tl-name" href="#${sectionOf(i)}/${esc(i.id)}">${esc(i.name)}</a>${SEASON.map((m) =>
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
    <h1 class="h headline">Fully funded.<br><em>Open to you.</em></h1>
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
    <div class="grid">${rest.map((i) => block(i, "region")).join("")}</div>
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
    const types = [["all", "All"], ["hackathon", "Hackathons"], ["challenge", "Innovation"], ["business_comp", "Business"]];
    return `
    <h1 class="h headline">Build. Pitch.<br><em>Win.</em></h1>
    <div class="types" role="group" aria-label="Type">${types.map(([v, l]) => `<button data-act="ui" data-key="competeType" data-val="${v}" aria-pressed="${u.competeType === v}">${l}</button>`).join("")}</div>
    <div class="row">
      <button class="go small" data-act="ui" data-key="featuredOnly" aria-pressed="${u.featuredOnly}">Featured hosts</button>
      <button class="go small" data-act="ui" data-key="onlineOnly" aria-pressed="${u.onlineOnly}">Online</button>
      <button class="go small" data-act="ui" data-key="inVietnam" aria-pressed="${u.inVietnam}">In Vietnam</button>
      <span class="spacer"></span><span class="k muted">${list.length} shown</span>
    </div>
    ${list.length ? `<div class="grid">${list.map((i) => block(i)).join("")}</div>` : empty("Nothing matches. Try turning off “Featured hosts”.")}
    ${hiddenList(all)}`;
  }

  function viewBigTech() {
    const all = items(TECH);
    const vis = all.filter(isVisible).sort(bySoonest);
    const insight = vis.filter((i) => i.kind === "insight");
    const named = vis.filter((i) => i.source === "registry" && i.kind !== "insight");
    const roles = vis.filter((i) => i.source !== "registry");
    return `
    <h1 class="h headline">Tech &amp; quant.<br><em>Get in early.</em></h1>
    <section><h2 class="k" style="margin:0 0 12px">Insight programs · Year 1–2</h2>
      ${insight.length ? `<div class="grid">${insight.map((i) => block(i)).join("")}</div>` : empty("No insight programs open to you right now")}
    </section>
    <section><h2 class="k" style="margin:0 0 12px">Programs &amp; career pages</h2>
      ${named.length ? `<div class="grid">${named.map((i) => block(i)).join("")}</div>` : empty("No programs match")}
    </section>
    <section>
      <div class="section-head"><h2 class="h section-title">Open roles near you</h2><span class="k muted">Vietnam &amp; Singapore · from job feeds</span></div>
      ${roles.length ? `<div class="scroll-x"><table>
        <thead><tr><th class="k" scope="col">Company</th><th class="k" scope="col">Role</th><th class="k" scope="col">City</th><th class="k" scope="col">Eligibility</th><th scope="col"><span class="sr">Actions</span></th></tr></thead>
        <tbody>${roles.map((i) => `<tr><td class="co">${esc(i.org)}</td><td>${esc(i.name)}</td><td>${esc(i.city || i.country)}</td><td>${eligTag(i)}</td><td style="text-align:right;white-space:nowrap">${saveButton(i)} ${openLink(i)}</td></tr>`).join("")}</tbody>
      </table></div>` : empty("No open roles in the feeds right now")}
    </section>
    ${hiddenList(all)}`;
  }

  function viewReview() {
    const queue = items().filter((i) => i.eligible_for_me === "check" && !state.decisions[i.id]);
    const decided = Object.entries(state.decisions);
    const yaml = decided.length ? "overrides:\n" + decided.map(([id, d]) => `  ${id}:\n    eligible_for_me: ${d}\n    reason: Decided in the review queue`).join("\n") : "";
    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline">You decide.</h1>
      <p style="max-width:420px;margin:0">These say “check rules”: the rules could not tell whether students in Vietnam can enter. Read the official page, then decide. Decisions apply on this device right away.</p>
    </div>
    <div>${queue.length ? queue.map((i, n) => `
      <article class="list-item">
        <span class="idx">${pad(n + 1)}</span>
        <div class="list-body">
          <div class="row"><span class="tag bg-${bgFor(i)}">${esc((KIND[i.kind] || {}).label)}</span><span class="k muted">via ${esc(i.source)} · ${esc(i.org)}</span></div>
          <h2 class="h list-title">${esc(i.name)}</h2>
          <blockquote>${reasonText(i)}</blockquote>
        </div>
        <div class="list-side">
          <button class="go small dark" data-act="decide" data-id="${esc(i.id)}" data-val="eligible">Eligible</button>
          <button class="go small" data-act="decide" data-id="${esc(i.id)}" data-val="not_eligible">Not eligible</button>
          <button class="go small" data-act="decide" data-id="${esc(i.id)}" data-val="ignore">Ignore</button>
          <a class="go small" href="${esc(safeUrl(i.url))}" target="_blank" rel="noopener">Official page ↗</a>
        </div>
      </article>`).join("") : empty("Queue is empty. Nice.")}</div>
    ${decided.length ? `
    <section>
      <div class="section-head"><h2 class="h section-title">Your decisions (${decided.length})</h2>
        <div class="row"><button class="go small dark" data-act="copy">Copy for overrides.yaml</button><button class="go small" data-act="undo-all">Undo all</button></div></div>
      <p class="muted" style="font-size:14px">Paste into <code>overrides.yaml</code> in the repo and commit, so the digest and other devices use them too.</p>
      <textarea class="export" readonly aria-label="Decisions as YAML">${esc(yaml)}</textarea>
    </section>` : ""}`;
  }

  function viewTracker() {
    const byId = Object.fromEntries(state.data.items.map((i) => [i.id, i]));
    const entries = Object.entries(state.tracker);
    const cols = STAGES.map((s) => ({ ...s, cards: entries.filter(([, t]) => t.stage === s.id) }));
    return `
    <div class="row" style="justify-content:space-between;align-items:flex-end;gap:16px">
      <h1 class="h headline">Your season.</h1>
      <p style="max-width:380px;margin:0">${entries.length} saved on this device. Use the arrows to move a card along.</p>
    </div>
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
              <a class="go small" href="${esc(safeUrl(i.url))}" target="_blank" rel="noopener">Open ↗</a>
              <button class="go small" data-act="remove" data-id="${esc(id)}">Remove</button>
            </div>
          </article>`;
        }).join("")}
      </section>`).join("")}</div></div>` : empty("Save something from another tab to start your season")}`;
  }

  const VIEWS = { overview: viewOverview, summer: viewSummer, compete: viewCompete, bigtech: viewBigTech, review: viewReview, tracker: viewTracker };

  // ------------------------------------------------------------ rendering & routing
  function route() {
    const [name, focus] = (location.hash.replace(/^#/, "") || "overview").split("/");
    return { name: VIEWS[name] ? name : "overview", focus };
  }

  function render(keepScroll) {
    const { name, focus } = route();
    const y = window.scrollY;
    document.getElementById("view").innerHTML = VIEWS[name]();
    document.querySelectorAll(".nav a").forEach((a) => {
      if (a.getAttribute("href") === "#" + name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    const reviewCount = state.data.items.filter((i) => i.eligible_for_me === "check" && !state.decisions[i.id]).length;
    document.querySelector('.nav a[href="#review"]').textContent = `Review (${reviewCount})`;
    const toggle = document.getElementById("elig-toggle");
    toggle.setAttribute("aria-pressed", String(state.eligibleOnly));
    toggle.classList.toggle("dark", state.eligibleOnly);
    toggle.textContent = state.eligibleOnly ? "Eligible for me · VN" : "Showing everything";
    if (keepScroll) window.scrollTo(0, y);
    else if (focus) { const el = document.getElementById("item-" + focus); if (el) el.scrollIntoView({ block: "center" }); }
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
    else if (act === "remove") { delete state.tracker[id]; saveTracker(); }
    else if (act === "move") {
      const t = state.tracker[id]; const idx = STAGES.findIndex((s) => s.id === t.stage) + Number(el.dataset.dir);
      t.stage = STAGES[Math.max(0, Math.min(STAGES.length - 1, idx))].id; t.at = new Date().toISOString(); saveTracker();
    }
    else if (act === "decide") { state.decisions[id] = el.dataset.val; store.set("decisions", state.decisions); toast("Decision saved"); }
    else if (act === "undo-all") { state.decisions = {}; store.set("decisions", {}); }
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

  document.addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.dataset && el.dataset.act === "note" && state.tracker[el.dataset.id]) { state.tracker[el.dataset.id].note = el.value; saveTracker(); }
  });

  document.getElementById("elig-toggle").addEventListener("click", () => {
    state.eligibleOnly = !state.eligibleOnly; store.set("eligibleOnly", state.eligibleOnly); render(true);
  });
  window.addEventListener("hashchange", () => render(false));

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
      const d = nowICT();
      document.getElementById("issue").textContent = `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()} · Updated ${ago(data.generated_at)}`;
      document.getElementById("footer").innerHTML = `<p class="k">Sources: ${Object.entries(data.sources || {}).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ")}</p>
        <p class="muted">Always confirm dates and eligibility on the official page. Deadlines are shown in Vietnam time (UTC+7). Labels: <strong>Eligible</strong> = verified, <strong>Likely</strong> = rules look open but unverified, <strong>Check rules</strong> = unclear.</p>`;
      render(false);
    })
    .catch((err) => {
      document.getElementById("view").innerHTML = empty("Could not load data (" + err.message + "). Run python -m tracker.run first.");
    });
})();
