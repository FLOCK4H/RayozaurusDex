# Rayozaurus Dex

**Raydium DeX Sniper Bot** that catches CLMM, CPMM, Standard AMM, and Pump.fun: Raydium Migration liquidity pool creations, listens for balance changes on their respective pool accounts to calculate real-time price, and checks `Dexscreener` for active boosts.

# Setup

<h4>Libraries</h4>

- Solders=0.21.0
- Solana=0.35.1
- aiohttp
- base64, base58

<h4>Download</h4>

```
  $ git clone https://github.com/FLOCK4H/RayozaurusDex
```

<h4>Before launching</h4>

**Modify `.config` file:**

```
HL_API_KEY=YOUR_API_KEY
WALLET_ADDRESS=YOUR_WALLET_ADDRESS
PRIVATE_KEY=YOUR_PRIVATE_KEY
```

**Change relevant places in code:**

```
-> common_.py
QN_WS = "wss://jupiter-swap-api.quiknode.pro/B6XDDDDDDDD/ws"

-> rayozaur.py
amount = await usd_to_lamports(1, self.swaps.sol_price_usd) if trust_level == 1 else await usd_to_lamports(1, self.swaps.sol_price_usd)
fee = await usd_to_lamports(0.07, self.swaps.sol_price_usd)

When to enter part:
in_entry_range = await self.determine_safe_range(buy_to_sell, price_len)
if "buy_price" not in self.mint_data[mint] and not session_meta["bought"]:
    if in_entry_range and diffs_threshold:
        if change_pct >= 80:

```

# Usage

```
  $ python rayozaur.py
```

# License

Copyright (c) 2025 FLOCK4H

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.