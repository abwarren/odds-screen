// ==UserScript==
// @name         Odds Screen Bet Bridge
// @namespace    https://odds-screen.local
// @version      0.1.0
// @description  Pulls bet commands from the odds screen API and populates the PokerBet bet slip (remote bet placement). Default: manual confirm on PokerBet; auto mode is an explicit opt-in on the request.
// @match        https://www.pokerbet.co.za/en/sports/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      localhost
// @require      file:///home/wa/projects/odds-screen/bridge/overlay-core.js
// ==/UserScript==

// Dev mode: @require points at the local core file (enable "Allow access to
// file URLs" in Tampermonkey). Bundle core + this file for release.
(function () {
  "use strict";
  const API_BASE = "http://localhost:8002";
  const TOKEN_KEY = "oddsScreenBetToken";
  let token = GM_getValue(TOKEN_KEY, "");
  if (!token) {
    token = prompt("Odds Screen API token (BET_TOKEN from docker-compose):");
    if (token) GM_setValue(TOKEN_KEY, token);
  }

  const api = {
    commands() {
      return new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
          method: "GET",
          url: API_BASE + "/bridge/commands?bookmaker=pokerbet",
          headers: { "X-Bet-Token": token },
          onload: (r) => { try { resolve(JSON.parse(r.responseText).commands || []); } catch (e) { reject(e); } },
          onerror: reject,
        });
      });
    },
    report(payload) {
      return new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
          method: "POST",
          url: API_BASE + "/bridge/report",
          headers: { "X-Bet-Token": token, "Content-Type": "application/json" },
          data: JSON.stringify(payload),
          onload: resolve,
          onerror: reject,
        });
      });
    },
  };

  window.OddsScreenBridge.start(api, 2000);

  // tiny status chip so you can see the bridge is alive
  const chip = document.createElement("div");
  chip.id = "odds-screen-bridge";
  chip.textContent = "bridge: idle";
  chip.style.cssText = "position:fixed;bottom:8px;right:8px;z-index:99999;background:#111;color:#0f0;font:12px monospace;padding:4px 8px;border-radius:4px;opacity:.85;pointer-events:none";
  document.body.appendChild(chip);
  setInterval(() => {
    const s = window.OddsScreenBridge.STATE;
    if (s.busy) chip.textContent = "bridge: placing…";
    else if (s.lastError) chip.textContent = "bridge: " + s.lastError;
    else chip.textContent = "bridge: idle";
  }, 1000);
})();
