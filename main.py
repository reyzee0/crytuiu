from web3 import Web3

# ==== Replace with your info ====
RPC = "https://mainnet.infura.io/v3/f9c379bd7ea34bd9a04a4a03328b7b58"
wallet_address = Web3.to_checksum_address("0xf12bc0bc633c4c7307d8c5a52a45b55ebd2db50d")
private_key = "00275d47d0873e817ab5c832b5290f817089532f2a88470a9fac814facdf33f2"  # keep private
# ================================

contract_address = Web3.to_checksum_address("0xCa00F9b8b2E27E5cE0aED48Dcb2e66c82D6f8438")

abi = [
    {
        "inputs": [],
        "name": "claimTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

w3 = Web3(Web3.HTTPProvider(RPC))
contract = w3.eth.contract(address=contract_address, abi=abi)

nonce = w3.eth.get_transaction_count(wallet_address)

txn = contract.functions.claimTokens().build_transaction({
    'from': wallet_address,
    'nonce': nonce,
    'gas': 150000,
    'gasPrice': w3.to_wei("20", "gwei")
})

signed = w3.eth.account.sign_transaction(txn, private_key)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

print(f"✅ TX sent: https://etherscan.io/tx/{tx_hash.hex()}")

