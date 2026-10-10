"""
Sovereign Smart Contract Bug Bounty Auditor & PoC Synthesizer
Heuristic Vulnerability Scanner + Local AI (Qwen 2.5 Coder) for Immunefi & Code4rena submissions
"""

import os
import re
import json
import httpx
import duckdb
from datetime import datetime

DATA_DIR = r"C:\Users\Admin\.gemini\antigravity-ide\data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "bounty_audit_vault.duckdb")
OLLAMA_URL = "http://127.0.0.1:11434"

VULN_PATTERNS = [
    {
        "id": "SWC-107",
        "name": "Reentrancy Vulnerability",
        "severity": "CRITICAL",
        "regex": r"\.call\{value:.*\}\(.*?\)",
        "guard_check": r"nonReentrant",
        "desc": "External call made without nonReentrant guard or state variable modified after external call."
    },
    {
        "id": "SWC-115",
        "name": "tx.origin Authentication Flaw",
        "severity": "HIGH",
        "regex": r"tx\.origin\s*==\s*",
        "desc": "Using tx.origin for authorization makes the contract vulnerable to phishing/proxy calls."
    },
    {
        "id": "SWC-104",
        "name": "Unchecked Low-Level Call Return Value",
        "severity": "MEDIUM",
        "regex": r"(?<!require\()\s*\w+\.call\{",
        "desc": "The return value of an external call is not verified with require() or if-statement."
    },
    {
        "id": "SWC-ORACLE",
        "name": "Spot Price / Flash Loan Manipulation Risk",
        "severity": "CRITICAL",
        "regex": r"(getReserves\(\)|balanceOf\(address\(this\)\))",
        "desc": "Directly querying spot balance or reserves for pricing is susceptible to single-block flash loan manipulation."
    }
]

def ensure_ollama_running():
    import subprocess
    import time
    try:
        httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
    except Exception:
        ollama_bin = r"C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe"
        if os.path.exists(ollama_bin):
            subprocess.Popen([ollama_bin, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)

def init_db():
    con = duckdb.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS audit_reports (
            report_id VARCHAR PRIMARY KEY,
            contract_name VARCHAR,
            severity VARCHAR,
            vuln_count INTEGER,
            summary VARCHAR,
            poc_report VARCHAR,
            audited_at TIMESTAMP
        )
    """)
    con.close()

def scan_contract_source(file_path: str):
    ensure_ollama_running()
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        source_code = f.read()

    contract_name = os.path.basename(file_path)
    print(f"\n[*] Auditing Smart Contract: '{contract_name}'...")
    
    findings = []
    for p in VULN_PATTERNS:
        matches = list(re.finditer(p["regex"], source_code))
        if matches:
            if "guard_check" in p and re.search(p["guard_check"], source_code):
                continue
            findings.append({
                "id": p["id"],
                "name": p["name"],
                "severity": p["severity"],
                "description": p["desc"],
                "occurrences": len(matches)
            })

    print(f"[+] Heuristic scan complete: Found {len(findings)} potential vulnerability vectors.")
    for f in findings:
        print(f"    -> [{f['severity']}] {f['name']} ({f['id']}): {f['description']}")

    # Generate Immunefi bounty report using local AI
    print("\n[*] Synthesizing Immunefi Bounty PoC Report with Local AI (Qwen 2.5 Coder)...")
    prompt = f"""You are a top-tier Web3 Security Researcher. Generate a formal Immunefi Bug Bounty submission report for the following contract findings.

Target Contract: {contract_name}
Findings:
{json.dumps(findings, indent=2)}

Contract Snippet:
{source_code[:1200]}

Generate the report following the standard Immunefi structure:
1. Title & Vulnerability Details
2. Severity Assessment (Critical / High / Medium)
3. Impact Explanation
4. Step-by-Step Proof of Concept (PoC) Scenario
5. Mitigation Recommendation"""

    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": "qwen2.5-coder:1.5b", "prompt": prompt, "stream": False},
            timeout=120.0
        )
        report_text = resp.json()["response"].strip()
    except Exception as e:
        report_text = f"Local AI synthesis skipped: {e}"

    print("\n======================= IMMUNEFI BOUNTY REPORT =======================")
    print(report_text[:1000] + "\n... [Report continues with full PoC details]")
    print("=======================================================================")

    init_db()
    con = duckdb.connect(DB_PATH)
    rep_id = f"BOUNTY_{contract_name}_{int(datetime.now().timestamp())}"
    max_sev = findings[0]["severity"] if findings else "LOW"
    con.execute("""
        INSERT OR REPLACE INTO audit_reports VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (rep_id, contract_name, max_sev, len(findings), f"Audit completed with {len(findings)} findings", report_text, datetime.now()))
    con.close()
    
    print(f"[+] Report logged to Bounty Vault ({DB_PATH}) under ID: {rep_id}")
    return report_text

if __name__ == "__main__":
    init_db()
    # Create a demo vulnerable contract to test detection
    demo_vuln_path = r"C:\Users\Admin\.gemini\antigravity-ide\scratch\sovereign-revenue-engine\auditor\VulnerableBank.sol"
    with open(demo_vuln_path, "w", encoding="utf-8") as f:
        f.write("""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract VulnerableBank {
    mapping(address => uint256) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw() external {
        uint256 bal = balances[msg.sender];
        require(bal > 0);
        (bool sent, ) = msg.sender.call{value: bal}("");
        require(sent, "Failed to send Ether");
        balances[msg.sender] = 0; // State updated after external call -> Reentrancy!
    }
}
""")
    scan_contract_source(demo_vuln_path)
