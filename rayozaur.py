import websockets
import asyncio
import json
import logging
import aiohttp
import traceback
from collections import defaultdict
import signal

import time

try:
    from .raycodes import *
    from .common_ import *
    from .colors import *
    from .swaps import *
    from .utils import *
    from .dexscreener import AsyncDex
except ImportError:
    from raycodes import *
    from common_ import *
    from colors import *
    from swaps import *
    from utils import *
    from dexscreener import AsyncDex

cc = ColorCodes()

logging.basicConfig(
    format=f"{cc.GREEN}[DexLab] %(levelname)s - %(message)s{cc.RESET}",
    level=logging.INFO,
)

async def intro():
    print(fr"""{cc.CYAN}{cc.BRIGHT}
{cc.CYAN} ______                                                {cc.LIGHT_BLUE}______          
{cc.CYAN} | ___ \                                               {cc.LIGHT_BLUE}|  _  \         
{cc.CYAN} | |_/ /__ _ _   _  ___ ______ _ _   _ _ __ _   _ ___  {cc.LIGHT_BLUE}| | | |_____  __
{cc.CYAN} |    // _` | | | |/ _ \_  / _` | | | | '__| | | / __| {cc.LIGHT_BLUE}| | | / _ \ \/ /
{cc.CYAN} | |\ \ (_| | |_| | (_) / / (_| | |_| | |  | |_| \__ \ {cc.LIGHT_BLUE}| |/ /  __/>  < 
{cc.CYAN} \_| \_\__,_|\__, |\___/___\__,_|\__,_|_|   \__,_|___/ {cc.LIGHT_BLUE}|___/ \___/_/\_\
{cc.CYAN}              __/ |                                                    
{cc.CYAN}             |___/               {cc.MAGENTA}{cc.BRIGHT}by FLOCK4H
{cc.RESET}
{cc.LIGHT_RED}$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$-$        
{cc.RESET}""")


class DexBetterLogs:
    def __init__(self, rpc_endpoint):
        self.logs = asyncio.Queue()
        self.session = aiohttp.ClientSession()
        self.rpc_endpoint = rpc_endpoint
        self.stop_event = asyncio.Event()
        self.balances = defaultdict(lambda: defaultdict(dict))
        self.subscriptions = {}  # {address: WebSocket object}
        self.mint_data = {}
        self.single_lock = True
        self.active_sessions, self.blacklist, self.active_tasks = set(), set(), set()
        self.pools = {}
        self.dexscreen = AsyncDex(self.session)
        self.boosted_mints = {}
        self.creators = {}

    def load_blacklist(self):
        try:
            with open("blacklist.txt", "r") as f:
                for line in f:
                    self.blacklist.add(line.strip())
        except Exception as e:
            logging.error(f"Error loading blacklist: {e}")

    async def save_tracker(self, result):
        try:
            with open("raydium_market.txt", "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = []

            data.append(result)

            with open("raydium_market.txt", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving result: {e}")

    async def save_result(self, result):
        try:
            os.makedirs("dev", exist_ok=True)
            with open("dev/results.txt", "a", encoding="utf-8") as f:
                f.write(json.dumps(result, indent=2) + "\n")
        except Exception as e:
            logging.error(f"Error saving result: {e}")

    def save_to_blacklist(self, address):
        try:
            logging.info(f"Saving to blacklist: {address}")
            with open("blacklist.txt", "a") as f:
                f.write(f"{address}\n")
        except Exception as e:
            logging.error(f"Error saving to blacklist: {e}")

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self.handle_exit)   # Ctrl+C
        signal.signal(signal.SIGTERM, self.handle_exit)  # Termination signal

    def handle_exit(self, signum, frame):
        """Signal handler for termination."""
        logging.info(f"Signal {signum} received. Shutting down gracefully...")
        self.stop_event.set()
        time.sleep(1)
        sys.exit(0)
            
    async def subscribe_logs(self, program=RLQ4):
        """Subscribe to logs for the specified program."""
        while not self.stop_event.is_set():
            try:
                async with websockets.connect(
                    WS_URL,
                    ping_interval=15,
                    ping_timeout=60,
                    max_size=10**6,
                ) as ws:
                    # Send subscription request
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "method": "logsSubscribe",
                        "params": [{"mentions": [program]}, {"commitment": "processed"}],
                        "id": program,
                    }))

                    response = json.loads(await ws.recv())
                    if 'result' in response:
                        logging.info(f"Response: {response}")
                        logging.info(f"Subscribed to logs for program {program}")
                    else:
                        logging.warning(f"Unexpected response: {response}")
                        continue

                    # Process incoming messages
                    while not self.stop_event.is_set():
                        try:
                            message = await ws.recv()
                            hMessage = json.loads(message)
                            await self.logs.put(hMessage)
                        except json.JSONDecodeError as e:
                            logging.warning(f"JSON decode error, ignoring message: {e}")
                            continue
                        except asyncio.exceptions.IncompleteReadError as e:
                            logging.warning(f"Incomplete message read, ignoring: {e}")
                            continue
                        except websockets.exceptions.ConnectionClosedError as e:
                            logging.warning(f"Connection unexpectedly closed: {e}")
                            break
                        except Exception as e:
                            logging.error(f"Unexpected error while receiving message: {e}")
                            continue

            except websockets.exceptions.ConnectionClosedError as e:
                logging.warning(f"Connection closed unexpectedly during setup: {e}. Retrying...")
            except Exception as e:
                logging.error(f"Unexpected error in logs subscription: {e}")
                traceback.print_exc()

            finally:
                logging.info("Reconnecting in 1 second...")
                await asyncio.sleep(1)

    async def subscribe_to_account(self, address, mint, role=None):
        """Subscribe to updates for a specific account"""
        try:
            async def account_subscription_task():
                async with websockets.connect(WS_URL, ping_interval=1, ping_timeout=15, max_size=10**6) as ws:
                    self.subscriptions[address] = ws
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "method": "accountSubscribe",
                        "params": [address, {"encoding": "jsonParsed", "commitment": "processed"}],
                        "id": address,
                    }))
                    await ws.recv()  # Acknowledge subscription
                    logging.info(f"Subscribed to account {address} as {role}")

                    while not self.stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=60)
                            data = json.loads(message)
                            if "result" in data or "params" in data:
                                result = await self.handle_account_update(data, address, mint, role)
                                if mint in self.pools and self.pools.get(mint, {}).get("sold") is True:
                                    logging.info(f"Unsubscribing due to sell order: {address}")
                                    self.subscriptions.pop(address, None)
                                    break
                        except asyncio.TimeoutError:
                            await ws.ping()
                        except AttributeError as e:
                            logging.error(f"Attribute error: {e}")
                            if mint in self.pools and self.pools.get(mint, {}).get("sold") is False:
                                self.pools[mint]["sold"] = True
                            self.subscriptions.pop(address, None)
                            break
                        except Exception as e:
                            logging.error(f"Error in account subscription for {address}: {e}")
                            if mint in self.pools and self.pools.get(mint, {}).get("sold") is False:
                                self.pools[mint]["sold"] = True
                            break

            asyncio.create_task(account_subscription_task())

        except Exception as e:
            logging.error(f"Subscription failed for {address}: {e}")

    async def buy(self, lp_id, trust_level):
        """Buy Raydium tokens"""
        amount = await usd_to_lamports(1, self.swaps.sol_price_usd) if trust_level == 1 else await usd_to_lamports(1, self.swaps.sol_price_usd)
        fee = await usd_to_lamports(0.07, self.swaps.sol_price_usd)
        if self.dev_balance <= amount + fee:
            logging.info(f"Insufficient balance: {self.dev_balance}")
            return
        ray_tx = await self.swaps.send_ws_transaction(lp_id, amount, fee)
        if ray_tx == "QuoteUnavailable":
            return "QuoteUnavailable"
        logging.info(f"Raydium buy order: {ray_tx}")
        result = await self.swaps.get_swap_tx(ray_tx, lp_id)
        # if result == "InstructionError":
        #     return await self.buy(lp_id, trust_level)
        await self.save_result({"timestamp": time.time(), "buy": result, "amount": amount, "fee": fee, "mint": lp_id, "trust_level": trust_level})
        token_amount = result.get("balance", 0)
        return token_amount
    
    async def sell(self, lp_id, amount, our_change_pct):
        """Sell Raydium tokens"""
        fee = await usd_to_lamports(0.1, self.swaps.sol_price_usd)
        ray_tx = await self.swaps.send_ws_transaction(lp_id, amount, fee, tx_type="sell")
        logging.info(f"Raydium sell order: {ray_tx}")
        result = await self.swaps.get_swap_tx(ray_tx, lp_id, tx_type="sell")

        if lp_id in self.creators and our_change_pct <= -25:
            await self.save_to_blacklist(self.creators[lp_id])
            self.blacklist.add(self.creators[lp_id])
        if result:
            self.dev_balance = result.get("balance", 0)
            await self.save_result({"timestamp": time.time(), "sell": result, "amount": amount, "fee": fee, "mint": lp_id, "change_pct": our_change_pct})
        else:
            return
        
    async def handle_account_update(self, data, address, mint, role):
        try:
            token_data = data.get("params", {}).get("result", {})
            if token_data:
                timestamp = time.time()
                token_balance = token_data.get("value", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {}).get("uiAmount", 0)

                self.balances[mint][role][timestamp] = token_balance

                if mint not in self.pools:
                    self.pools[mint] = {"pool1": None, "pool2": None, "sold": False}
                if role == "pool1":
                    self.pools[mint]["pool1"] = address
                elif role == "pool2":
                    self.pools[mint]["pool2"] = address

                # We have balances for both pools => We can calculate a price
                if self.balances[mint].get("pool1") and self.balances[mint].get("pool2"):
                    if mint in self.pools and self.pools[mint].get("pool1") and self.pools[mint].get("pool2"):
                        pool1_balance = list(self.balances[mint].get("pool1", {}).values())[-1]
                        pool2_balance = list(self.balances[mint].get("pool2", {}).values())[-1]

                        if pool1_balance is not None and pool2_balance is not None:
                            new_price = self.calculate_price(pool1_balance, pool2_balance)
                            price_usd = float(Decimal(new_price) * self.swaps.sol_price_usd)

                            if mint not in self.active_sessions:
                                self.active_sessions.add(mint)
                                lp1 = self.pools[mint].get("pool1")
                                lp2 = self.pools[mint].get("pool2")
                                start_price = new_price
                                real_supply = await self.swaps.get_token_supply(mint)
                                asyncio.create_task(self.session_tracker(mint, lp1, lp2, start_price, timestamp, real_supply))
                            else:
                                if mint in self.mint_data:
                                    if new_price != self.mint_data[mint]["price"]:
                                        if new_price > self.mint_data[mint]["price"]:
                                            self.mint_data[mint]["volume"]["buy"] += 1
                                        elif new_price < self.mint_data[mint]["price"]:
                                            self.mint_data[mint]["volume"]["sell"] += 1
                                        self.mint_data[mint]["price"] = new_price
                                        self.mint_data[mint]["price_usd"] = price_usd
                                    else:
                                        await asyncio.sleep(0.02)
                                        return

        except AttributeError:
            logging.error(f"Unknown structure for {address}, stopping the tracker...")
            self.pools[mint]["sold"] = True

        except Exception as e:
            logging.error(f"Error processing account update for {address}: {e}")
            traceback.print_exc()

    async def session_tracker(self, mint, lp1, lp2, start_price, timestamp, supply):
        last_price = 0
        momentum = float(0.00)
        current_step = 40
        last_price_change = time.time()
        time_since_buy = None
        session_meta = {"bought": False, "sold": False, "stagnant": False}
        iterations = 0
        our_change_pct = 0
        market_cap = 0
        balance = 0
        change_pct = 0
        peak_change = 0
        pct_diff = []
        last_logged_time = time.time()
        prev_change_pct = 0
        while not self.stop_event.is_set():
            try:
                iterations += 1

                # Mint data dict
                if mint not in self.mint_data:
                    self.mint_data[mint] = {
                        "price_history": [],
                        "price": start_price,
                        "price_usd": 0,
                        "balance": 0,
                        "our_peak_price": 0,
                        "timestamp": timestamp,
                        "open_price": start_price,
                        "volume": {"buy": 0, "sell": 0},
                    }

                price_len = len(self.mint_data[mint].get("price_history", []))
                new_price = self.mint_data[mint].get("price")
                price_usd = self.mint_data[mint].get("price_usd", 0)
                volume = self.mint_data[mint].get("volume")

                if time.time() - last_price_change >= 30:
                    session_meta["stagnant"] = True
                    if session_meta["bought"] and not session_meta["sold"]:
                        await self.sell(mint, self.mint_data[mint].get("balance"), our_change_pct)
                        logging.info(f"Sold {mint} at {new_price}")
                        self.pools[mint]["sold"] = True
                    break

                if new_price == last_price:
                    await asyncio.sleep(0.1)
                    continue
                last_price_change = time.time()                
                momentum += 0.01 if new_price > last_price else -0.01 if new_price < last_price else 0
                last_price = new_price 

                self.mint_data[mint].setdefault("price_history", []).append(new_price)

                # If we haven't recorded the buy_price previously, do so
                if mint in self.mint_data and "buy_price" not in self.mint_data[mint]:
                    balance = self.mint_data[mint]["balance"]
                    if balance > 0:
                        self.mint_data[mint]["buy_price"] = new_price

                change_pct = self._calc_change_pct(
                    self.mint_data[mint].get("open_price", 0), 
                    new_price
                )
                if change_pct > peak_change:
                    peak_change = change_pct

                if change_pct != prev_change_pct:
                    if not pct_diff:
                        pct_diff.append(round(change_pct, 2))
                    else:
                        pct_diff.append(round(change_pct - prev_change_pct, 2))
                    prev_change_pct = change_pct

                diffs_threshold = all(diff >= -10 for diff in pct_diff)

                logging.info(
                    f"""Price: {new_price:.10f} for mint {mint} at {time.strftime('%H:%M:%S')}
                    Owner: {self.creators.get(mint, "Unknown")}
                    Price USD: {price_usd:.5f}
                    Market Cap: {f"{market_cap:,.2f}$"}
                    Current step: {current_step}
                    Change: {change_pct:.2f}%
                    Volume: {volume}$
                    """
                )
                elapsed = time.time() - self.mint_data[mint].get("timestamp", 0)

                curtime = time.time()
                if curtime - last_logged_time >= 10:
                    last_logged_time = curtime
                    pct_diff = []
                    logging.info(f"Momentum for {mint}: {momentum:.2f}")
                    momentum = 0
                    is_boosted, boosts = await self.dexscreen.get_chain_address_info(mint)
                    if is_boosted and mint not in self.boosted_mints:
                        self.boosted_mints[mint] = boosts
                        logging.info(f"{cc.YELLOW}Boosted token: {mint} with {boosts} boosts")
                    elif mint in self.boosted_mints:
                        if self.boosted_mints[mint] != boosts:
                            self.boosted_mints[mint] = boosts
                            logging.info(f"{cc.YELLOW}Token {mint} is boosted with {boosts} boosts{cc.RESET}")

                # if price drops below -40% and it’s been at least 13s
                if (change_pct <= -40 and elapsed >= 13 or change_pct <= -15 and elapsed >= 60 or elapsed > 60 * 60) and not session_meta["bought"]:
                    logging.info(f"Exiting due to low change: {change_pct:.2f}% for elapsed time: {elapsed:.2f}s")
                    break

                buy_to_sell = (volume["sell"] * 100) / volume["buy"] if volume["buy"] > 0 else 0
                if price_len >= 20 and buy_to_sell >= 100 and not session_meta["bought"]:
                    logging.info(f"Buy to sell ratio is too high: {buy_to_sell}")
                    break

                in_entry_range = await self.determine_safe_range(buy_to_sell, price_len)
                if "buy_price" not in self.mint_data[mint] and not session_meta["bought"]:
                    if in_entry_range and diffs_threshold:
                        if change_pct >= 80:
                            logging.info(f"Change pct at the moment of buy: {change_pct}")
                            balance = await self.buy(mint, 1)
                        else:
                            continue
                        if balance == "QuoteUnavailable":
                            break
                        logging.info(f"Balance: {balance}")
                        time_since_buy = time.time()
                        self.mint_data[mint]["balance"] = balance
                        session_meta["bought"] = True
                
                # Our own buy-based change
                our_change_pct = self._calc_change_pct(
                    self.mint_data.get(mint, {}).get("buy_price", 0), 
                    new_price
                )

                if our_change_pct != 0:
                    elapsed_since_buy = time.time() - time_since_buy
                    if new_price > self.mint_data[mint].get("our_peak_price", 0):
                        self.mint_data[mint]["our_peak_price"] = new_price

                    logging.info(f"Our change for {mint}: {our_change_pct:.2f}%")
                    current_step = await self.determine_inc_factor(momentum, volume, our_change_pct, elapsed_since_buy, current_step)

                    if (
                        our_change_pct >= current_step
                        or (our_change_pct <= -12)
                    ):
                        await self.sell(mint, self.mint_data[mint].get("balance"), our_change_pct)
                        logging.info(f"Sold {mint} at {new_price}")
                        self.pools[mint]["sold"] = True
                        session_meta["sold"] = True
                        break
                await asyncio.sleep(0.02)
            except Exception as e:
                logging.error(f"Error in session tracker: {e}")
                traceback.print_exc()
                break
        self.pools[mint]["sold"] = True
        await self.save_tracker({
            "mint": mint, 
            "owner": self.creators.get(mint, "NN"), 
            "latest_price": new_price, 
            "price_history": self.mint_data[mint].get("price_history", []), 
            "saved_at": time.time(), 
            "current_change": change_pct, 
            "peak_change": peak_change, 
            "market_cap": market_cap, 
            "volume": volume,
            "pct_diff": pct_diff,
        })
        self.mint_data.pop(mint, None)

    async def determine_safe_range(self, buy_to_sell, price_len):
        if price_len <= 50:
            return False
        elif price_len <= 2000:
            return buy_to_sell <= 80

    async def determine_inc_factor(self, momentum, volume, our_change_pct, elapsed_since_buy, current_step):
        next_increment = current_step + 40
        diff = next_increment - current_step
        half_diff = diff * 0.5

        if volume["sell"] > volume["buy"] and our_change_pct <= 10 and elapsed_since_buy >= 30:
            logging.info(f"Volume sell is higher than buy: {volume['sell']} > {volume['buy']}")
            return -99

        if our_change_pct <= -35 or (our_change_pct <= -20 and elapsed_since_buy >= 140):
            logging.info(f"Change is negative: {our_change_pct}")
            return -99

        if momentum <= -0.05:
            logging.info(f"Momentum is negative: {momentum}")
            if current_step >= 20:
                current_step = current_step - 10
            return current_step

        threshold = (current_step - half_diff) if current_step != 40 else 20
        if our_change_pct >= threshold and momentum >= 0.15:
            logging.info(f"Change is greater than current step: {our_change_pct} >= {current_step}")
            return next_increment

        return current_step
                    
    async def get_latest_price(self, mint):
        if mint in self.mint_data:
            return self.mint_data[mint].get("price")
        return 0

    def _calc_change_pct(self, open_price, new_price):
        """Calculate percentage change between two prices."""
        try:
            return ((new_price - open_price) / open_price) * 100
        except ZeroDivisionError:
            return 0

    def calculate_price(self, pool1_balance, pool2_balance):
        """Calculate price based on pool balances."""
        try:
            price = pool1_balance / pool2_balance if pool2_balance > 0 else float('inf')
            if price >= 1:
                price = pool2_balance / pool1_balance if pool1_balance > 0 else float('inf')
            return price
        except ZeroDivisionError:
            return float('inf')

    async def process_log(self, message):
        if 'params' in message:
            if 'result' in message['params']:
                data = message.get('params', {}).get('result', {})
                slot = data.get('context', {}).get('slot', 0)
                val = data.get('value', {})
                logs = val.get('logs', [])
                sig = val.get('signature', "")
                err = val.get('err', {})
                return {"slot": slot, "logs": logs, "signature": sig, "err": err}
        return None

    async def validate(self, log_list, sig):
        is_mint = False
        for log in log_list:
            if "InitializeMint" in log:
                is_mint = True
        return is_mint

    async def handle_mint_logs(self, log):
        """Handle mint-related logs to manage account subscriptions."""
        try:
            pLog = await self.process_log(log)
            if pLog:
                if pLog["err"]:
                    return None
                is_mint = await self.validate(pLog["logs"], pLog["signature"])
                if not is_mint:
                    return None
                sig = pLog.get("signature")
                tx_info = await self._fetch_ray_tx(sig)
                #logging.info(f"TX Info: {json.dumps(tx_info,indent=2)}")
                tx_info = tx_info.get("result", {})
                if tx_info:
                    program, keys = await self.extract_keys(tx_info, sig)
                    poolAddress, pool1, pool2, mint, owner = keys
                    self.creators[mint] = owner
                else:
                    logging.info(f"TX Info not found for {pLog.get('signature')}")
                    return
                    
                logging.info(f"{cc.CYAN}{cc.BRIGHT}New migration: {mint}, Program: {program}, pools: Pool1={pool1}, Pool2={pool2}, PoolAddress={poolAddress}{cc.RESET}")
                if self.single_lock and len(self.mint_data) > 0:
                    return
                
                if owner in self.blacklist:
                    logging.info(f"{cc.MAGENTA}Owner is blacklisted: {owner}")
                    return

                if mint in ["So11111111111111111111111111111111111111112", "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"]:
                    return
                
                await self.manage_subscriptions(pool1, pool2, mint)
        except Exception as e:
            logging.error(f"Error handling mint logs: {e}")
            traceback.print_exc()

    async def extract_keys(self, tx_info, sig):
        try:
            account_keys = tx_info.get("transaction", {}).get("message", {}).get("accountKeys", [])
            pump_migration_match = any(PUMP_MIGRATION in key for key in account_keys)
            owner = account_keys[0]
            ak_len = len(account_keys)
            logging.info(f"Len of account keys: {ak_len}\nPump migration match: {pump_migration_match}")
            if pump_migration_match:
                poolAddress = account_keys[2]
                pool1 = account_keys[5]
                pool2 = account_keys[6]
                mint = account_keys[18]
                return "PUMP", [poolAddress, pool1, pool2, mint, owner]
            elif ak_len == 25:
                poolAddress = account_keys[2]
                pool1 = account_keys[6] # WSOL
                pool2 = account_keys[5] # TOKEN
                mint = account_keys[19] if account_keys[19] != "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL" else account_keys[21]
                return "RAY", [poolAddress, pool1, pool2, mint, owner]
            elif ak_len == 24:
                poolAddress = account_keys[2]
                pool1 = account_keys[6] # WSOL
                pool2 = account_keys[5] # TOKEN
                mint = account_keys[20]
                return "RAY", [poolAddress, pool1, pool2, mint, owner]
            elif ak_len == 23:
                poolAddress = account_keys[2]
                pool1 = account_keys[6] # WSOL
                pool2 = account_keys[5] # TOKEN
                mint = account_keys[19]
                return "RAY", [poolAddress, pool1, pool2, mint, owner]
            elif ak_len == 22:
                poolAddress = account_keys[2]
                pool1 = account_keys[6]
                pool2 = account_keys[5]
                mint = account_keys[18] if account_keys[18] not in ["So11111111111111111111111111111111111111112", "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"] else account_keys[16]
                return "RAY", [poolAddress, pool1, pool2, mint, owner]
            elif ak_len == 21:
                poolAddress = account_keys[2]
                pool1 = account_keys[5]
                pool2 = account_keys[6]
                mint = account_keys[18]
                return "RAY", [poolAddress, pool1, pool2, mint, owner]
            elif ak_len == 20:
                poolAddress = account_keys[2]
                pool1 = account_keys[5]
                pool2 = account_keys[6]
                mint = account_keys[17]
                return "RAY", [poolAddress, pool1, pool2, mint, owner]
            elif ak_len == 19: # moonshot
                poolAddress = account_keys[2]
                pool1 = account_keys[6]
                pool2 = account_keys[5]
                mint = account_keys[16]
                return "MOONSHOT", [poolAddress, pool1, pool2, mint, owner]
            elif ak_len == 18: # RPCMM
                poolAddress = account_keys[2]
                pool1 = account_keys[6]
                pool2 = account_keys[5]
                mint = account_keys[17]
                return "RAY", [poolAddress, pool1, pool2, mint, owner]
            else:
                # Guess
                poolAddress = account_keys[2]
                pool1 = account_keys[6]
                pool2 = account_keys[5]
                mint = account_keys[17]
                return "Unknown", [poolAddress, pool1, pool2, mint, owner]
        except IndexError as e:
            logging.info(f"Index error for {sig}: {e}")
            logging.info(f"Account keys: {account_keys}")
            return None

    async def _fetch_ray_tx(self, sig):
        try:
            msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                        sig,
                        {
                            "commitment": "confirmed",
                            "encoding": "json",
                            "maxSupportedTransactionVersion": 0
                        }
                    ]
            }
            async with self.session.post(RPC_URL, json=msg) as response:
                res = await response.json()
                if 'result' in res:
                    if res['result'] == "null" or not res['result']:
                        await asyncio.sleep(1)
                        return await self._fetch_ray_tx(sig)
            return res

        except Exception as e:
            logging.error(f"Error when fetching transaction data: {e}")
            traceback.print_exc()

    async def manage_subscriptions(self, pool1, pool2, mint):
        """Add subscriptions for new pools dynamically without affecting existing ones."""
        try:
            if pool1 not in self.subscriptions:
                asyncio.create_task(self.subscribe_to_account(pool1, mint, role="pool1"))
            if pool2 not in self.subscriptions:
                asyncio.create_task(self.subscribe_to_account(pool2, mint, role="pool2"))
        except Exception as e:
            logging.error(f"Failed to subscribe to pools: {e}")

    async def unsubscribe_from_account(self, address):
        """Unsubscribe from a specific account."""
        ws = self.subscriptions.pop(address, None)
        if ws:
            try:
                await ws.close()
            except Exception as e:
                logging.error(f"Error unsubscribing from {address}: {e}")

    async def run(self):
        """Run the main process."""
        await intro()
        self.setup_signal_handlers()
        self.load_blacklist()
        self.swaps = SolanaSwaps(
            self,
            Keypair.from_bytes(base58.b58decode(PRIV_KEY)),
            WALLET,
            RPC_URL,
            API_KEY
        )
        self.dev_balance = await self.swaps.fetch_wallet_balance_sol()
        await asyncio.gather(
            self.subscribe_logs(),
            self.process_logs(),
        )

    async def process_logs(self):
        """Process logs as they arrive."""
        while not self.stop_event.is_set():
            log = await self.logs.get()
            await self.handle_mint_logs(log)

    async def shutdown(self):
        """Gracefully shut down."""
        self.stop_event.set()
        for ws in self.subscriptions.values():
            await ws.close()
        await self.session.close()

async def main():
    dex_logs = DexBetterLogs(WS_URL)
    try:
        await dex_logs.run()
    except KeyboardInterrupt:
        await dex_logs.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
