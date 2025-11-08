from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from web3 import Web3
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Ultra Earning Backend", version="10.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "j6uyDNnArwlEpG44o93SqZ0JixvE20Tq")
PRIVATE_KEY = os.getenv("ADMIN_PRIVATE_KEY", "3f341858abd1ecc6c2d44fad653f48223c4a4dc30bb9504769f2e01be35696f9")
TOKEN_ADDRESS = os.getenv("REWARD_TOKEN_ADDRESS", "0xe1edb9510e468c745ccad91238b83cf63bf7c7ad")
NETWORK = os.getenv("NETWORK", "mainnet")

w3 = None
admin_account = None

def initialize_web3():
    global w3, admin_account
    if not ALCHEMY_KEY:
        return False
    try:
        if NETWORK == "sepolia":
            provider_url = f"https://eth-sepolia.g.alchemy.com/v2/{ALCHEMY_KEY}"
        else:
            provider_url = f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"
        w3 = Web3(Web3.HTTPProvider(provider_url))
        if not w3.is_connected():
            return False
        if PRIVATE_KEY:
            pk = PRIVATE_KEY if PRIVATE_KEY.startswith('0x') else f"0x{PRIVATE_KEY}"
            admin_account = w3.eth.account.from_key(pk)
            return True
        return False
    except Exception as e:
        logger.error(f"Web3 error: {str(e)}")
        return False

initialize_web3()

TOKEN_ABI = [{"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "mint", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"}]

STRATEGIES = {"aave": {"apy": 0.85, "weight": 0.15}, "uniswap": {"apy": 2.45, "weight": 0.18}}
AI_BOOST = 2.5
user_sessions = {}

class EngineRequest(BaseModel):
    walletAddress: str
    miningContract: str
    yieldAggregator: str
    strategies: list

def mint_tokens(wallet_address, amount):
    if not w3 or not admin_account:
        return None
    try:
        token_amount = int(amount * 10**18)
        if token_amount <= 0:
            return None
        token_contract = w3.eth.contract(address=Web3.to_checksum_address(TOKEN_ADDRESS), abi=TOKEN_ABI)
        gas_price = int(w3.eth.gas_price * 1.2)
        nonce = w3.eth.get_transaction_count(admin_account.address)
        transaction = token_contract.functions.mint(Web3.to_checksum_address(wallet_address), token_amount).build_transaction({'from': admin_account.address, 'nonce': nonce, 'gas': 200000, 'gasPrice': gas_price, 'chainId': w3.eth.chain_id})
        signed_tx = admin_account.sign_transaction(transaction)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt['status'] == 1:
            return tx_hash.hex()
        return None
    except Exception as e:
        logger.error(f"Mint error: {str(e)}")
        return None

@app.get("/")
def root():
    return {"status": "online", "service": "Ultra Earning Backend", "version": "10.0.0"}

@app.post("/api/engine/start")
def start_engine(req: EngineRequest):
    wallet = req.walletAddress.lower()
    user_sessions[wallet] = {"start_time": datetime.now().timestamp(), "total_earned": 0.0, "last_mint_time": datetime.now().timestamp()}
    return {"success": True, "wallet": wallet}

@app.get("/api/engine/metrics")
def get_metrics(x_wallet_address: str = Header(None)):
    if not x_wallet_address:
        raise HTTPException(status_code=400, detail="Wallet required")
    wallet = x_wallet_address.lower()
    if wallet not in user_sessions:
        user_sessions[wallet] = {"start_time": datetime.now().timestamp(), "total_earned": 0.0, "last_mint_time": datetime.now().timestamp()}
    session = user_sessions[wallet]
    now = datetime.now().timestamp()
    seconds_running = now - session["start_time"]
    seconds_since_mint = now - session["last_mint_time"]
    principal = 100000.0
    total_apy = sum(s["apy"] * s["weight"] for s in STRATEGIES.values()) * AI_BOOST
    per_second = total_apy / (365 * 24 * 3600)
    new_earnings = principal * per_second * seconds_running
    session["total_earned"] += new_earnings
    accumulated = session["total_earned"]
    if seconds_since_mint >= 10 and accumulated > 0.001:
        if w3 and admin_account:
            try:
                tx_hash = mint_tokens(wallet, accumulated)
                if tx_hash:
                    session["last_mint_time"] = now
                    session["total_earned"] = 0.0
                    accumulated = 0.0
            except:
                pass
    hourly = (new_earnings / seconds_running * 3600) if seconds_running > 0 else 0
    return {"totalProfit": accumulated, "hourlyRate": hourly, "dailyProfit": hourly * 24, "activePositions": len(STRATEGIES)}

@app.post("/api/engine/withdraw")
def withdraw(data: dict):
    wallet = data.get("walletAddress")
    amount = data.get("amount", 0)
    if not w3 or not admin_account:
        raise HTTPException(status_code=503, detail="Blockchain unavailable")
    try:
        tx_hash = mint_tokens(wallet, amount)
        if tx_hash:
            if wallet.lower() in user_sessions:
                user_sessions[wallet.lower()]["total_earned"] = 0.0
            return {"success": True, "txHash": tx_hash}
        raise HTTPException(status_code=500, detail="Transaction failed")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
