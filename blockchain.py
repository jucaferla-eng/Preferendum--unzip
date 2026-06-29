"""
blockchain.py - Preferendum blockchain integration
Connects the backend to the PreferendumVote smart contract on Polygon.

Setup:
1. Deploy PreferendumVote.sol to Polygon Mumbai (testnet) or Mainnet
2. Set environment variables:
   - CONTRACT_ADDRESS   = 0x...  (deployed contract address)
   - WALLET_ADDRESS     = 0x...  (Preferendum wallet)
   - WALLET_PRIVATE_KEY = 0x...  (NEVER commit this — use Render env vars)
   - POLYGON_RPC_URL    = https://polygon-rpc.com  (or Mumbai testnet)

En memoria de Jose Ignacio Fernandez (1989-2024)
"""

import os
import hashlib
import json
from typing import Optional

# ── CONTRACT ABI ──────────────────────────────────────────────
# Only the functions we need from PreferendumVote.sol
CONTRACT_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "debateId",  "type": "uint256"},
            {"internalType": "bytes32", "name": "voteHash",  "type": "bytes32"},
            {"internalType": "string",  "name": "vcode",     "type": "string"}
        ],
        "name": "anchorVote",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256",   "name": "debateId",   "type": "uint256"},
            {"internalType": "bytes32[]", "name": "voteHashes", "type": "bytes32[]"},
            {"internalType": "string[]",  "name": "vcodes",     "type": "string[]"}
        ],
        "name": "anchorVoteBatch",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "debateId",    "type": "uint256"},
            {"internalType": "string",  "name": "title",       "type": "string"},
            {"internalType": "string",  "name": "institution", "type": "string"}
        ],
        "name": "openDebate",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "debateId", "type": "uint256"}
        ],
        "name": "closeDebate",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "string", "name": "vcode", "type": "string"}
        ],
        "name": "verifyByCode",
        "outputs": [
            {"internalType": "bool",    "name": "exists",    "type": "bool"},
            {"internalType": "bytes32", "name": "voteHash",  "type": "bytes32"},
            {"internalType": "uint256", "name": "debateId",  "type": "uint256"},
            {"internalType": "uint256", "name": "timestamp", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "voteHash", "type": "bytes32"}
        ],
        "name": "verifyByHash",
        "outputs": [
            {"internalType": "bool",   "name": "exists", "type": "bool"},
            {"internalType": "string", "name": "vcode",  "type": "string"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "totalVotesAnchored",
        "outputs": [
            {"internalType": "uint256", "name": "", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

# ── BLOCKCHAIN CLIENT ─────────────────────────────────────────

class PreferendumBlockchain:
    """
    Interface between Preferendum backend and Polygon smart contract.
    Falls back to mock mode if web3 is not installed or contract not deployed.
    """

    def __init__(self):
        self.contract_address = os.getenv('CONTRACT_ADDRESS')
        self.wallet_address   = os.getenv('WALLET_ADDRESS')
        self.private_key      = os.getenv('WALLET_PRIVATE_KEY') or self._read_secret('WALLET_PRIVATE_KEY')
        self.rpc_url          = os.getenv('POLYGON_RPC_URL', 'https://1rpc.io/matic')
        self.web3             = None
        self.contract         = None
        self.live             = False
        self._init()

    @staticmethod
    def _read_secret(name: str) -> str:
        for path in [f'/etc/secrets/{name}', f'./{name}']:
            try:
                with open(path, 'r') as f:
                    return f.read().strip()
            except Exception:
                pass
        return ''

    def _init(self):
        """Try to connect to Polygon. Fall back to mock if not configured."""
        if not all([self.contract_address, self.wallet_address, self.private_key]):
            print('[Blockchain] Running in MOCK mode — set CONTRACT_ADDRESS, WALLET_ADDRESS, WALLET_PRIVATE_KEY to go live')
            return

        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not w3.is_connected():
                print(f'[Blockchain] Cannot connect to {self.rpc_url} — using mock mode')
                return

            self.web3     = w3
            self.contract = w3.eth.contract(
                address=Web3.to_checksum_address(self.contract_address),
                abi=CONTRACT_ABI
            )
            self.live = True
            print(f'[Blockchain] LIVE — Connected to Polygon at {self.contract_address}')

        except ImportError:
            print('[Blockchain] web3 not installed — using mock mode')
            print('[Blockchain] Add web3==6.11.1 to requirements.txt to go live')
        except Exception as e:
            print(f'[Blockchain] Init error: {e} — using mock mode')

    def _mock_tx(self, vote_hash: str) -> str:
        """Generate a realistic-looking mock transaction hash."""
        return '0x' + hashlib.sha256(f'polygon-mock-{vote_hash}'.encode()).hexdigest()

    def _chain_id(self) -> int:
        """Detect chainId from RPC URL: Amoy=80002, mainnet=137."""
        rpc = self.rpc_url or ''
        if 'amoy' in rpc:
            return 80002
        if 'mumbai' in rpc:
            return 80001
        return 137

    def _send_transaction(self, func) -> Optional[str]:
        """Sign and send a transaction to Polygon."""
        try:
            w3 = self.web3
            nonce = w3.eth.get_transaction_count(
                w3.to_checksum_address(self.wallet_address)
            )
            gas_price = int(w3.eth.gas_price * 1.1)

            tx = func.build_transaction({
                'from':     w3.to_checksum_address(self.wallet_address),
                'nonce':    nonce,
                'gas':      200000,
                'gasPrice': gas_price,
                'chainId':  self._chain_id(),
            })

            signed = w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
            return tx_hash.hex()

        except Exception as e:
            print(f'[Blockchain] Transaction error: {e}')
            return None

    # ── PUBLIC METHODS ────────────────────────────────────────

    def anchor_vote(self, debate_id: int, vote_hash: str, vcode: str) -> dict:
        """
        Anchor a single vote on Polygon.

        Args:
            debate_id:  Database debate ID
            vote_hash:  SHA-256 hex string of encrypted vote
            vcode:      Voter's verification code (XXXX-XXXX-XXXX)

        Returns:
            {'tx_hash': '0x...', 'live': bool, 'success': bool}
        """
        if not self.live:
            tx_hash = self._mock_tx(vote_hash)
            return {'tx_hash': tx_hash, 'live': False, 'success': True}

        try:
            # Convert hex hash string to bytes32
            hash_bytes = bytes.fromhex(vote_hash)

            func = self.contract.functions.anchorVote(
                debate_id,
                hash_bytes,
                vcode
            )
            tx_hash = self._send_transaction(func)

            if tx_hash:
                return {'tx_hash': tx_hash, 'live': True, 'success': True}
            else:
                # Fallback to mock if tx fails
                return {'tx_hash': self._mock_tx(vote_hash), 'live': False, 'success': False}

        except Exception as e:
            print(f'[Blockchain] anchor_vote error: {e}')
            return {'tx_hash': self._mock_tx(vote_hash), 'live': False, 'success': False}

    def anchor_vote_batch(self, debate_id: int, votes: list) -> dict:
        """
        Anchor multiple votes in one transaction. More gas efficient.

        Args:
            debate_id: Database debate ID
            votes: List of {'vote_hash': str, 'vcode': str}

        Returns:
            {'tx_hash': '0x...', 'count': int, 'live': bool}
        """
        if not self.live:
            combined = ''.join(v['vote_hash'] for v in votes)
            tx_hash = self._mock_tx(combined)
            return {'tx_hash': tx_hash, 'count': len(votes), 'live': False}

        try:
            hashes = [bytes.fromhex(v['vote_hash']) for v in votes]
            vcodes = [v['vcode'] for v in votes]

            func = self.contract.functions.anchorVoteBatch(debate_id, hashes, vcodes)
            tx_hash = self._send_transaction(func)

            return {
                'tx_hash': tx_hash or self._mock_tx('batch'),
                'count':   len(votes),
                'live':    tx_hash is not None
            }

        except Exception as e:
            print(f'[Blockchain] batch error: {e}')
            return {'tx_hash': self._mock_tx('batch'), 'count': len(votes), 'live': False}

    def open_debate(self, debate_id: int, title: str, institution: str) -> dict:
        """Register a debate opening on-chain."""
        if not self.live:
            return {'tx_hash': self._mock_tx(f'open-{debate_id}'), 'live': False}

        try:
            func = self.contract.functions.openDebate(debate_id, title, institution)
            tx_hash = self._send_transaction(func)
            return {'tx_hash': tx_hash, 'live': True}
        except Exception as e:
            print(f'[Blockchain] open_debate error: {e}')
            return {'tx_hash': self._mock_tx(f'open-{debate_id}'), 'live': False}

    def close_debate(self, debate_id: int) -> dict:
        """Register a debate closing on-chain."""
        if not self.live:
            return {'tx_hash': self._mock_tx(f'close-{debate_id}'), 'live': False}

        try:
            func = self.contract.functions.closeDebate(debate_id)
            tx_hash = self._send_transaction(func)
            return {'tx_hash': tx_hash, 'live': True}
        except Exception as e:
            print(f'[Blockchain] close_debate error: {e}')
            return {'tx_hash': self._mock_tx(f'close-{debate_id}'), 'live': False}

    def verify_by_code(self, vcode: str) -> dict:
        """
        Verify a vote on-chain using its verification code.
        This is a READ operation — free, no gas needed.
        """
        if not self.live:
            return {
                'exists':    True,
                'vcode':     vcode,
                'vote_hash': hashlib.sha256(vcode.encode()).hexdigest(),
                'debate_id': 0,
                'timestamp': 0,
                'live':      False,
                'note':      'Mock verification — deploy contract for real blockchain verification'
            }

        try:
            result = self.contract.functions.verifyByCode(vcode).call()
            exists, vote_hash, debate_id, timestamp = result
            return {
                'exists':    exists,
                'vcode':     vcode,
                'vote_hash': vote_hash.hex() if exists else None,
                'debate_id': debate_id,
                'timestamp': timestamp,
                'live':      True
            }
        except Exception as e:
            print(f'[Blockchain] verify error: {e}')
            return {'exists': False, 'error': str(e), 'live': False}

    def get_total_votes(self) -> int:
        """Get total votes anchored across all debates."""
        if not self.live:
            return -1
        try:
            return self.contract.functions.totalVotesAnchored().call()
        except:
            return -1

    def status(self) -> dict:
        """Return blockchain connection status — never raises."""
        try:
            chain = self._chain_id()
            net_name = {137: 'Polygon Mainnet', 80002: 'Polygon Amoy Testnet', 80001: 'Polygon Mumbai (deprecated)'}.get(chain, f'Unknown (chainId {chain})')
            return {
                'live':             self.live,
                'network':          net_name if self.live else 'Mock mode',
                'chain_id':         chain,
                'contract_address': self.contract_address or 'Not deployed',
                'wallet':           self.wallet_address or 'Not configured',
                'rpc_url':          self.rpc_url,
                'total_anchored':   self.get_total_votes(),
            }
        except Exception as e:
            return {'live': False, 'network': 'Mock mode', 'error': str(e)}


# ── SINGLETON ─────────────────────────────────────────────────
# Import this instance in main.py
blockchain = PreferendumBlockchain()
