
try:
    from .config_reader import get_api_key, get_private_key, get_wallet, read_config
except ImportError:
    from config_reader import get_api_key, get_private_key, get_wallet, read_config

config = read_config(".config")
API_KEY = get_api_key(config)
PRIV_KEY = get_private_key(config)
WALLET = get_wallet(config)
gWS_URL = f"wss://atlas-mainnet.helius-rpc.com/?api-key={API_KEY}"
WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={API_KEY}" # wss://mainnet.helius-rpc.com/?api-key={API_KEY} wss://chaotic-tiniest-general.solana-mainnet.quiknode.pro/281a5cd092301d6dc4d5049345f05397c7eb3408
PUMP_FUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
METAPLEX = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
MOONSHOT = "MoonCVVNZFSYkqNXP6bxHLPL6QQJiMagDL3qcqUQTrG"
RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={API_KEY}"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
SOL_ADDRESS = "So11111111111111111111111111111111111111112"
PUMP_MIGRATION = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
RLQ4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RCLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
RPLMM = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
QN_WS = "wss://jupiter-swap-api.quiknode.pro/B6D3B800F1E3/ws"