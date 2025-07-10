import asyncio, time, random, json
from functools import partial
import httpx
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.keypair import Keypair
from solana.transaction import Transaction
from spl.token.instructions import close_account
from solana.rpc.types import TxOpts, TokenAccountOpts
from solana.rpc.commitment import Confirmed

# ==== CONFIG ====
NUM_BLOCKS = 500
MAX_WALLETS = 30
KEYPAIR_PATH = "phantom_keypair.json"
RPC_ENDPOINTS = ["https://api.mainnet-beta.solana.com"]
RATE_LIMIT = 3
TOKEN_PROGRAM_PUBKEY = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
# ================

req_count = 0
last_reset = time.time()

def load_keypair():
    with open(KEYPAIR_PATH, "r") as f:
        secret = json.load(f)
    kp = Keypair.from_secret_key(bytes(secret))
    print(f"[*] Loaded keypair: {kp.public_key}")
    return kp

def throttle():
    global req_count, last_reset
    now = time.time()
    if now - last_reset >= 1.0:
        last_reset, req_count = now, 0
    req_count += 1
    if req_count > RATE_LIMIT:
        time.sleep(1 - (now - last_reset))

async def rpc_with_retry(func, *args, max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            return await func(*args)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                delay = float(e.response.headers.get("Retry-After", 2 ** attempt))
                print(f"[429] Rate limited – retry {attempt}, sleeping {delay:.1f}s")
                await asyncio.sleep(delay)
            else:
                raise
    raise Exception(f"RPC {func.__name__} failed after {max_retries} retries")

def get_client():
    return AsyncClient(random.choice(RPC_ENDPOINTS))

async def find_recent_wallets():
    print(f"[*] Scanning last {NUM_BLOCKS} blocks...")
    async with get_client() as client:
        slot_resp = await rpc_with_retry(client.get_slot)
        start_slot = slot_resp.value
        found = set()
        get_block = partial(client.get_block, max_supported_transaction_version=0)

        for i in range(NUM_BLOCKS):
            throttle()
            blk = (await rpc_with_retry(get_block, start_slot - i)).value
            if blk and blk.transactions:
                for tx in blk.transactions:
                    for pk in tx.transaction.message.account_keys:
                        s = str(pk)
                        if not s.startswith(("111111", "Sysvar", "BPFLoader")):
                            found.add(s)
                            if len(found) >= MAX_WALLETS:
                                return list(found)
        print(f"[+] Found {len(found)} wallets")
        return list(found)

async def harvest_wallet(wallet_addr: str, signer_kp: Keypair, client: AsyncClient) -> int:
    print(f"\n[!] Scanning wallet: {wallet_addr}")
    resp = await rpc_with_retry(
        client.get_token_accounts_by_owner_json_parsed,
        Pubkey.from_string(wallet_addr),
        TokenAccountOpts(program_id=TOKEN_PROGRAM_PUBKEY),   # *** <--- FIXED: pass string!
        Confirmed
    )
    accounts = resp.value or []
    if not accounts:
        print("  [⏭️] No token accounts.")
        return 0

    closed = 0
    for acct in accounts:
        info = acct.to_json()
        parsed = info["account"]["data"]["parsed"]["info"]
        ui_amt = parsed["tokenAmount"]["uiAmount"]
        pub = info["pubkey"]

        if ui_amt == 0:
            print(f"  [💀] Closing empty account: {pub}")
            instr = close_account(
                account=Pubkey.from_string(pub),
                owner=Pubkey.from_string(wallet_addr),
                dest=signer_kp.public_key,
                program_id=Pubkey.from_string(TOKEN_PROGRAM_PUBKEY)
            )
            try:
                sig = await client.send_transaction(
                    Transaction().add(instr),
                    signer_kp,
                    opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
                )
                print(f"    [✅] Closed {pub}: {sig.value}")
                closed += 1
            except Exception as e:
                print(f"    [❌] Failed to close {pub}: {e}")
        else:
            print(f"  [⏭️] Non-empty skipped: {pub}")

    return closed

async def main():
    kp = load_keypair()
    wallets = await find_recent_wallets()
    total_closed = 0
    async with get_client() as client:
        for w in wallets:
            await asyncio.sleep(0.3)
            total_closed += await harvest_wallet(w, kp, client)
    print(f"\n[🏁] Done — closed total: {total_closed}")

if __name__ == "__main__":
    asyncio.run(main())
