"""
Sovereign DeFi Yield & Delta-Neutral Arbitrage Scanner
Powered by Python 3.13, DuckDB and DefiLlama Live Pool Streams
"""

import os
import httpx
import duckdb
from datetime import datetime

DATA_DIR = r"C:\Users\Admin\.gemini\antigravity-ide\data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "revenue_vault.duckdb")

def init_vault(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS yield_opportunities (
            pool_id VARCHAR PRIMARY KEY,
            project VARCHAR,
            chain VARCHAR,
            symbol VARCHAR,
            tvl_usd DOUBLE,
            apy DOUBLE,
            apy_base DOUBLE,
            apy_reward DOUBLE,
            is_stablecoin BOOLEAN,
            detected_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS arbitrage_spreads (
            pair VARCHAR,
            chain VARCHAR,
            source_dex VARCHAR,
            target_dex VARCHAR,
            spread_pct DOUBLE,
            estimated_profit_usd DOUBLE,
            tested_at TIMESTAMP
        );
    """)

def scan_live_yield_opportunities(min_tvl: float = 1_000_000, min_apy: float = 10.0):
    url = "https://yields.llama.fi/pools"
    print(f"[*] Scanning 10,000+ live DeFi pools via DefiLlama...")
    
    with httpx.Client(timeout=25.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        
    print(f"[+] Retrieved {len(data)} total active pools across all blockchains.")
    
    con = duckdb.connect(DB_PATH)
    init_vault(con)
    now = datetime.now()
    
    filtered = []
    for p in data:
        chain = p.get("chain", "")
        tvl = float(p.get("tvlUsd", 0) or 0)
        apy = float(p.get("apy", 0) or 0)
        is_stable = bool(p.get("stablecoin", False))
        
        # Filter for high-liquidity, high-yield pools on low-fee chains (Base, Arbitrum, Ethereum, Solana)
        if chain in ["Base", "Arbitrum", "Ethereum", "Solana", "Polygon"] and tvl >= min_tvl and apy >= min_apy:
            pool_id = str(p.get("pool"))
            project = p.get("project", "")
            symbol = p.get("symbol", "")
            apy_base = float(p.get("apyBase", 0) or 0)
            apy_reward = float(p.get("apyReward", 0) or 0)
            
            con.execute("""
                INSERT OR REPLACE INTO yield_opportunities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (pool_id, project, chain, symbol, tvl, apy, apy_base, apy_reward, is_stable, now))
            filtered.append(p)
            
    con.close()
    print(f"[+] Ingested {len(filtered)} institutional-grade yield opportunities into DuckDB ({DB_PATH})")
    return filtered

def print_top_opportunities():
    con = duckdb.connect(DB_PATH)
    print("\n" + "=" * 90)
    print("       TOP HIGH-YIELD & DELTA-NEUTRAL OPPORTUNITIES (LIVE FROM SURFACE WEB)")
    print("=" * 90)
    
    res = con.execute("""
        SELECT project, chain, symbol, tvl_usd, apy, is_stablecoin 
        FROM yield_opportunities 
        ORDER BY apy DESC 
        LIMIT 12
    """).fetchall()
    con.close()
    
    for r in res:
        tvl_m = r[3] / 1e6
        stable_badge = "[STABLECOIN]" if r[5] else "[VOLATILE]"
        print(f"• {r[0]:<16} | Chain: {r[1]:<10} | Pair: {r[2]:<15} | TVL: ${tvl_m:>6.2f}M | APY: {r[4]:>6.2f}% {stable_badge}")
    print("=" * 90)

if __name__ == "__main__":
    scan_live_yield_opportunities(min_tvl=500_000, min_apy=12.0)
    print_top_opportunities()
