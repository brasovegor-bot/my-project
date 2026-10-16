# Browser source check (stage 1)

This is a diagnostic Chrome MV3 extension, not a working trade notifier yet.
It reads a small sample of visible GMGN rows for the selected 28 wallets, after
an explicit action click. It requires no GMGN API key, Telegram token, cookies,
network permissions, host access on startup, server or Python on the user's PC.

Permissions: activeTab and scripting. Only https://gmgn.ai or www.gmgn.ai is
accepted by both popup and capture function. The function never clicks, changes
the DOM, mutates follows, reads form values/storage/cookies or makes requests.
Only compact nearby token rows are captured; no complete page HTML is exported.
Captured links lose query/fragment and are restricted to public token/address/tx
paths. Row names, addresses, transactions and amounts remain private user data;
the user explicitly downloads and shares the JSON for development.

Names alone do not prove wallet identity. This version therefore marks wallet
and event identity unverified and never automatically sends a trade. The sample
must establish real wallet address, token address, stable event ID, direction,
quote identity/amount and market-cap meaning before notifications are enabled.
Rows without enough data must be flagged as unavailable or unverified, not
invented. DOM changes, virtualized rows, background throttling, sleeping PC or
closed/hidden tracker can cause missed events; an open browser does not establish
24/7 completeness, realtime detection or historical recovery.

Build private package in the cloud:

```sh
python -m wallet_alerts.build_browser_extension
```

Output `data/gmgn/browser_extension/` contains the extension plus the selected
wallets. Its ZIP and a self-contained install page with in-page download/save
buttons are generated alongside it. The real wallet list stays in ignored data.

User installs unpacked extension through chrome://extensions, Developer mode,
Load unpacked. In the GMGN tab, open Wallet Tracker, show selected-wallet rows,
click the extension, Capture sample, Download JSON. Attach that small JSON to
Codex. No API permissions or trading/follow settings need modification.

Validation: `node tests/test_browser_extension.mjs` exercises two synthetic rows,
excludes unrelated/hidden/form/cookie/query data, rejects non-GMGN hosts, checks no
page clicks, ZIP byte identity, saved-install-page reopening and mobile layout.
It does not establish compatibility with the real GMGN page. Loading the unpacked
extension in this environment's automated Chromium was not verified: command-line
sideload did not load it and the Extensions.loadUnpacked developer method returned
Method not available. No browser policy was changed. The actual manual Chrome
installation and popup capture must be verified with the user.
