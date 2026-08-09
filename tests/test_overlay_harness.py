"""Playwright harness for the bet bridge overlay core.

Loads bridge/overlay-core.js (the exact shipped artifact) into a fixture page
replicating the BetConstruct DOM documented in the
betconstruct-sportsbook-scraping skill: event listing row, event view with
Match/Quarters tabs, Total Points O/U sections, bet slip with amount input,
Place Bet button and toast area.

Skipped if playwright isn't installed (host .venv only).
"""
import pathlib

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright

REPO = pathlib.Path(__file__).resolve().parent.parent
CORE = (REPO / "bridge" / "overlay-core.js").read_text()

FIXTURE = """<!doctype html><html><body>
<div id="listing">
  <div class="event-row" id="row-lakers">
    <span class="team">Lakers</span><span class="score">72</span>
    <span class="team">Celtics</span><span class="score">68</span>
    <div class="clickable" onclick="openEventView()">expand</div>
  </div>
</div>
<div id="event-view" style="display:none">
  <div class="horizontal-sl-tab-bc">All</div>
  <div class="horizontal-sl-tab-bc">Match</div>
  <div class="horizontal-sl-tab-bc">Quarters</div>
  <div id="match-panel">
    <div class="market-section">
      <div class="market-title">Total Points</div>
      <div class="ou-row"><span class="line">222.5</span><button class="odds">1.85</button><button class="odds">1.90</button></div>
      <div class="ou-row"><span class="line">223.5</span><button class="odds">1.80</button><button class="odds">1.85</button></div>
    </div>
  </div>
  <div id="quarters-panel" style="display:none">
    <div class="market-section">
      <div class="market-title">3rd Quarter Total Points</div>
      <div class="ou-row"><span class="line">52.5</span><button class="odds">1.85</button><button class="odds">1.90</button></div>
    </div>
  </div>
</div>
<div id="betslip" class="betslip-panel" style="display:none">
  <div class="slip-leg">(empty)</div>
  <input type="number" name="amount" placeholder="Amount" />
  <button id="place-bet">Place Bet</button>
</div>
<div id="toasts"></div>
<script>
function openEventView() { document.getElementById('event-view').style.display = 'block'; }
document.querySelectorAll('.odds').forEach(b => {
  b.addEventListener('click', () => {
    const row = b.closest('.ou-row');
    const line = row.querySelector('.line').textContent;
    const side = row.querySelectorAll('.odds')[0] === b ? 'Over' : 'Under';
    const slip = document.getElementById('betslip');
    slip.style.display = 'block';
    slip.querySelector('.slip-leg').textContent =
      'Lakers vs Celtics — ' + side + ' ' + line + ' @ ' + b.textContent;
  });
});
document.querySelectorAll('.horizontal-sl-tab-bc').forEach(t => {
  t.addEventListener('click', () => {
    const name = t.textContent.trim();
    document.getElementById('match-panel').style.display = name === 'Match' ? 'block' : 'none';
    document.getElementById('quarters-panel').style.display = name === 'Quarters' ? 'block' : 'none';
  });
});
</script></body></html>"""

RESET = """() => {
  document.getElementById('event-view').style.display = 'none';
  document.getElementById('betslip').style.display = 'none';
  document.querySelector('.slip-leg').textContent = '(empty)';
  document.getElementById('toasts').innerHTML = '';
}"""


REPORT_SLOTS = {}


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page()
        pg.set_content(FIXTURE)
        pg.add_script_tag(content=CORE)
        # slot-addressed push: a lingering background watcher from a previous
        # test can only write into its own test's list, never the current one
        pg.expose_function("__reportPush", lambda p, slot_id: REPORT_SLOTS[slot_id].append(p))
        yield pg
        browser.close()


def report_api():
    """Fresh reports list + slot id; build the page api as {report: (p) => __reportPush(p, slot)}."""
    slot = f"s{len(REPORT_SLOTS)}"
    reports = []
    REPORT_SLOTS[slot] = reports
    return reports, slot


API_JS = "{report: (p) => __reportPush(p, a.slot)}"


def test_find_odds_button_over_2235(page):
    found = page.evaluate("""() => {
      const section = OddsScreenBridge.findMarketSection('ft');
      const btn = OddsScreenBridge.findOddsButton(section, 223.5, 'over');
      return btn ? btn.textContent.trim() : null;
    }""")
    assert found == "1.80"


def test_find_odds_button_under_2225(page):
    found = page.evaluate("""() => {
      const section = OddsScreenBridge.findMarketSection('ft');
      const btn = OddsScreenBridge.findOddsButton(section, 222.5, 'under');
      return btn ? btn.textContent.trim() : null;
    }""")
    assert found == "1.90"


def test_find_quarter_section(page):
    found = page.evaluate("""() => {
      const section = OddsScreenBridge.findMarketSection('q3');
      const btn = OddsScreenBridge.findOddsButton(section, 52.5, 'over');
      return btn ? btn.textContent.trim() : null;
    }""")
    assert found == "1.85"


def test_set_stake(page):
    ok = page.evaluate("""() => {
      const slip = document.querySelector('.betslip-panel');
      return OddsScreenBridge.setStake(slip, 50);
    }""")
    assert ok is True
    assert page.input_value('input[name="amount"]') == "50"


def test_manual_flow_delivered_then_confirmed(page):
    page.evaluate(RESET)
    reports, slot = report_api()
    cmd = {"bet_id": 7, "side": "over", "line_value": 223.5, "odds_at_request": 1.80,
           "stake": 50, "mode": "manual", "home_team": "Lakers", "away_team": "Celtics",
           "period": "ft", "market_type": "total_points"}
    # fire-and-forget: the manual branch watches the slip in the background
    page.evaluate("""(a) => {
      OddsScreenBridge.processCommand(a.cmd, {report: (p) => __reportPush(p, a.slot)}, a.opts);
      return 'started';
    }""", {"cmd": cmd, "slot": slot, "opts": {"watchMs": 5000}})
    page.wait_for_timeout(2500)  # processCommand sleeps: 600 + 500 + 400 + slip poll
    assert reports == [{"bet_id": 7, "status": "delivered", "reason": None}]

    # user confirms on PokerBet -> toast -> bridge reports confirmed
    page.click("#place-bet")
    page.evaluate("""() => {
      const t = document.createElement('div');
      t.className = 'notification';
      t.textContent = 'Bet placed successfully';
      document.getElementById('toasts').appendChild(t);
    }""")
    page.wait_for_timeout(1500)
    assert reports[-1] == {"bet_id": 7, "status": "confirmed", "reason": None}


def test_auto_mode_clicks_place_and_confirms(page):
    page.evaluate(RESET)
    reports, slot = report_api()
    cmd = {"bet_id": 8, "side": "under", "line_value": 222.5, "odds_at_request": 1.90,
           "stake": 100, "mode": "auto", "home_team": "Lakers", "away_team": "Celtics",
           "period": "ft", "market_type": "total_points"}
    page.evaluate("""() => {
      const btn = document.getElementById('place-bet');
      btn.addEventListener('click', () => {
        const t = document.createElement('div');
        t.className = 'notification';
        t.textContent = 'Your bet has been accepted';
        document.getElementById('toasts').appendChild(t);
      }, { once: true });
    }""")
    page.evaluate("""(a) => OddsScreenBridge.processCommand(a.cmd, {report: (p) => __reportPush(p, a.slot)}, a.opts)""",
                  {"cmd": cmd, "slot": slot, "opts": {"watchMs": 3000}})
    assert reports == [
        {"bet_id": 8, "status": "delivered", "reason": None},
        {"bet_id": 8, "status": "confirmed", "reason": None},
    ]


def test_auto_mode_odds_moved_aborts(page):
    page.evaluate(RESET)
    reports, slot = report_api()
    cmd = {"bet_id": 9, "side": "over", "line_value": 223.5, "odds_at_request": 1.85,
           "stake": 50, "mode": "auto", "home_team": "Lakers", "away_team": "Celtics",
           "period": "ft", "market_type": "total_points"}
    page.evaluate("""(a) => OddsScreenBridge.processCommand(a.cmd, {report: (p) => __reportPush(p, a.slot)}, a.opts)""",
                  {"cmd": cmd, "slot": slot, "opts": {"watchMs": 1500}})
    # slip shows 1.80 but request was priced at 1.85 -> delivered (slip filled),
    # then auto-verify aborts: never clicked Place Bet
    assert reports == [
        {"bet_id": 9, "status": "delivered", "reason": None},
        {"bet_id": 9, "status": "failed", "reason": "odds moved since request"},
    ]


def test_event_not_found_fails_cleanly(page):
    reports, slot = report_api()
    cmd = {"bet_id": 10, "side": "over", "line_value": 223.5, "odds_at_request": 1.80,
           "stake": 50, "mode": "manual", "home_team": "Knicks", "away_team": "Nets",
           "period": "ft", "market_type": "total_points"}
    page.evaluate("""(a) => OddsScreenBridge.processCommand(a.cmd, {report: (p) => __reportPush(p, a.slot)}, a.opts)""",
                  {"cmd": cmd, "slot": slot, "opts": {"watchMs": 500}})
    assert reports == [{"bet_id": 10, "status": "failed", "reason": "event not found on page"}]
