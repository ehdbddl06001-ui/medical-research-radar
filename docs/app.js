/* 메디 리서치 레이더 - 화면 로직
   데이터: data/items.json (GitHub Actions 가 3시간마다 갱신)
   저장(별표)·읽음·마지막 방문은 이 기기의 localStorage 에만 저장됩니다. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const store = {
    get(k, d) { try { const v = localStorage.getItem("mr:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("mr:" + k, JSON.stringify(v)); } catch { /* 저장 불가 환경 */ } },
  };

  const S = {
    data: null,
    view: "feed",
    cat: store.get("cat", "all"),
    q: "",
    hidePast: store.get("hidePast", true),
    onlyFit: store.get("onlyFit", false),     // ★ 맞춤(관심 분야·학생 대상)만 보기
    stars: new Set(store.get("stars", [])),
    starItems: store.get("starItems", {}),   // 데이터에서 사라져도 저장함에 남도록 사본 보관
    read: new Set(store.get("read", [])),
    seenUntil: store.get("seenUntil", null), // 지난 방문 때 본 가장 최근 first_seen
  };

  const CAT_FALLBACK = [
    { id: "research", name: "연구·인턴" }, { id: "ai", name: "AI·해커톤" }, { id: "data", name: "데이터·WHO" },
  ];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const parseDay = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const daysLeft = (dl) => (dl ? Math.round((parseDay(dl) - today()) / 864e5) : null);

  // guess = 제목이 아니라 공고 본문에서 읽은 마감(추정) → 앞에 ≈ 를 붙이고 점선 테두리
  function ddBadge(dl, guess) {
    const n = daysLeft(dl);
    if (n == null) return "";
    const tip = `마감 ${dl}${guess ? " · 본문에서 읽은 날짜(추정) — 원문에서 확인하세요" : ""}`;
    if (n < 0) return `<span class="dd past" title="${tip}">마감</span>`;
    const cls = (n <= 3 ? "urgent" : n <= 10 ? "soon" : "") + (guess ? " guess" : "");
    return `<span class="dd ${cls}" title="${tip}">${guess ? "≈" : ""}${n === 0 ? "D-DAY" : "D-" + n}</span>`;
  }
  const starAt = () => S.data?.star ?? 4;
  const isFit = (it) => (it.score ?? 0) >= starAt();
  const isOff = (it) => (it.score ?? 0) < 0;
  function fmtDate(it) {
    const d = it.date || (it.baseline ? "" : (it.first_seen || "").slice(0, 10));
    if (!d) return "";
    const [y, m, dd] = d.split("-");
    return (y == String(new Date().getFullYear()) ? "" : y.slice(2) + ".") + `${+m}.${+dd}`;
  }
  const catName = (id) => (S.data?.categories || CAT_FALLBACK).find((c) => c.id === id)?.name || id;

  /* ---------------- 필터 ---------------- */
  function base() {
    let items = S.data?.items || [];
    if (S.view === "saved") items = [...S.stars].map((id) => items.find((x) => x.id === id) || S.starItems[id]).filter(Boolean);
    const q = S.q.trim().toLowerCase();
    if (q) items = items.filter((x) => `${x.title} ${x.source} ${x.extra} ${(x.tags || []).join(" ")}`.toLowerCase().includes(q));
    if (S.onlyFit && S.view !== "saved") items = items.filter(isFit);
    if (S.view === "due") {
      items = items.filter((x) => x.deadline && daysLeft(x.deadline) >= 0)
        .sort((a, b) => a.deadline.localeCompare(b.deadline));
    } else if (S.hidePast && S.view !== "saved") {
      items = items.filter((x) => !x.deadline || daysLeft(x.deadline) >= 0);
    }
    return items;
  }

  /* ---------------- 그리기 ---------------- */
  function card(it) {
    const isNew = S.seenUntil && it.first_seen > S.seenUntil;
    const starred = S.stars.has(it.id);
    const fit = isFit(it), off = isOff(it);
    const tags = (fit || off) && (it.tags || []).length
      ? `<span class="tags${off ? " off" : ""}">${esc((off ? it.tags.filter((t) => t === "대상 아님") : it.tags).join(" · "))}</span>` : "";
    return `<article class="card c-${esc(it.category)}${S.read.has(it.id) ? " read" : ""}${off ? " off" : ""}">
      <a href="${esc(it.link)}" target="_blank" rel="noopener" data-id="${esc(it.id)}">
        <span class="meta"><span class="dot"></span><span class="src">${esc(it.source)}</span><time>${esc(fmtDate(it))}</time>${isNew ? '<span class="new">NEW</span>' : ""}${fit ? '<span class="fit">★ 맞춤</span>' : ""}</span>
        <span class="title">${esc(it.title)}</span>
        ${it.extra ? `<span class="extra">${esc(it.extra)}</span>` : ""}
        ${tags}
      </a>
      <div class="side">${ddBadge(it.deadline, it.deadline_src === "page")}
        <button class="star" data-star="${esc(it.id)}" aria-pressed="${starred}" aria-label="${starred ? "저장 해제" : "저장"}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/></svg>
        </button></div>
    </article>`;
  }

  function renderChips(items) {
    const cats = S.data?.categories || CAT_FALLBACK;
    const count = (id) => items.filter((x) => id === "all" || x.category === id).length;
    $("#chips").innerHTML = [{ id: "all", name: "전체" }, ...cats].map((c) =>
      `<button class="chip c-${c.id}" data-cat="${c.id}" aria-pressed="${S.cat === c.id}">${c.id !== "all" ? '<span class="dot"></span>' : ""}${esc(c.name)} <span class="n">${count(c.id)}</span></button>`).join("");
  }

  // 게시일이 있으면 게시일, 없으면 처음 발견한 날
  // (처음 설치 때 이미 있던 글은 게시일이 없으면 맨 아래로)
  const dayOf = (it) => it.date || (it.baseline ? "" : (it.first_seen || "").slice(0, 10));

  function groupByDay(items) {
    items = [...items].sort((a, b) => dayOf(b).localeCompare(dayOf(a)) || (b.first_seen || "").localeCompare(a.first_seen || ""));
    const t = today(), out = [];
    const label = (it) => {
      const d = parseDay(dayOf(it) || "1970-01-01");
      const n = Math.round((t - d) / 864e5);
      return n <= 0 ? "오늘" : n === 1 ? "어제" : n < 7 ? "최근 7일" : n < 31 ? "최근 한 달" : "그 이전";
    };
    for (const it of items) {
      const l = label(it);
      if (!out.length || out[out.length - 1].l !== l) out.push({ l, items: [] });
      out[out.length - 1].items.push(it);
    }
    return out;
  }

  function render() {
    const info = S.view === "info";
    $("#searchBox").hidden = info; $("#chips").hidden = info; $("#tools").hidden = info;
    document.querySelectorAll("nav button").forEach((b) => {
      if (b.dataset.view === S.view) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    $("#hidePast").closest(".toggle").hidden = S.view !== "feed";
    $("#onlyFit").closest(".toggle").hidden = S.view === "saved";
    const dueN = (S.data?.items || []).filter((x) => x.deadline && daysLeft(x.deadline) >= 0 && daysLeft(x.deadline) <= 7).length;
    $("#dueBadge").hidden = !dueN; $("#dueBadge").textContent = dueN;
    if (info) return renderInfo();

    const all = base();
    renderChips(all);
    const items = all.filter((x) => S.cat === "all" || x.category === S.cat);
    $("#count").textContent = `${items.length}건`;
    const v = $("#view");
    if (!S.data) { v.innerHTML = `<div class="empty"><strong>소식을 불러오는 중입니다</strong>잠시만 기다려 주세요.</div>`; return; }
    if (!items.length) {
      const msg = S.view === "saved" ? ["저장한 글이 없습니다", "글 오른쪽 ☆를 누르면 여기에 모입니다."]
        : S.onlyFit ? ["★ 맞춤 글이 없습니다", "‘맞춤만’을 끄면 전체가 보입니다. 맞춤 기준은 config.yaml 의 interests 에서 고칩니다."]
        : S.view === "due" ? ["마감일이 확인된 공고가 없습니다", "제목이나 공고 본문에서 마감일을 읽은 공고만 이곳에 나옵니다."]
        : S.q ? ["검색 결과가 없습니다", "다른 단어로 찾아보거나 분류를 ‘전체’로 바꿔 보세요."]
        : ["이 분류에는 아직 소식이 없습니다", "새 공고가 올라오면 알림과 함께 여기에 쌓입니다."];
      v.innerHTML = `<div class="empty"><strong>${msg[0]}</strong>${msg[1]}</div>`; return;
    }
    if (S.view === "feed") {
      v.innerHTML = groupByDay(items).map((g) => `<div class="sec">${g.l}</div><div class="list">${g.items.map(card).join("")}</div>`).join("");
    } else {
      v.innerHTML = `<div class="sec">${S.view === "due" ? "마감 가까운 순" : "저장한 글"}</div><div class="list">${items.map(card).join("")}</div>`;
    }
  }

  function renderInfo() {
    const d = S.data;
    const byCat = (d?.categories || CAT_FALLBACK).map((c) => `<p style="margin-top:12px"><strong style="color:var(--ink)">${esc(c.name)}</strong></p><ul class="srcs">${(d?.sources || []).filter((s) => s.category === c.id).map((s) =>
      `<li class="c-${esc(s.category)}"><span class="dot" style="width:8px;height:8px;border-radius:50%"></span>${esc(s.name)}<span class="st${s.error ? " err" : s.pc_only ? " pc" : ""}" title="${esc(s.error || (s.pc_only ? "해외 서버 접속을 막는 사이트 — PC에서 monitor.py 를 돌릴 때만 확인합니다" : ""))}">${s.error ? "확인 실패" : s.pc_only ? "PC 전용" : "정상"}</span></li>`).join("")}</ul>`).join("");
    const ics = new URL("data/deadlines.ics", location.href);
    const webcal = ics.href.replace(/^https?:/, "webcal:");
    $("#view").innerHTML = `<div class="info">
      <section class="panel"><h2>핸드폰 푸시 알림 받기</h2>
        <ol><li>앱스토어·플레이스토어에서 <code>ntfy</code> 앱을 설치합니다.</li>
        <li>앱에서 <b>+</b> → <b>Subscribe to topic</b> → 설정할 때 받은 토픽 이름을 입력합니다.</li>
        <li>새 공고가 올라오면 알림이 오고, 누르면 원문이, ‘앱에서 보기’를 누르면 이 화면이 열립니다.</li></ol>
      </section>
      <section class="panel"><h2>마감을 내 캘린더에</h2>
        <p>마감이 남은 공고가 하루짜리 일정으로 들어옵니다(‘대상 아님’ 제외). 한 번 구독하면 새 마감이 자동으로 추가됩니다.</p>
        <p style="margin-top:8px"><a class="btn" href="${esc(webcal)}">캘린더 구독</a></p>
        <p style="margin-top:8px">Google 캘린더는 <b>다른 캘린더 + → URL로 추가</b>에 이 주소를 넣습니다.<br><code style="word-break:break-all">${esc(ics.href)}</code></p>
        <p style="margin-top:8px">일정 제목의 <b>(추정)</b>과 목록의 <b>≈D-5</b>는 공고 본문에서 읽은 날짜입니다. 지원 전에 원문에서 확인하세요.</p>
      </section>
      <section class="panel"><h2>★ 맞춤 · 대상 아님</h2>
        <p><b>★ 맞춤</b>은 학생 대상이거나 관심 분야(연구 방법·의사과학자·심장·감염·의료 AI)에 걸린 글입니다. 푸시도 ★ 가 먼저 옵니다.
        기업·전문의 대상처럼 <b>대상 아님</b>으로 분류된 글은 흐리게 보이고 푸시하지 않습니다. 기준 단어는 <code>config.yaml</code> 의 <code>interests</code> 에서 고칩니다.</p>
      </section>
      <section class="panel"><h2>홈 화면에 앱으로 추가</h2>
        <p>iPhone은 Safari 공유 버튼 → <b>홈 화면에 추가</b>, Android는 Chrome 메뉴 → <b>앱 설치</b>를 누르면 일반 앱처럼 열립니다. 인터넷이 없을 때도 마지막으로 받은 목록을 볼 수 있습니다.</p>
      </section>
      <section class="panel"><h2>확인하는 곳 <span class="upd">${d ? esc(d.sources.length) + "곳" : ""}</span></h2>${byCat || "<p>불러오는 중…</p>"}
        <p style="margin-top:12px">3시간마다 자동으로 확인합니다. 사이트 구조가 바뀌면 ‘확인 실패’로 표시됩니다.</p>
      </section></div>`;
  }

  /* ---------------- 데이터 ---------------- */
  function rel(iso) {
    const t = new Date(iso); const m = Math.round((Date.now() - t) / 6e4);
    return m < 1 ? "방금" : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.round(m / 60)}시간 전` : `${Math.round(m / 1440)}일 전`;
  }
  async function load() {
    $("#refresh").classList.add("spin");
    try {
      const r = await fetch("data/items.json?t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      S.data = await r.json();
      $("#upd").textContent = `${rel(S.data.updated)} 업데이트 · ${S.data.items.length}건`;
      $("#banner").innerHTML = "";
      const newest = S.data.items.reduce((m, x) => (x.first_seen > m ? x.first_seen : m), "");
      if (S.seenUntil == null) S.seenUntil = newest;     // 첫 방문: NEW 표시 없이 시작
      store.set("seenUntil", newest);                     // 다음 방문 기준
    } catch (e) {
      $("#banner").innerHTML = `<div class="banner">새 소식을 받아오지 못했습니다. 인터넷 연결을 확인한 뒤 새로고침을 눌러 주세요.</div>`;
      if (!S.data) $("#upd").textContent = "연결 안 됨";
    } finally {
      $("#refresh").classList.remove("spin");
      render();
    }
  }

  /* ---------------- 이벤트 ---------------- */
  document.addEventListener("click", (e) => {
    const star = e.target.closest("[data-star]");
    if (star) {
      const id = star.dataset.star;
      if (S.stars.has(id)) { S.stars.delete(id); delete S.starItems[id]; }
      else { S.stars.add(id); const it = S.data?.items.find((x) => x.id === id); if (it) S.starItems[id] = it; }
      store.set("stars", [...S.stars]); store.set("starItems", S.starItems);
      render(); return;
    }
    const a = e.target.closest("a[data-id]");
    if (a) { S.read.add(a.dataset.id); store.set("read", [...S.read].slice(-2000)); setTimeout(render, 300); return; }
    const chip = e.target.closest("[data-cat]");
    if (chip) { S.cat = chip.dataset.cat; store.set("cat", S.cat); render(); return; }
    const nav = e.target.closest("nav [data-view]");
    if (nav) { S.view = nav.dataset.view; render(); window.scrollTo({ top: 0 }); }
  });
  $("#q").addEventListener("input", (e) => { S.q = e.target.value; render(); });
  $("#hidePast").checked = S.hidePast;
  $("#hidePast").addEventListener("change", (e) => { S.hidePast = e.target.checked; store.set("hidePast", S.hidePast); render(); });
  $("#onlyFit").checked = S.onlyFit;
  $("#onlyFit").addEventListener("change", (e) => { S.onlyFit = e.target.checked; store.set("onlyFit", S.onlyFit); render(); });
  $("#refresh").addEventListener("click", load);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  render();
  load();
})();
