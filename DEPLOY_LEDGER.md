# SIMPWallet Ledger Nano — DEPLOYMENT GUIDE
## For simptoken.uk configuration

## Files to deploy:

### 1. FULL SIMPWallet + Ledger (REPLACE "Coming Soon")
File: `dashboard/static/simpwallet_embed.html`
- 969 lines — full dashboard + Ledger Nano integration
- Paste the ENTIRE file content into the section where "Wallet: Coming Soon" currently sits
- Auto-renders live token data, mesh state, trust graph, whale wallet, and Ledger connect
- Falls back to cached data if broker is offline
- Zero dependencies (no CDN, no libraries)
- Works in Chrome/Edge/Brave/Opera
- Paste before `</body>` tag

### 2. Ledger Nano Only (if you already have a wallet section)
File: `dashboard/static/ledger_nano_embed.html`
- 370 lines — pure Ledger Nano hardware wallet interface
- Smaller, focused only on hardware wallet connect/verify/sign
- Paste anywhere you want a "Connect Ledger" section
- Three-step visual setup guide included

### 3. If you need a script reference instead of inline:
File: `dashboard/static/simpledger_webhid.js`
- 737 lines — full WebHID library (LedgerDevice + SolanaApp classes)
- Load as: `<script src="/path/to/simpledger_webhid.js"></script>`
- Then use: `SIMPLedger.connect()` / `SIMPLedger.getAddress()` / `SIMPLedger.proveOwnership()`

## What users experience:

1. User visits simptoken.uk
2. Scrolls to SIMPWallet section
3. Sees LIVE data: SIMPT supply, holders, whale wallet, mesh agents, trust graph
4. Clicks "Connect Ledger Nano"
5. Browser shows HID permission prompt
6. User selects their Ledger Nano from the list
7. User approves on their Ledger (PIN + Solana app open)
8. SIMPT address appears instantly
9. User can click "Verify Address" — shows on Ledger screen
10. User can click "Sign Proof" — proves ownership without exposing key

## Broker dependency:
The live data requires the SIMP broker running on port 5555 with TLS.
If the broker is offline, the wallet shows cached/demo data with an "Offline" indicator.
The Ledger Nano connect/verify works regardless of broker status.

## Browser support:
- ✅ Chrome 89+ (recommended)
- ✅ Edge 89+
- ✅ Brave 1.3+
- ✅ Opera 75+
- ❌ Firefox (no WebHID)
- ❌ Safari (no WebHID)
