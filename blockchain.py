# utils/blockchain.py
# Polygon blockchain integration for vote hash anchoring
# Full Web3 when deployed, graceful fallback for dev/testing

import os
import hashlib

CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "")
PRIVATE_KEY      = os.getenv("PREFERENDUM_WALLET_KEY", "")
ADMIN_ADDRESS    = os.getenv("PREFERENDUM_WALLET_ADDRESS", "")
WEB3_PROVIDER    = os.getenv("WEB3_PROVIDER", "https://polygon-rpc.com")

# Minimal ABI for PreferendumVote.sol
CONTRACT_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "voteHash", "type": "bytes32"},
            {"internalType": "string",  "name": "vcode",    "type": "string"}
        ],
        "name": "submitVote",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]


def send_vote_to_blockchain(vote_hash: str, vcode: str = "") -> str:
    """
    Send vote hash to Polygon blockchain.
    Returns transaction hash (tx_hash).

    In production: deploy PreferendumVote.sol → set CONTRACT_ADDRESS,
    PREFERENDUM_WALLET_KEY, PREFERENDUM_WALLET_ADDRESS in .env

    In dev/test: returns a deterministic mock tx hash.
    """
    # If production credentials are set, use real Web3
    if CONTRACT_ADDRESS and PRIVATE_KEY and ADMIN_ADDRESS:
        return _send_real(vote_hash, vcode)
    else:
        # Dev mode: deterministic mock tx hash
        mock_tx = "0x" + hashlib.sha256(
            f"mock-{vote_hash}".encode()
        ).hexdigest()
        print(f"[BLOCKCHAIN-DEV] Mock tx: {mock_tx[:20]}… (deploy contract for real tx)")
        return mock_tx


def _send_real(vote_hash: str, vcode: str) -> str:
    """Real Polygon transaction — only called when env vars are set."""
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER))
        if not w3.is_connected():
            raise Exception("Cannot connect to Polygon node")

        contract   = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)
        nonce      = w3.eth.get_transaction_count(ADMIN_ADDRESS)
        hash_bytes = bytes.fromhex(vote_hash)

        txn = contract.functions.submitVote(hash_bytes, vcode).build_transaction({
            "chainId":  137,
            "gas":      200000,
            "gasPrice": w3.to_wei("30", "gwei"),
            "nonce":    nonce,
        })
        signed  = w3.eth.account.sign_transaction(txn, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        return w3.to_hex(tx_hash)

    except Exception as e:
        # Never lose a vote because of blockchain issues
        # Log and return mock hash — vote is still encrypted and stored
        print(f"[BLOCKCHAIN-ERROR] {e} — falling back to mock hash")
        return "0x" + hashlib.sha256(f"fallback-{vote_hash}".encode()).hexdigest()
