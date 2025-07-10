import base58
import csv
import requests
import time
from datetime import datetime
from solana.publickey import PublicKey
from solana.rpc.api import Client
from solana.transaction import Transaction
from solana.keypair import Keypair
from solana.rpc.types import TxOpts
from solana.rpc.commitment import Confirmed
from spl.token.instructions import get_associated_token_address, create_associated_token_account
from spl.token.constants import TOKEN_PROGRAM_ID
from solana.transaction import TransactionInstruction, AccountMeta

# === Your Receiver Wallet ===
receiver_wallet = PublicKey("5n6kEgrsgokKC9aNo4cToD1gQ5YSC7QJD5hnu9CPsssE")

# === Your Private Key (base58 Phantom format) ===
base58_key = "4uei6YuVhj6nN9SpLiEkZh6a9M9zNJtxnLgVJ3kEGbZucozrfMszt48fwCajgeugdJYWCVKX9zTA2Dehj6dnjSDW"
keypair = Keypair.from_secret_key(base58.b58decode(base58_key))
print("🔑 Wallet loaded:", keypair.public_key)

# === Constants ===
client = Client("https://api.mainnet-beta.solana.com")
log_file = "harvested_log.csv"

# === Stats ===
wallets_scanned = 0
transferred_count = 0
closed_count = 0
skipped_count = 0
error_count = 0

# === Init Log File ===
with open(log_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Timestamp", "Wallet", "TokenAccount", "Status", "TX_Hash_or_Error"])

# === Create ATA if needed ===
def ensure_ata_exists(mint):
    ata = get_associated_token_address(receiver_wallet, PublicKey(mint))
    account_info = client.get_account_info(ata)
    if account_info.value is None:

        print(f"[+] Creating ATA for token: {mint}")
        tx = Transaction()
        tx.add(
            create_associated_token_account(
                payer=keypair.public_key,
                owner=receiver_wallet,
                mint=PublicKey(mint)
            )
        )
        try:
            result = client.send_transaction(tx, keypair)
            client.confirm_transaction(result.value, commitment="finalized")
        except Exception as e:
            print(f"[!] Failed to create ATA for {mint}: {e}")
            return None
    return ata

# === Get Wallets from Recent Blocks ===
def get_wallets_from_blocks(slots=5):
    wallets = set()
    latest_slot = client.get_slot().value
    for i in range(slots):
        slot = latest_slot - i
        try:
            block = client.get_block(slot, max_supported_transaction_version=0)
            if not block.value:
                continue
            for tx in block.value.transactions:
                for acc in tx.transaction.message.account_keys:
                    wallets.add(str(acc))
        except Exception as e:
            print(f"[!] Error slot {slot}: {e}")
    return list(wallets)

# === Get Token Accounts for Wallet ===
def get_token_accounts(wallet):
    opts = {"encoding": "jsonParsed"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [wallet, {"programId": str(TOKEN_PROGRAM_ID)}, opts]
    }
    try:
        res = requests.post("https://api.mainnet-beta.solana.com", json=payload).json()
        return res["result"]["value"]
    except Exception:
        return []

# === Transfer and Close Token Account ===
def transfer_and_close(account_pub, amount, decimals, mint, wallet_owner):
    global transferred_count, closed_count, error_count

    try:
        dest_ata = ensure_ata_exists(mint)
        if dest_ata is None:
            skipped_count += 1
            return

        for attempt in range(3):
            try:
                tx = Transaction()

                # === Transfer SPL Token ===
                tx.add(TransactionInstruction(
                    program_id=TOKEN_PROGRAM_ID,
                    data=bytes([12]) + amount.to_bytes(8, byteorder="little") + bytes([decimals]),
                    keys=[
                        AccountMeta(pubkey=PublicKey(account_pub), is_signer=False, is_writable=True),
                        AccountMeta(pubkey=dest_ata, is_signer=False, is_writable=True),
                        AccountMeta(pubkey=PublicKey(mint), is_signer=False, is_writable=False),
                        AccountMeta(pubkey=keypair.public_key, is_signer=True, is_writable=False),
                    ],
                ))

                # === Close Token Account (instruction 9) ===
                tx.add(TransactionInstruction(
                    program_id=TOKEN_PROGRAM_ID,
                    data=bytes([9]),
                    keys=[
                        AccountMeta(pubkey=PublicKey(account_pub), is_signer=False, is_writable=True),
                        AccountMeta(pubkey=receiver_wallet, is_signer=False, is_writable=True),
                        AccountMeta(pubkey=keypair.public_key, is_signer=True, is_writable=False),
                    ],
                ))

                result = client.send_transaction(tx, keypair, opts=TxOpts(skip_preflight=False))
                client.confirm_transaction(result.value, commitment="finalized")

                tx_hash = result.value
                transferred_count += 1
                closed_count += 1
                print(f"[✅] TRANSFER+CLOSE: {account_pub} → TX: https://solscan.io/tx/{tx_hash}")
                log_row(wallet_owner, account_pub, "TRANSFER+CLOSE", f"https://solscan.io/tx/{tx_hash}")
                break

            except Exception as e:
                print(f"[!] Retry {attempt+1}/3 FAILED: {e}")
                if attempt == 2:
                    error_count += 1
                    log_row(wallet_owner, account_pub, "FAILED", str(e))
                time.sleep(2)

    except Exception as e:
        error_count += 1
        print(f"[❌] FAILED: {account_pub} from {wallet_owner} → {str(e)}")
        log_row(wallet_owner, account_pub, "FAILED", str(e))

# === Log to CSV ===
def log_row(wallet, token_account, status, result):
    with open(log_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.utcnow(), wallet, token_account, status, result])

# === Main Execution ===
def main():
    global skipped_count, wallets_scanned
    print(f"[🔍] Scanning latest Solana blocks...")
    wallets = get_wallets_from_blocks(10)
    print(f"[🧠] Found {len(wallets)} unique wallets.\n")

    for i, wallet in enumerate(wallets):
        wallets_scanned += 1
        print(f"[{i+1}/{len(wallets)}] Checking wallet: {wallet}")
        try:
            token_accounts = get_token_accounts(wallet)
            if not token_accounts:
                print(f"[⏭️] No token accounts found.")
                continue

            for acc in token_accounts:
                info = acc["account"]["data"]["parsed"]["info"]
                amount = int(info["tokenAmount"]["amount"])
                decimals = int(info["tokenAmount"]["decimals"])
                mint = info["mint"]
                account_pub = acc["pubkey"]

                if amount == 0:
                    skipped_count += 1
                    continue

                transfer_and_close(account_pub, amount, decimals, mint, wallet)
        except Exception as e:
            print(f"[!] Error wallet {wallet}: {e}")
            log_row(wallet, "N/A", "WALLET_ERROR", str(e))
        time.sleep(0.1)

    print("\n========== ✅ HARVEST SUMMARY ==========")
    print(f"Scanned Wallets       : {wallets_scanned}")
    print(f"Transferred Accounts  : {transferred_count}")
    print(f"Closed Accounts       : {closed_count}")
    print(f"Skipped (zero/ATA)    : {skipped_count}")
    print(f"Errors                : {error_count}")
    print(f"Results Logged In     : {log_file}")

if __name__ == "__main__":
    main()
