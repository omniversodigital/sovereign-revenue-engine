"""
CEREBRO AUTONOMOUS END-TO-END ON-CHAIN PIPELINE
Fully automated:
1. Compiles & Deploys FlashArbitrageReceiver to Base / Arbitrum
2. Automatically configures owner as the operating wallet
3. Runs 24/7 scanning & continuous flash loan arbitrage execution loop
"""

import os
import sys
import time
import json
from datetime import datetime
from web3 import Web3
from eth_abi import encode

# Auto-load workspace .env files
SCRATCH_DIR = r"C:\Users\Admin\.gemini\antigravity-ide\scratch"
if SCRATCH_DIR not in sys.path:
    sys.path.insert(0, SCRATCH_DIR)
DATA_DIR = r"C:\Users\Admin\.gemini\antigravity-ide\data"
os.makedirs(DATA_DIR, exist_ok=True)

env_paths = [
    os.path.join(SCRATCH_DIR, ".env"),
    os.path.join(SCRATCH_DIR, "omniverso", ".env")
]
for p in env_paths:
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and not os.getenv(k):
                        os.environ[k] = v

RPCS = {
    "Base": os.getenv("BASE_RPC_URL", "https://mainnet.base.org"),
    "Arbitrum": os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc")
}

CHAIN_IDS = {
    "Base": 8453,
    "Arbitrum": 42161
}

ROUTER_CONFIGS = {
    "Base": {
        "chainId": 8453,
        "aavePool": "0xA238Dd80C259b70e830E2e4290777249d3888351",
        "swapRouter": "0x2626664c2603336E57B271c5C0b26F421741e481"
    },
    "Arbitrum": {
        "chainId": 42161,
        "aavePool": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
        "swapRouter": "0xE592427A0AEce92De3Edee1F18E0157C05861564"
    }
}

TOKENS = {
    "Base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "WETH": "0x4200000000000000000000000000000000000006"
    },
    "Arbitrum": {
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
    }
}

DEPLOYED_FILE = os.path.join(DATA_DIR, "deployed_contracts.json")
COMPILED_FILE = os.path.join(DATA_DIR, "FlashArbitrageReceiver_compiled.json")


class AutonomousPipeline:
    def __init__(self):
        self.private_key = os.getenv("SOVEREIGN_PRIVATE_KEY") or os.getenv("PRIVATE_KEY") or os.getenv("ETH_PRIVATE_KEY")
        self.w3_base = Web3(Web3.HTTPProvider(RPCS["Base"]))
        self.w3_arb = Web3(Web3.HTTPProvider(RPCS["Arbitrum"]))
        self.account = None

        if self.private_key and self.private_key.startswith("0x") and len(self.private_key) == 66:
            try:
                self.account = self.w3_base.eth.account.from_key(self.private_key)
            except Exception as e:
                print(f"[!] Error loading account from private key: {e}")

        self.deployed = {}
        if os.path.exists(DEPLOYED_FILE):
            try:
                with open(DEPLOYED_FILE, "r", encoding="utf-8") as f:
                    self.deployed = json.load(f)
            except Exception:
                pass

    def deploy_contract_if_needed(self, chain: str) -> str:
        if chain in self.deployed and self.deployed[chain]:
            print(f"[*] {chain} contract already deployed at: {self.deployed[chain]}")
            return self.deployed[chain]

        if not self.account:
            print(f"[!] Cannot auto-deploy to {chain} without SOVEREIGN_PRIVATE_KEY in .env")
            return None

        w3 = self.w3_base if chain == "Base" else self.w3_arb
        chain_id = CHAIN_IDS[chain]
        config = ROUTER_CONFIGS[chain]

        if not os.path.exists(COMPILED_FILE):
            print("[!] Compiled contract JSON missing. Compiling now...")
            import subprocess
            subprocess.run([sys.executable, os.path.join(SCRATCH_DIR, "compile_contract.py")], check=True)

        with open(COMPILED_FILE, "r", encoding="utf-8") as f:
            compiled_data = json.load(f)

        abi = compiled_data["abi"]
        bytecode = compiled_data["bytecode"]

        print(f"[*] Deploying FlashArbitrageReceiver to {chain} from {self.account.address}...")
        
        # Check balance
        bal = w3.eth.get_balance(self.account.address)
        bal_eth = float(w3.from_wei(bal, 'ether'))
        print(f"[*] Wallet Balance on {chain}: {bal_eth:.6f} ETH")
        
        if bal_eth < 0.0001:
            print(f"[!] Insufficient ETH for gas deployment on {chain}. Minimum required: ~0.0001 ETH")
            return None

        contract = w3.eth.contract(abi=abi, bytecode=bytecode)
        
        # Constructor args: _aavePool, _swapRouter
        constructor_tx = contract.constructor(
            w3.to_checksum_address(config["aavePool"]),
            w3.to_checksum_address(config["swapRouter"])
        ).build_transaction({
            'from': self.account.address,
            'nonce': w3.eth.get_transaction_count(self.account.address, 'pending'),
            'gas': 1_200_000,
            'maxFeePerGas': int(w3.eth.gas_price * 1.3),
            'maxPriorityFeePerGas': int(w3.eth.gas_price * 0.1),
            'chainId': chain_id
        })

        signed_tx = w3.eth.account.sign_transaction(constructor_tx, self.private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"[+] Deployment transaction sent! TxHash: {tx_hash.hex()}")
        print("[*] Awaiting on-chain confirmation...")

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        deployed_address = receipt.contractAddress
        print(f"[+] CONTRACT DEPLOYED SUCCESSFULLY ON {chain}! Address: {deployed_address}")

        self.deployed[chain] = deployed_address
        with open(DEPLOYED_FILE, "w", encoding="utf-8") as f:
            json.dump(self.deployed, f, indent=2)

        return deployed_address

    def execute_flash_arbitrage(self, chain: str, asset: str, amount_usd: float, expected_profit: float):
        contract_addr = self.deployed.get(chain)
        if not contract_addr:
            print(f"[!] No contract deployed on {chain} to execute.")
            return

        if not self.account:
            print("[!] No signing key configured for live broadcast.")
            return

        w3 = self.w3_base if chain == "Base" else self.w3_arb
        chain_id = CHAIN_IDS[chain]
        
        with open(COMPILED_FILE, "r", encoding="utf-8") as f:
            compiled_data = json.load(f)

        contract = w3.eth.contract(address=w3.to_checksum_address(contract_addr), abi=compiled_data["abi"])

        asset_addr = w3.to_checksum_address(TOKENS[chain]["USDC"])
        weth_addr = w3.to_checksum_address(TOKENS[chain]["WETH"])
        borrow_amount_wei = int(amount_usd * 10**6) # USDC decimals
        min_profit_wei = int(expected_profit * 0.8 * 10**6)

        # Encode ArbParams struct: (address intermediateToken, uint24 poolFee1, uint24 poolFee2, uint256 minProfit)
        params_bytes = encode(
            ['address', 'uint24', 'uint24', 'uint256'],
            [weth_addr, 500, 3000, min_profit_wei]
        )

        print(f"[*] Broadcasting Flash Loan Arbitrage on {chain} for ${amount_usd:,.2f} USDC...")
        
        tx = contract.functions.requestFlashLoan(
            asset_addr,
            borrow_amount_wei,
            params_bytes
        ).build_transaction({
            'from': self.account.address,
            'nonce': w3.eth.get_transaction_count(self.account.address, 'pending'),
            'gas': 450_000,
            'maxFeePerGas': int(w3.eth.gas_price * 1.3),
            'maxPriorityFeePerGas': int(w3.eth.gas_price * 0.1),
            'chainId': chain_id
        })

        signed_tx = w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"[+] Flash Loan broadcasted! TxHash: {tx_hash.hex()}")
        
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        status = "SUCCESS" if receipt.status == 1 else "REVERTED"
        print(f"[+] Transaction Result: {status} (Block: {receipt.blockNumber})")

    def run_autonomous_loop(self):
        print("==========================================================================")
        print("      CEREBRO AUTONOMOUS END-TO-END ON-CHAIN ARBITRAGE ENGINE             ")
        print("==========================================================================")

        if self.account:
            print(f"[+] Operator Account Loaded: {self.account.address}")
            # Try auto deployment
            for chain in ["Base", "Arbitrum"]:
                self.deploy_contract_if_needed(chain)
        else:
            print("[*] Running in Sovereign Signal & Web3 Ready Mode.")
            print("[*] Terminal active on: http://127.0.0.1:5173")

        # Start continuous loop
        iteration = 1
        while True:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{timestamp}] --- AUTONOMOUS HARVEST CYCLE #{iteration} ---")
            
            try:
                from dex_live_arbitrage_engine import LiveLiquidityEngine
                engine = LiveLiquidityEngine()
                report = engine.run_live_liquidity_pipeline()
                
                opps = report.get("opportunities", [])
                print(f"[*] Detected {len(opps)} opportunities. Top extractable: ${report.get('total_estimated_instant_profit_usd', 0):,.2f} USD")

                for opp in opps:
                    if opp.get("net_profit_usd", 0) > 50.0 and self.account:
                        chain = opp["chain"]
                        if self.deployed.get(chain):
                            self.execute_flash_arbitrage(
                                chain=chain,
                                asset="USDC",
                                amount_usd=opp.get("simulated_flash_loan_usd", 250000.0),
                                expected_profit=opp.get("net_profit_usd", 100.0)
                            )
            except Exception as e:
                print(f"[!] Error in harvest loop: {e}")

            iteration += 1
            time.sleep(30)


if __name__ == "__main__":
    pipeline = AutonomousPipeline()
    pipeline.run_autonomous_loop()
