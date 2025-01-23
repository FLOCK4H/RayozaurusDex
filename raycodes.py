import base64
import struct
from base58 import b58encode

LOG_TYPE_INIT = 0
LOG_TYPE_DEPOSIT = 1
LOG_TYPE_WITHDRAW = 2
LOG_TYPE_SWAP_BASE_IN = 3
LOG_TYPE_SWAP_BASE_OUT = 4

class RaydiumLogParser:
    """
    Decodes Raydium logs (bincode-serialized) into Python dictionaries.
    """

    @staticmethod
    def _parse_u128_le(data_16: bytes) -> int:
        """
        Convert 16 little-endian bytes into a Python int (u128).
        """
        # Unpack into two 64-bit little-endian parts, then combine
        low, high = struct.unpack("<QQ", data_16)
        return low + (high << 64)

    @staticmethod
    def parse_init_log(raw: bytes) -> dict:
        """
        Parse InitLog:
            pub struct InitLog {
                log_type: u8,
                time: u64,
                pc_decimals: u8,
                coin_decimals: u8,
                pc_lot_size: u64,
                coin_lot_size: u64,
                pc_amount: u64,
                coin_amount: u64,
                market: [u8; 32],
            }
        """
        fmt = "<B Q B B Q Q Q Q 32s"
        (
            log_type,
            time,
            pc_decimals,
            coin_decimals,
            pc_lot_size,
            coin_lot_size,
            pc_amount,
            coin_amount,
            market_pubkey,
        ) = struct.unpack(fmt, raw)

        return {
            "log_type": log_type,
            "time": time,
            "pc_decimals": pc_decimals,
            "coin_decimals": coin_decimals,
            "pc_lot_size": pc_lot_size,
            "coin_lot_size": coin_lot_size,
            "pc_amount": pc_amount,
            "coin_amount": coin_amount,
            "market_pubkey": b58encode(market_pubkey).decode("utf-8"),
        }

    @staticmethod
    def parse_deposit_log(raw: bytes) -> dict:
        """
        Parse DepositLog:
            pub struct DepositLog {
                log_type: u8,
                max_coin: u64,
                max_pc: u64,
                base: u64,
                pool_coin: u64,
                pool_pc: u64,
                pool_lp: u64,
                calc_pnl_x: u128,
                calc_pnl_y: u128,
                deduct_coin: u64,
                deduct_pc: u64,
                mint_lp: u64,
            }
        """
        # We'll read the 2x u128 fields as 16 bytes each, then convert manually.
        # Format: <B 6Q 16s 16s 3Q = total 1 + 48 + 32 + 24 = 105 bytes
        fmt = "<B 6Q 16s 16s 3Q"
        parsed = struct.unpack(fmt, raw)
        (
            log_type,
            max_coin,
            max_pc,
            base,
            pool_coin,
            pool_pc,
            pool_lp,
            calc_pnl_x_bytes,
            calc_pnl_y_bytes,
            deduct_coin,
            deduct_pc,
            mint_lp,
        ) = parsed

        calc_pnl_x = RaydiumLogParser._parse_u128_le(calc_pnl_x_bytes)
        calc_pnl_y = RaydiumLogParser._parse_u128_le(calc_pnl_y_bytes)

        return {
            "log_type": log_type,
            "max_coin": max_coin,
            "max_pc": max_pc,
            "base": base,
            "pool_coin": pool_coin,
            "pool_pc": pool_pc,
            "pool_lp": pool_lp,
            "calc_pnl_x": calc_pnl_x,
            "calc_pnl_y": calc_pnl_y,
            "deduct_coin": deduct_coin,
            "deduct_pc": deduct_pc,
            "mint_lp": mint_lp,
        }

    @staticmethod
    def parse_withdraw_log(raw: bytes) -> dict:
        """
        Parse WithdrawLog:
            pub struct WithdrawLog {
                log_type: u8,
                withdraw_lp: u64,
                user_lp: u64,
                pool_coin: u64,
                pool_pc: u64,
                pool_lp: u64,
                calc_pnl_x: u128,
                calc_pnl_y: u128,
                out_coin: u64,
                out_pc: u64,
            }
        """
        # Format: <B 3Q 16s 16s 2Q = 1 + 24 + 32 + 32 + 16 = 105 bytes
        # Actually we have:
        #   log_type (1 byte)
        #   withdraw_lp (8)
        #   user_lp (8)
        #   pool_coin (8)
        #   pool_pc (8)
        #   pool_lp (8)
        #   calc_pnl_x (16)
        #   calc_pnl_y (16)
        #   out_coin (8)
        #   out_pc (8)
        # => 1 + 5*8 + 2*16 + 2*8 = 1 + 40 + 32 + 16 = 89? Let's recount carefully:
        # Actually it's 5 u64 = 5*8=40, plus 2 u128=2*16=32, plus 2 u64=16, plus 1=1 => 89 total
        fmt = "<B Q Q Q Q Q 16s 16s Q Q"
        parsed = struct.unpack(fmt, raw)
        (
            log_type,
            withdraw_lp,
            user_lp,
            pool_coin,
            pool_pc,
            pool_lp,
            calc_pnl_x_bytes,
            calc_pnl_y_bytes,
            out_coin,
            out_pc,
        ) = parsed

        calc_pnl_x = RaydiumLogParser._parse_u128_le(calc_pnl_x_bytes)
        calc_pnl_y = RaydiumLogParser._parse_u128_le(calc_pnl_y_bytes)

        return {
            "log_type": log_type,
            "withdraw_lp": withdraw_lp,
            "user_lp": user_lp,
            "pool_coin": pool_coin,
            "pool_pc": pool_pc,
            "pool_lp": pool_lp,
            "calc_pnl_x": calc_pnl_x,
            "calc_pnl_y": calc_pnl_y,
            "out_coin": out_coin,
            "out_pc": out_pc,
        }

    @staticmethod
    def parse_swap_base_in_log(raw: bytes) -> dict:
        """
        Parse SwapBaseInLog:
            pub struct SwapBaseInLog {
                log_type: u8,
                amount_in: u64,
                minimum_out: u64,
                direction: u64,
                user_source: u64,
                pool_coin: u64,
                pool_pc: u64,
                out_amount: u64,
            }
        """
        # Format: <B 7Q = 1 + 7*8 = 57 bytes
        fmt = "<B Q Q Q Q Q Q Q"
        (
            log_type,
            amount_in,
            minimum_out,
            direction,
            user_source,
            pool_coin,
            pool_pc,
            out_amount,
        ) = struct.unpack(fmt, raw)

        return {
            "log_type": log_type,
            "amount_in": amount_in,
            "minimum_out": minimum_out,
            "direction": direction,
            "user_source": user_source,
            "pool_coin": pool_coin,
            "pool_pc": pool_pc,
            "out_amount": out_amount,
        }

    @staticmethod
    def parse_swap_base_out_log(raw: bytes) -> dict:
        """
        Parse SwapBaseOutLog:
            pub struct SwapBaseOutLog {
                log_type: u8,
                max_in: u64,
                amount_out: u64,
                direction: u64,
                user_source: u64,
                pool_coin: u64,
                pool_pc: u64,
                deduct_in: u64,
            }
        """
        # Format: <B 7Q = 57 bytes
        fmt = "<B Q Q Q Q Q Q Q"
        (
            log_type,
            max_in,
            amount_out,
            direction,
            user_source,
            pool_coin,
            pool_pc,
            deduct_in,
        ) = struct.unpack(fmt, raw)

        return {
            "log_type": log_type,
            "max_in": max_in,
            "amount_out": amount_out,
            "direction": direction,
            "user_source": user_source,
            "pool_coin": pool_coin,
            "pool_pc": pool_pc,
            "deduct_in": deduct_in,
        }

    def parse_log(self, b64_data: str) -> dict:
        """
        Main entry point: given a base64-encoded bincode from Raydium,
        detect log_type and parse accordingly.
        Returns a dictionary of all fields.
        """
        raw = base64.b64decode(b64_data)
        if not raw:
            raise ValueError("No data to decode.")
        log_type = raw[0]

        if log_type == LOG_TYPE_INIT:
            return self.parse_init_log(raw)
        elif log_type == LOG_TYPE_DEPOSIT:
            return self.parse_deposit_log(raw)
        elif log_type == LOG_TYPE_WITHDRAW:
            return self.parse_withdraw_log(raw)
        elif log_type == LOG_TYPE_SWAP_BASE_IN:
            return self.parse_swap_base_in_log(raw)
        elif log_type == LOG_TYPE_SWAP_BASE_OUT:
            return self.parse_swap_base_out_log(raw)
        else:
            raise ValueError(f"Unknown log_type: {log_type}")
        
if __name__ == "__main__":
    # Example usage
    parser = RaydiumLogParser()
    b64_data = "AASmgmcAAAAACQaghgEAAAAAAEBCDwAAAAAAAMqaOwAAAAAAID2IeS0AAHEqcnpabbIF4M/QaJoHlIeLkFBa0VgTlDKIcH5MM0Vi"
    result = print(parser.parse_log(b64_data))