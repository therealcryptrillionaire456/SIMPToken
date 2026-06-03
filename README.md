# SIMPToken — The Agentic Token on Solana

**Token:** `SIMPT`  
**Mint (V2):** `6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW`  
**Network:** Solana Mainnet  
**Standard:** Token-2022 (spl-token-2022)  
**Supply:** 1,000,000,000 SIMPT (mint authority permanently revoked)  
**Website:** [https://simptoken.uk](https://simptoken.uk)

The native token powering the SIMP multi-agent mesh — Structured Intent Messaging Protocol.

## What's in this repo

| Component | Description |
|-----------|-------------|
| `tokens/` | Token economy modules — burn engine, distribution, unified ledger, V1/V2 configs |
| `simpwallet.py` | AI-native state-carrying token explorer — on-chain data, mesh economy, trust graph |
| `simpwallet_fortress.py` | Fortress vault — encrypted key storage, circuit breaker, audit trail |
| `simpwallet_brp.py` | BRP threat intelligence integration — packet screening, trust penalties |
| `dashboard/static/` | Zero-dep JS/CSS dashboard — 7-tab UI, Ledger WebHID, BRP threat display |
| `simp_integration_kernel.js` | Self-contained JS module for embedding SIMPWallet on any website |
| `solana/` | Token creation/deployment scripts |
| `docs/` | Token metadata, logo, architecture docs |

## Quick Start

### Standalone Token Explorer

```bash
# Install dependencies
pip install requests pynacl base58

# Run the explorer
python3 simpwallet.py --standalone
```

### Run the Full Dashboard

```bash
# Python 3.9+ required
pip install -r requirements.txt
python3 -m http.server 8000
# Open http://localhost:8000/dashboard/static/simpwallet_embed.html
```

### Deploy to simptoken.uk

See `DEPLOY_LEDGER.md` for the integration guide.

## V2 Token Details

- **Mint:** `6QxRa9aeCidptKS8CS2uenbQiy5enHR7eMMY29mghZNW`
- **Token Program:** `TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb` (Token-2022)
- **Decimals:** 6
- **Supply:** 1,000,000,000 SIMPT
- **Mint Authority:** Permanently disabled (null)
- **Freeze Authority:** None
- **Metadata:** Embedded on-chain via Token-2022 metadata pointer extension
- **Whale Wallet:** `58EohzqesFaxpRaqgaab7v5f9ZAhBGhzubTNHEHHmPpB`

## Security

See `SECURITY_ARCHITECTURE.md` for the full 9-layer security model including:
- Rate limiting + DDoS protection
- Signed Ed25519 audit trail
- TLS 1.3 + mTLS + cert pinning
- Fortress Vault (encrypted key storage)
- BRP Threat Engine
- Ledger Nano hardware wallet support

## License

Proprietary — All Rights Reserved.
