from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from web3 import Web3
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Ultra Backend V12")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

ALCHEMY_KEY = os.getenv("ALCHEMY_API_KEY", "j6uyDNnArwlEpG44o93SqZ0JixvE20Tq")
ADMIN_KEY = os.getenv("ADMIN_PRIVATE_KEY", "0x76efd894c952f65bba1d8730349af94de3da56516bd2f3de02b07adbda0a0037")
NETWORK = os.getenv("NETWORK", "mainnet")

# All 3 production contracts hardcoded
CONTRACTS = [
    {"id": 1, "name": "Primary", "address": "0x29983BE497D4c1D39Aa80D20Cf74173ae81D2af5"},
    {"id": 2, "name": "Secondary", "address": "0x0b8Add0d32eFaF79E6DB4C58CcA61D6eFBCcAa3D"},
    {"id": 3, "name": "Tertiary", "address": "0xf97A395850304b8ec9B8f9c80A17674886612065"}
]

web3_instance = None
admin_account = None

def init_web3():
    global web3_instance, admin_account
    if not ALCHEMY_KEY:
        return False
    try:
        web3_instance = Web3(Web3.HTTPProvider(f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"))
        if not web3_instance.is_connected():
            return False
        logger.info("Connected to Ethereum")
        for contract in CONTRACTS:
            logger.info(f"{contract['name']}: {contract['address']}")
        if ADMIN_KEY:
            private_key = ADMIN_KEY if ADMIN_KEY.startswith('0x') else f"0x{ADMIN_KEY}"
            admin_account = web3_instance.eth.account.from_key(private_key)
            logger.info(f"Admin: {admin_account.address}")
            return True
        return False
    except Exception as error:
        logger.error(f"Error: {error}")
        return False

web3_ready = init_web3()

TOKEN_ABI = [
    {"inputs": [{"type": "address"}, {"type": "uint256"}], "name": "mint", "type": "function"},
    {"inputs": [{"type": "address"}, {"type": "uint256"}], "name": "transfer", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "type": "function"}
]

sessions = {}

def process_withdrawal(user_wallet, amount_usd, preferred_contract):
    if not web3_instance or not admin_account:
        raise HTTPException(503, "Not connected")
    if not Web3.is_address(user_wallet):
        raise ValueError("Invalid address")
    if amount_usd <= 0:
        raise ValueError("Invalid amount")
    
    contract_list = []
    if preferred_contract:
        for contract in CONTRACTS:
            if contract["address"].lower() == preferred_contract.lower():
                contract_list.append(contract)
                break
    for contract in CONTRACTS:
        if contract not in contract_list:
            contract_list.append(contract)
    
    logger.info(f"Withdraw {amount_usd} to {user_wallet}")
    
    for index, contract_data in enumerate(contract_list):
        logger.info(f"Try {index+1}: {contract_data['name']}")
        try:
            token_contract = web3_instance.eth.contract(
                address=Web3.to_checksum_address(contract_data["address"]), 
                abi=TOKEN_ABI
            )
            try:
                token_symbol = token_contract.functions.symbol().call()
                token_decimals = token_contract.functions.decimals().call()
            except:
                token_symbol = "TOKEN"
                token_decimals = 18
            
            amount_in_wei = int(amount_usd * (10 ** token_decimals))
            current_gas_price = web3_instance.eth.gas_price
            current_nonce = web3_instance.eth.get_transaction_count(admin_account.address)
            
            try:
                mint_tx = token_contract.functions.mint(
                    Web3.to_checksum_address(user_wallet), 
                    amount_in_wei
                ).build_transaction({
                    'from': admin_account.address, 
                    'nonce': current_nonce, 
                    'gas': 200000, 
                    'gasPrice': int(current_gas_price * 1.2), 
                    'chainId': web3_instance.eth.chain_id
                })
                signed_mint_tx = admin_account.sign_transaction(mint_tx)
                mint_hash = web3_instance.eth.send_raw_transaction(signed_mint_tx.rawTransaction)
                mint_receipt = web3_instance.eth.wait_for_transaction_receipt(mint_hash, 120)
                if mint_receipt['status'] == 1:
                    logger.info("Mint success")
                    return {
                        "success": True, 
                        "method": "mint", 
                        "contract": contract_data['name'], 
                        "contractAddress": contract_data["address"], 
                        "txHash": mint_hash.hex(), 
                        "blockNumber": mint_receipt['blockNumber'], 
                        "symbol": token_symbol
                    }
            except:
                try:
                    new_nonce = web3_instance.eth.get_transaction_count(admin_account.address)
                    transfer_tx = token_contract.functions.transfer(
                        Web3.to_checksum_address(user_wallet), 
                        amount_in_wei
                    ).build_transaction({
                        'from': admin_account.address, 
                        'nonce': new_nonce, 
                        'gas': 100000, 
                        'gasPrice': int(current_gas_price * 1.2), 
                        'chainId': web3_instance.eth.chain_id
                    })
                    signed_transfer_tx = admin_account.sign_transaction(transfer_tx)
                    transfer_hash = web3_instance.eth.send_raw_transaction(signed_transfer_tx.rawTransaction)
                    transfer_receipt = web3_instance.eth.wait_for_transaction_receipt(transfer_hash, 120)
                    if transfer_receipt['status'] == 1:
                        logger.info("Transfer success")
                        return {
                            "success": True, 
                            "method": "transfer", 
                            "contract": contract_data['name'], 
                            "contractAddress": contract_data["address"], 
                            "txHash": transfer_hash.hex(), 
                            "blockNumber": transfer_receipt['blockNumber'], 
                            "symbol": token_symbol
                        }
                except:
                    continue
        except:
            continue
    raise HTTPException(500, "All contracts failed")

@app.get("/")
def root():
    admin_addr = admin_account.address if admin_account else None
    admin_balance = None
    if admin_account and web3_instance:
        try:
            bal = web3_instance.eth.get_balance(admin_account.address)
            admin_balance = float(web3_instance.from_wei(bal, 'ether'))
        except:
            pass
    return {
        "status": "online", 
        "version": "12.0.0", 
        "web3_ready": web3_ready, 
        "admin_wallet": admin_addr,
        "admin_eth_balance": admin_balance,
        "contracts": CONTRACTS, 
        "total": 3
    }

@app.post("/api/engine/start")
def start(data: dict):
    user_wallet = data.get("walletAddress", "").lower()
    sessions[user_wallet] = {"start": datetime.now().timestamp()}
    return {"success": True}

@app.get("/api/engine/metrics")
def metrics(x_wallet_address: str = Header(None)):
    return {"hourlyRate": 6.0, "dailyProfit": 144.0, "activePositions": 7}

@app.post("/api/engine/withdraw")
def withdraw_endpoint(data: dict):
    if not web3_ready:
        raise HTTPException(503, "Not connected")
    user_wallet = data.get("walletAddress")
    amount_requested = float(data.get("amount", 0))
    preferred = data.get("tokenAddress")
    if not user_wallet or amount_requested <= 0:
        raise HTTPException(400, "Invalid request")
    try:
        return process_withdrawal(user_wallet, amount_requested, preferred)
    except Exception as error:
        raise HTTPException(500, str(error))

@app.post("/api/engine/stop")
def stop(data: dict):
    return {"success": True}

@app.get("/api/health")
def health():
    return {"web3": web3_instance.is_connected() if web3_instance else False, "contracts": CONTRACTS}

@app.get("/api/contracts")
def get_contracts():
    return {"contracts": CONTRACTS, "total": 3}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
