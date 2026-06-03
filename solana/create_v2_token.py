#!/usr/bin/env python3
"""
SIMP V2 Token — Public-Facing Token2022 Mint Creation Script.
Creates a new Token2022 mint with metadata for the public SIMP token.

Usage:
    python3 create_v2_token.py [--keypair PATH] [--url mainnet-beta|devnet|localhost]

This script:
  1. Generates a new mint keypair
  2. Creates Token2022 mint with metadata extension (name, symbol, URI)
  3. Mints initial supply to treasury
  4. Optionally disables mint authority

Prerequisites:
    - spl-token CLI (comes with Solana CLI tools)
    - ~0.015 SOL for rent-exempt accounts
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RPC = "https://solana-mainnet.g.alchemy.com/v2/mDKvlGo6XpFKJWGDWc7R0dUjoIsxYjWW"

# V2 Token parameters
V2_NAME = "SIMP Protocol"
V2_SYMBOL = "SIMP"
V2_DECIMALS = 6
V2_SUPPLY = 1_000_000_000  # 1 billion
# TODO: Host metadata JSON properly (IPFS, Arweave, or PTAI server)
V2_URI = "https://ptai.systems/tokens/simp/v2.json"
V2_UPDATE_AUTHORITY = "HYmZ74WydHkUeVAHn4H63UwCrQAtovGc7YJwtxcmS8Fj"  # PTAI


def run_cmd(cmd, description="", timeout=120):
    """Run a shell command and return output."""
    print(f"  → {description or ' '.join(cmd[:4])}...")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            print(f"  ⚠  {result.stderr[:300]}")
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        print(f"  ⚠  Timed out")
        return "", "TIMEOUT", -1


def main():
    parser = argparse.ArgumentParser(description="Create SIMP V2 Token (Token2022)")
    parser.add_argument("--keypair", default=None, help="Treasury keypair path")
    parser.add_argument("--url", default="mainnet-beta", help="Solana cluster")
    parser.add_argument("--no-mint", action="store_true", help="Skip minting initial supply")
    parser.add_argument("--no-disable", action="store_true", help="Don't disable mint authority")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("🌟 SIMP V2 TOKEN CREATION (Token2022)")
    print("="*60)

    # ------------------------------------------------------------------
    # Resolve keypair
    # ------------------------------------------------------------------
    if args.keypair:
        treasury_kp = args.keypair
    else:
        # Try PTAI keypair
        ptai_path = Path("/tmp/simp_ptai_keypair.json")
        if ptai_path.exists():
            treasury_kp = str(ptai_path)
        else:
            config_out, _, _ = run_cmd(["solana", "config", "get"], "Get solana config")
            treasury_kp = ""
            for line in config_out.split("\n"):
                if "Keypair Path" in line:
                    treasury_kp = line.split(":")[-1].strip()
                    break

    if not treasury_kp or not Path(treasury_kp).exists():
        print("❌ No keypair found.")
        print("  Use --keypair or set solana config keypair.")
        sys.exit(1)

    # Get treasury address
    stdout, _, rc = run_cmd(
        ["solana", "address", "--keypair", treasury_kp, "-u", args.url],
        "Get treasury address",
    )
    treasury_address = stdout.strip()
    print(f"\n🏦 Treasury: {treasury_address} ({treasury_kp})")

    # Check balance
    stdout, _, _ = run_cmd(
        ["solana", "balance", "--keypair", treasury_kp, "-u", args.url],
        "Check balance",
    )
    print(f"💰 Balance: {stdout}")

    # ------------------------------------------------------------------
    # Generate mint keypair
    # ------------------------------------------------------------------
    mint_kp = REPO_ROOT / "programs" / "token" / "target" / "deploy" / "simp_v2-keypair.json"
    mint_kp.parent.mkdir(parents=True, exist_ok=True)

    if mint_kp.exists():
        print(f"\n📋 Using existing mint keypair: {mint_kp}")
    else:
        print(f"\n🔑 Generating mint keypair...")
        run_cmd(
            ["solana-keygen", "new", "--no-bip39-passphrase", "--force", "-o", str(mint_kp)],
            "Generate mint keypair",
        )

    # Read mint address
    stdout, _, rc = run_cmd(
        ["solana-keygen", "pubkey", str(mint_kp)],
        "Read mint address",
    )
    mint_address = stdout.strip()
    print(f"📋 V2 Mint Address: {mint_address}")

    if args.dry_run:
        print("\n🔍 DRY RUN — Commands that would be executed:")
        print(f"  spl-token --program-2022 create-token {mint_kp} --decimals {V2_DECIMALS} --enable-metadata")
        print(f"  spl-token --program-2022 create-account {mint_address} --owner {treasury_address}")
        print(f"  spl-token --program-2022 mint {mint_address} {V2_SUPPLY * (10**V2_DECIMALS)}")
        print(f"  spl-token --program-2022 initialize-metadata {mint_address} '{V2_NAME}' '{V2_SYMBOL}' '{V2_URI}'")
        if not args.no_disable:
            print(f"  spl-token --program-2022 authorize {mint_address} mint --disable")
        return

    # ------------------------------------------------------------------
    # Step 1: Create the Token2022 mint with metadata extension
    # ------------------------------------------------------------------
    print(f"\n🚀 Step 1: Create Token2022 mint with metadata extension...")
    stdout, stderr, rc = run_cmd(
        [
            "spl-token", "--program-2022", "create-token",
            str(mint_kp),
            "--decimals", str(V2_DECIMALS),
            "--enable-metadata",
            "-u", args.url,
            "--fee-payer", treasury_kp,
        ],
        "Create Token2022 mint",
        timeout=60,
    )
    if rc != 0 and "already in use" not in stderr:
        print(f"❌ Failed: {stderr}")
        sys.exit(1)
    print(f"  ✅ Mint created: {mint_address}")
    print(stdout[:300])

    # ------------------------------------------------------------------
    # Step 2: Create treasury token account
    # ------------------------------------------------------------------
    print(f"\n🚀 Step 2: Create treasury token account...")
    stdout, stderr, rc = run_cmd(
        [
            "spl-token", "--program-2022", "create-account",
            mint_address,
            "--owner", treasury_address,
            "-u", args.url,
            "--fee-payer", treasury_kp,
        ],
        "Create treasury token account",
        timeout=60,
    )
    if rc != 0 and "already exists" not in stderr:
        print(f"⚠  {stderr[:200]}")
    else:
        print(f"  ✅ Treasury account created")
        print(stdout[:300])

    # ------------------------------------------------------------------
    # Step 3: Initialize metadata
    # ------------------------------------------------------------------
    print(f"\n🚀 Step 3: Initialize metadata...")
    stdout, stderr, rc = run_cmd(
        [
            "spl-token", "--program-2022", "initialize-metadata",
            mint_address,
            V2_NAME,
            V2_SYMBOL,
            V2_URI,
            "--update-authority", V2_UPDATE_AUTHORITY,
            "-u", args.url,
            "--fee-payer", treasury_kp,
            "--mint-authority", treasury_kp,
        ],
        "Initialize metadata",
        timeout=60,
    )
    if rc != 0 and "already" not in stderr.lower():
        print(f"⚠  {stderr[:200]}")
    else:
        print(f"  ✅ Metadata initialized")
        print(f"     Name:   {V2_NAME}")
        print(f"     Symbol: {V2_SYMBOL}")
        print(f"     URI:    {V2_URI}")
        print(stdout[:300])

    # ------------------------------------------------------------------
    # Step 4: Mint initial supply
    # ------------------------------------------------------------------
    if not args.no_mint:
        total_raw = V2_SUPPLY * (10 ** V2_DECIMALS)
        print(f"\n🚀 Step 4: Mint {V2_SUPPLY:,} V2 tokens to treasury...")
        stdout, stderr, rc = run_cmd(
            [
                "spl-token", "--program-2022", "mint",
                mint_address,
                str(total_raw),
                "--recipient-owner", treasury_address,
                "-u", args.url,
                "--fee-payer", treasury_kp,
            ],
            "Mint initial supply",
            timeout=60,
        )
        if rc != 0:
            print(f"⚠  {stderr[:200]}")
        else:
            print(f"  ✅ Minted {V2_SUPPLY:,} V2 to {treasury_address}")
            print(stdout[:300])

    # ------------------------------------------------------------------
    # Step 5: Disable mint authority (optional)
    # ------------------------------------------------------------------
    if not args.no_disable:
        print(f"\n🚀 Step 5: Disable mint authority (permanent)...")
        stdout, stderr, rc = run_cmd(
            [
                "spl-token", "--program-2022", "authorize",
                mint_address,
                "mint",
                "--disable",
                "-u", args.url,
                "--fee-payer", treasury_kp,
            ],
            "Disable mint authority",
            timeout=60,
        )
        if rc != 0:
            print(f"⚠  {stderr[:200]}")
        else:
            print(f"  ✅ Mint authority disabled (supply is now fixed)")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "="*60)
    print("✅ V2 TOKEN CREATION COMPLETE")
    print("="*60)
    print(f"  Mint Address:    {mint_address}")
    print(f"  Token Name:      {V2_NAME}")
    print(f"  Symbol:          {V2_SYMBOL}")
    print(f"  Decimals:        {V2_DECIMALS}")
    print(f"  Supply:          {V2_SUPPLY:,}")
    print(f"  Program:         Token2022 (TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb)")
    print(f"  Metadata:        {V2_URI}")
    print(f"  Update Auth:     {V2_UPDATE_AUTHORITY}")
    print(f"  Mint Auth:       {'DISABLED' if not args.no_disable else 'ENABLED'}")
    print(f"  Treasury:        {treasury_address}")
    print(f"  Keypair:         {mint_kp}")
    print()
    print("  Add to .env:")
    print(f"  SIMP_V2_TOKEN_MINT={mint_address}")
    print(f"  SIMP_V2_TOKEN_DECIMALS={V2_DECIMALS}")
    print(f"  SIMP_V2_TOKEN_SUPPLY={V2_SUPPLY}")
    print("="*60)


if __name__ == "__main__":
    main()
