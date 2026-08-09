// Odds Screen Bet Bridge — overlay core (pure DOM logic, testable).
// Loaded by the Tampermonkey userscript and by the Playwright harness.
// DOM map per betconstruct-sportsbook-scraping skill (PokerBet/BetConstruct).
(function (global) {
  "use strict";

  const STATE = { busy: false, abort: false, lastError: null, pollMs: 2000 };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const txt = (el) => (el.innerText || el.textContent || "").trim();
  const ODDS_RE = /^\d+\.\d{2}$/;

  function findText(selector, re) {
    const els = Array.from(document.querySelectorAll(selector));
    return els.find((el) => re.test(txt(el))) || null;
  }

  // ---- event navigation -------------------------------------------------
  function findEventRow(home, away) {
    const rows = Array.from(document.querySelectorAll('[class*="event"], [class*="row"]'));
    return rows.find((r) => {
      const t = txt(r);
      return t.includes(home) && t.includes(away);
    }) || null;
  }

  async function openEventView(row) {
    const clickable = row.querySelector('[onclick], [class*="clickable"], a, [role="button"]');
    if (!clickable) return false;
    clickable.click();
    return true;
  }

  function clickTab(name) {
    const tab = findText('[class*="tab"], button, [role="tab"]', new RegExp("^\\s*" + name + "\\s*$", "i"));
    if (!tab) return false;
    tab.click();
    return true;
  }

  // ft -> "Total Points" (game totals); qN -> "{N}th Quarter Total Points"
  function marketHeader(period) {
    if (period === "ft") return /^\s*Total Points\s*$/;
    const names = { q1: "1st", q2: "2nd", q3: "3rd", q4: "4th" };
    return new RegExp("^\\s*" + names[period] + " Quarter Total Points\\s*$");
  }

  function findMarketSection(period) {
    const header = findText("div, span, h1, h2, h3, h4", marketHeader(period));
    if (!header) return null;
    let node = header;
    for (let i = 0; i < 6 && node; i++) {
      if (node.querySelectorAll("button, [class*='odd'], [class*='coef'], [class*='price']").length >= 2) {
        return node;
      }
      node = node.parentElement;
    }
    return header.parentElement;
  }

  // BetConstruct totals row layout: [line "222.5"] [over odds] [under odds] ...
  // Returns the odds element for the requested side at the requested line.
  function findOddsButton(section, line, side) {
    const want = new RegExp("^\\s*" + String(line).replace(".", "\\.") + "\\s*$");
    const leaf = (el) => el.children.length === 0;
    const oddsEls = Array.from(section.querySelectorAll("div, span, button, a"))
      .filter((el) => leaf(el) && ODDS_RE.test(txt(el)));
    for (const oddsEl of oddsEls) {
      let node = oddsEl.parentElement;
      for (let i = 0; i < 4 && node; i++) {
        const lineEl = findTextIn(node, want);
        if (lineEl) {
          const rowEls = Array.from(node.querySelectorAll("div, span, button, a"));
          const later = rowEls.slice(rowEls.indexOf(lineEl) + 1)
            .filter((el) => leaf(el) && ODDS_RE.test(txt(el)));
          const isOver = later.indexOf(oddsEl) === 0;
          if ((side === "over" && isOver) || (side === "under" && !isOver)) return oddsEl;
        }
        node = node.parentElement;
      }
    }
    return null;
  }

  function findTextIn(root, re) {
    const els = Array.from(root.querySelectorAll("div, span, button, a"));
    return els.find((el) => el.children.length === 0 && re.test(txt(el))) || null;
  }

  // ---- bet slip ----------------------------------------------------------
  function slipContainer() {
    return document.querySelector('[class*="slip"], [class*="betslip"], [class*="bet-slip"], [id*="slip"]') || null;
  }

  async function waitForSlipLeg(timeoutMs) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      const slip = slipContainer();
      if (slip && slip.querySelectorAll('[class*="selection"], [class*="leg"], [class*="stake"]').length >= 1) {
        return slip;
      }
      await sleep(250);
    }
    return null;
  }

  function setStake(slip, amount) {
    const num = Array.from(slip.querySelectorAll("input")).find((i) =>
      /(amount|stake|bet)/i.test(i.name + i.placeholder + i.id) && (i.type === "number" || i.type === "text"));
    if (!num) return false;
    num.value = String(amount);
    num.dispatchEvent(new Event("input", { bubbles: true }));
    num.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function slipShows(slip, line, side) {
    const t = txt(slip);
    return t.includes(String(line)) && t.includes(side === "over" ? "Over" : "Under");
  }

  function slipShowsOdds(slip, odds) {
    const t = txt(slip);
    const s = String(odds);
    return t.includes(s) || t.includes(s.replace(/0+$/, ""));
  }

  function findPlaceBetButton(slip) {
    return findText("button, a, [class*='btn'], [type='submit']", /place\s*bet|confirm/i) || null;
  }

  async function waitForToast(timeoutMs) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeoutMs) {
      const el = findText("div, span, [class*='toast'], [class*='notification'], [class*='message']",
        /bet\b.*?(placed|accepted|confirmed|success)|successfully/i);
      if (el) return txt(el);
      await sleep(250);
    }
    return null;
  }

  // ---- one command --------------------------------------------------------
  async function processCommand(cmd, api, opts) {
    opts = opts || {};
    const watchMs = opts.watchMs || (cmd.mode === "manual" ? 600000 : 8000);
    const report = (status, reason) => api.report({ bet_id: cmd.bet_id, status, reason });

    const row = findEventRow(cmd.home_team, cmd.away_team);
    if (!row) return report("failed", "event not found on page");
    if (!(await openEventView(row))) return report("failed", "could not open event view");
    await sleep(600);

    const tabName = cmd.period === "ft" ? "Match" : "Quarters";
    if (!clickTab(tabName)) return report("failed", "market tab not found: " + tabName);
    await sleep(500);

    const section = findMarketSection(cmd.period);
    if (!section) return report("failed", "market section not found: " + cmd.period);

    const btn = findOddsButton(section, cmd.line_value, cmd.side);
    if (!btn) return report("failed", "odds button not found: " + cmd.side + " " + cmd.line_value);
    btn.click();
    await sleep(400);

    const slip = await waitForSlipLeg(5000);
    if (!slip) return report("failed", "bet slip did not populate");
    if (!slipShows(slip, cmd.line_value, cmd.side)) return report("failed", "slip leg mismatch");
    if (!setStake(slip, cmd.stake)) return report("failed", "stake input not found on slip");

    await report("delivered");

    if (cmd.mode === "auto") {
      if (!slipShowsOdds(slip, cmd.odds_at_request)) return report("failed", "odds moved since request");
      const place = findPlaceBetButton(slip);
      if (!place) return report("failed", "place bet button not found");
      place.click();
      return (await waitForToast(watchMs))
        ? report("confirmed")
        : report("failed", "no confirmation toast after placing");
    }

    // manual: slip stays populated for the user to confirm on PokerBet
    const toast = await waitForToast(watchMs);
    return toast ? report("confirmed") : null; // timed out — leave as delivered
  }

  async function tick(api) {
    if (STATE.busy) return;
    STATE.busy = true;
    try {
      const cmds = (await api.commands()) || [];
      for (const cmd of cmds) {
        await processCommand(cmd, api);
        if (STATE.abort) break;
      }
    } catch (err) {
      STATE.lastError = String(err);
    } finally {
      STATE.busy = false;
    }
  }

  function start(api, pollMs) {
    STATE.pollMs = pollMs || STATE.pollMs;
    setInterval(() => tick(api), STATE.pollMs);
    tick(api);
  }

  global.OddsScreenBridge = {
    STATE, start, tick, processCommand,
    findEventRow, openEventView, clickTab, findMarketSection, findOddsButton,
    slipContainer, waitForSlipLeg, setStake, slipShows, slipShowsOdds,
    findPlaceBetButton, waitForToast,
  };
})(window);
