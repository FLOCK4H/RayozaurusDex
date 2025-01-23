import asyncio
import aiohttp
import base58
import base64
import json
from typing import Optional
from solders.keypair import Keypair # lint: ignore
from solders.transaction import VersionedTransaction # lint: ignore
from solders import message
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
import time, logging, os, sys
from decimal import Decimal
import websockets, requests
import websockets.connection

try:
    from .common_ import *
    from .colors import *

except ImportError:
    from common_ import *
    from colors import *

LOG_DIR = 'dev/logs'
# Configure logging
logging.basicConfig(
    format=f'{cc.LIGHT_CYAN}[RexLab] %(levelname)s - %(message)s{cc.RESET}',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

def get_solana_price_usd():
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd')
        data = response.json()
        price = data['solana']['usd']
        return str(price)
    except Exception:
        logging.info(f"{cc.RED}Failed to get Solana price from Coingecko{cc.RESET}")
        return '247.11'  # Fallback price

class SolanaSwaps:
    def __init__(self, parent, private_key: Keypair, wallet_address: str, rpc_endpoint: str, api_key: str):
        self.rpc_endpoint = rpc_endpoint
        self.wallet_address = wallet_address
        self.private_key = private_key
        self.api_key = api_key
        self.q_retry = 0
        self.session = aiohttp.ClientSession()  # Persistent session
        self.async_client = AsyncClient(endpoint=self.rpc_endpoint)
        self.dexter = parent
        self.sol_price_usd = Decimal(get_solana_price_usd())
        self.ws_url = QN_WS
        self.websocket_conn = None 

    async def open_ws_session(self):
        if self.websocket_conn is None or self.websocket_conn.closed:
            # Connect once and store the connection
            self.websocket_conn = await websockets.connect(
                self.ws_url, 
                ping_interval=1, 
                ping_timeout=5
            )
            logging.info("WebSocket session opened.")

    async def close_ws_session(self):
        if self.websocket_conn and not self.websocket_conn.closed:
            await self.websocket_conn.close()
            logging.info("WebSocket session closed.")
            self.websocket_conn = None

    async def fetch_wallet_balance_sol(self):
        headers = {"Content-Type": "application/json"}
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance",
            "params": [
                f"{WALLET}",
            ]
        }
        async with self.session.post(RPC_URL, json=payload, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                result = data.get('result')
                value = result.get('value')
                logging.info(f"{cc.BRIGHT}{cc.LIGHT_GREEN}| Wallet balance: {Decimal(value) / Decimal('1e9')} SOL")
                return value
            else:
                raise Exception(f"HTTP {resp.status}: {await resp.text()}")

    async def get_token_supply(self, mint):
        try:
            headers = {"Content-Type": "application/json"}
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenSupply",
                "params": [
                    mint
                ]
            }
            async with self.session.get(RPC_URL, json=payload, headers=headers) as response:
                supply = 0
                response.raise_for_status()
                data = await response.json()
                supply = data.get("result", {}).get("value")
                if supply:
                    amount = int(supply.get("amount"))
                    decimals = int(supply.get("decimals"))
                supply = amount / 10 ** decimals
                return supply
        except Exception as e:
            logging.error(f"Failed to get token supply: {e}")
            return None

    async def close_session(self):
        await self.session.close()

    async def fetch_json(self, url: str) -> dict:
        """Fetch JSON data asynchronously from a given URL."""
        try:
            async with self.session.get(url, timeout=10) as response:
                response.raise_for_status()
                data = await response.json()
                logging.debug(f"Fetched data from {url}: {data}")
                return data
        except aiohttp.ClientError as e:
            logging.error(f"HTTP error while fetching {url}: {e}")
            raise
        except asyncio.TimeoutError:
            logging.error(f"Request to {url} timed out.")
            raise

    async def post_json(self, url: str, payload: dict) -> dict:
        """Post JSON data asynchronously to a given URL."""
        try:
            async with self.session.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10) as response:
                response.raise_for_status()
                data = await response.json()
                logging.debug(f"Posted data to {url}: {data}")
                return data
        except aiohttp.ClientError as e:
            logging.error(f"HTTP error while posting to {url}: {e}")
            raise
        except asyncio.TimeoutError:
            logging.error(f"Post request to {url} timed out.")
            raise

    async def send_ws_transaction(self, minted_token: str, amount: int, fee: int, tx_type: str = "buy"):
        start_time = time.time()

        if tx_type == "buy":
            input_mint = "So11111111111111111111111111111111111111112"
            output_mint = minted_token
        else:
            input_mint = minted_token
            output_mint = "So11111111111111111111111111111111111111112"

        try:
            if self.websocket_conn is None or self.websocket_conn.closed:
                await self.open_ws_session()

            async def token_quote():
                #1 Quote
                quote_req = {
                    "jsonrpc": "2.0", 
                    "method": "quote", 
                    "params": {
                        "inputMint": input_mint, 
                        "outputMint": output_mint, 
                        "amount": amount,
                        "slippageBps": 10000 #100% MAX
                        }, 
                    "id": 1
                }
                await self.websocket_conn.send(json.dumps(quote_req))

            await token_quote()

            self.q_retry = 0  # Reset retry counter
            async for msg in self.websocket_conn:
                quote = json.loads(msg)
                result = quote.get("result")
                
                if self.q_retry < 15:  # Retry logic
                    if result.get("errorCode", "") in ["TOKEN_NOT_TRADABLE", "COULD_NOT_FIND_ANY_ROUTE"]:
                        logging.info(f"Token is not tradable. Retrying...\nQuote response: {quote}")
                        self.q_retry += 1
                        await asyncio.sleep(0.5)
                        await token_quote()
                        continue
                else:
                    logging.error("Max retries reached for fetching quote.")
                    return "QuoteUnavailable"

                logging.info(f"Received Quote: {quote}")
                break

            # Swap
            swap_req = {
                "jsonrpc": "2.0",
                "method": "swap",
                "params": {
                    "userPublicKey": self.wallet_address,
                    "wrapAndUnwrapSol": True,
                    "prioritizationFeeLamports": fee,
                    "quoteResponse": result
                },
                "id": 2
            }
            await self.websocket_conn.send(json.dumps(swap_req))

            async for msg in self.websocket_conn:
                swap = json.loads(msg)
                result = swap.get("result")
                swap_route = result.get('swapTransaction')
                if swap_route == None:
                    logging.error(f"{cc.RED}Swap response: {swap}")
                    return "QuoteUnavailable"
                if not result.get("simulationError") == None:
                    logging.error(f"Swap response: {swap}")
                    raise Exception("Swap response is empty.")
                break
        except TimeoutError:
            logging.error("WebSocket connection timed out.")
            await asyncio.sleep(0.25)
        except ConnectionRefusedError:
            logging.error("WebSocket connection timed out.")
            await asyncio.sleep(0.25)
        # Step 5: Decode and sign the transaction
        try:
            raw_transaction_bytes = base64.b64decode(swap_route)
            raw_transaction = VersionedTransaction.from_bytes(raw_transaction_bytes)
            message_bytes = message.to_bytes_versioned(raw_transaction.message)
            signature = self.private_key.sign_message(message_bytes)
            signed_txn = VersionedTransaction.populate(raw_transaction.message, [signature])
            logging.info("Transaction decoded and signed successfully.")
        except Exception as e:
            logging.error(f"Error processing transaction: {e}")
            raise Exception("Failed to process transaction.") from e

        # Step 6: Send the signed transaction with preflight checks
        try:
            opts = TxOpts(skip_preflight=True, max_retries=0, skip_confirmation=True)
            result = await self.async_client.send_raw_transaction(txn=bytes(signed_txn), opts=opts)
            logging.info("Transaction sent successfully.")
        except Exception as e:
            logging.error(f"Error sending transaction: {e}")
            raise Exception("Failed to send transaction.") from e

        # Step 7: Extract and return the transaction ID
        try:
            result_json = result.to_json()
            transaction_id = json.loads(result_json).get('result')
            elapsed_time = time.time() - start_time
            logging.info(f"Transaction time: {elapsed_time:.2f} seconds")
            if not transaction_id:
                logging.error("Transaction ID not found in the response.")
                raise Exception("Transaction ID not found.")
            logging.info(f"Transaction sent: https://solscan.io/tx/{transaction_id}")
            return transaction_id
        except json.JSONDecodeError as e:
            logging.error(f"Error parsing transaction result: {e}")
            raise Exception("Failed to parse transaction result.") from e

    async def get_swap_tx(self, tx_id: str, mint_token: str, tx_type: str = "buy", max_retries: int = 8) -> Optional[str]:
        """
        Fetches the transaction details for a given transaction ID with retry mechanism.

        Args:
            tx_id (str): The transaction signature.
            mint_token (str): The mint address of the token.
            tx_type (str): Type of transaction ("buy" or "sell").
            max_retries (int): Maximum number of retries if the result is None.
            retry_interval (float): Time to wait between retries in seconds.

        Returns:
            Optional[str]: The token balance if successful, else None.
        """
        attempt = 0
        while attempt < max_retries:
            try:
                await asyncio.sleep(1)  # Initial delay before first attempt
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [
                        tx_id,
                        {
                            "commitment": "confirmed",
                            "encoding": "json",
                            "maxSupportedTransactionVersion": 0
                        }
                    ]
                }
                headers = {
                    "Content-Type": "application/json"
                }

                async with self.session.post(RPC_URL, json=payload, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        logging.error(f"HTTP Error {response.status}: {await response.text()}")
                        raise Exception(f"HTTP Error {response.status}")
    
                    data = await response.json()
                    logging.debug(f"Attempt {attempt + 1}: Received data: {data}")

                    if data and data.get('result') is not None:
                        result = data['result']
                        meta = result.get("meta", {})
                        err = meta.get("err", {})
                        if err is not None and err.get("InstructionError"):
                            logging.info(f"{cc.RED}Instruction error occurred: {err}")
                            await asyncio.sleep(0.2)
                            return "InstructionError"
                        
                        post_token_balances = meta.get("postTokenBalances", [])
                        post_balances = meta.get("postBalances", [])

                        if tx_type == "buy":
                            for post_token_balance in post_token_balances:
                                if post_token_balance.get("mint") == mint_token:
                                    if post_token_balance.get('owner') == self.wallet_address:
                                        logging.info("Transaction verified.")
                                        token_balance = post_token_balance.get("uiTokenAmount", {}).get("amount")
                                        return {"balance": int(token_balance)}
                        elif tx_type == "sell":
                            if post_balances:
                                sol_balance = post_balances[0]  # Assuming the first element is SOL
                                return {"balance": int(sol_balance)}
                            else:
                                logging.error("No post balances found for sell transaction.")
                                return None
                    else:
                        logging.warning(f"Attempt {attempt + 1}: Transaction result is None.")
            except Exception as e:
                logging.warning(f"Attempt {attempt + 1}: Exception occurred: {e}")

            # Increment the attempt counter
            attempt += 1
            if attempt < max_retries:
                logging.info(f"Retrying in 1 seconds...")
                await asyncio.sleep(0.5)
            else:
                logging.error(f"Max retries reached for transaction ID: {tx_id}. Transaction details not found.")
                return "tx_fail"
        return None