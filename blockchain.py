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
import time
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
    },
    {
        "inputs": [{"internalType": "uint256", "name": "debateId", "type": "uint256"}],
        "name": "debates",
        "outputs": [
            {"internalType": "uint256", "name": "id",          "type": "uint256"},
            {"internalType": "string",  "name": "title",       "type": "string"},
            {"internalType": "string",  "name": "institution", "type": "string"},
            {"internalType": "uint256", "name": "openedAt",    "type": "uint256"},
            {"internalType": "uint256", "name": "closedAt",    "type": "uint256"},
            {"internalType": "bool",    "name": "isOpen",      "type": "bool"},
            {"internalType": "uint256", "name": "totalVotes",  "type": "uint256"},
            {"internalType": "bool",    "name": "exists",      "type": "bool"}
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
        self.live             = False
        self.web3             = None
        self.contract         = None
        self._initialized     = False  # lazy: connect on first use, not at import
        self._init_attempts   = 0      # cap retries at 3
        # Momento en que se agotaron los intentos. Permite reintentar mas
        # tarde en vez de quedarse en modo simulado para siempre (ver
        # _ensure_init: esa era la causa de la intermitencia del anclaje).
        self._gave_up_at      = 0.0
        self.contract_address = (os.getenv('CONTRACT_ADDRESS') or '').strip()
        self.wallet_address   = (os.getenv('WALLET_ADDRESS') or '').strip()
        self.private_key      = (os.getenv('WALLET_PRIVATE_KEY') or self._read_secret('WALLET_PRIVATE_KEY') or '').strip()
        self.rpc_url          = (os.getenv('POLYGON_RPC_URL') or 'https://1rpc.io/matic').strip()

    # CAUSA DE LA INTERMITENCIA — ver _ensure_init.
    # Tiempo que se espera antes de volver a intentar la conexion despues de
    # agotar los intentos. Acota el coste: como el anclaje ocurre dentro del
    # camino de voto, cada reintento puede costarle a UN votante hasta la
    # suma de los timeouts de los RPC candidatos. Con esta espera, ese coste
    # lo paga como maximo un voto cada cinco minutos, en vez de dejar el
    # anclaje muerto hasta el siguiente despliegue.
    _REINTENTO_CONEXION_SEGUNDOS = 300

    def _ensure_init(self):
        """Connect to Polygon on first use, and keep trying later if it failed.

        DEFECTO CORREGIDO — ESTA ERA LA CAUSA DE LA INTERMITENCIA.

        Antes, tras tres intentos fallidos se hacia `self._initialized = True`
        y se devolvia para siempre sin volver a intentarlo:

            if not self.live and self._init_attempts < 3:
                pass          # Will retry on next request
            else:
                self._initialized = True   # Either connected or gave up

        El comentario decia "gave up", y era literal: ese proceso web se
        quedaba en modo SIMULADO durante toda su vida. Si al arrancar —o en
        los tres primeros votos— los RPC publicos estaban caidos, saturados
        o limitando peticiones, todos los votos servidos por ese proceso
        recibian un hash simulado, hasta el siguiente reinicio o despliegue.

        Eso explica exactamente el patron medido en produccion: tramos
        CONTIGUOS de votos simulados y tramos contiguos de votos reales
        (mayo simulados, julio reales, agosto simulados, octubre reales).
        No era aleatorio por voto: era por vida de proceso.

        Correccion minima: no se abandona para siempre. Se mantiene el tope
        de tres intentos seguidos, pero pasado el tiempo de espera se
        permite otra tanda. No se anade ningun mecanismo nuevo: solo deja de
        recordar un fallo transitorio como si fuera permanente.
        """
        if self.live:
            return  # Already connected — fast path
        ahora = time.time()
        if self._initialized:
            if ahora - self._gave_up_at < self._REINTENTO_CONEXION_SEGUNDOS:
                return  # dentro de la espera: no se reintenta todavia
            # Se reabre la ventana de intentos.
            self._initialized   = False
            self._init_attempts = 0
        self._init_attempts += 1
        try:
            self._init()
        except BaseException as e:
            print(f'[Blockchain] connect error ({type(e).__name__}): {e} — running mock')
        if not self.live and self._init_attempts < 3:
            pass  # Will retry on next request
        else:
            self._initialized = True
            if not self.live:
                self._gave_up_at = ahora
                print(f'[Blockchain] sin conexion tras {self._init_attempts} '
                      f'intentos; se reintentara en '
                      f'{self._REINTENTO_CONEXION_SEGUNDOS}s. Mientras tanto '
                      f'los votos se registran SIN anclaje (y se informa asi).')

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
        # Re-read env vars — also check PREFERENDUM_ prefixed names used in Render
        _DEFAULT_CONTRACT = '0xB7fCD1aD46eC0a3ABfaddf95961e435C991dfd36'
        _DEFAULT_WALLET   = '0x668108Ecfd50993Cf3bCcbeE0ADaedF5Fa306d51'
        self.contract_address = (os.getenv('CONTRACT_ADDRESS') or os.getenv('PREFERENDUM_CONTRACT_ADDRESS') or self.contract_address or _DEFAULT_CONTRACT).strip()
        self.wallet_address   = (os.getenv('WALLET_ADDRESS') or os.getenv('PREFERENDUM_WALLET_ADDRESS') or self.wallet_address or _DEFAULT_WALLET).strip()
        self.private_key      = (os.getenv('WALLET_PRIVATE_KEY') or os.getenv('PREFERENDUM_WALLET_KEY') or self._read_secret('WALLET_PRIVATE_KEY') or self.private_key or '').strip()
        self.rpc_url          = (os.getenv('POLYGON_RPC_URL') or self.rpc_url or 'https://1rpc.io/matic').strip()
        print(f'[Blockchain] _init: contract={bool(self.contract_address)} wallet={bool(self.wallet_address)} pk={bool(self.private_key)} pk_len={len(self.private_key)} rpc={self.rpc_url}')
        if not all([self.contract_address, self.wallet_address, self.private_key]):
            print('[Blockchain] Running in MOCK mode — set CONTRACT_ADDRESS, WALLET_ADDRESS, WALLET_PRIVATE_KEY to go live')
            return

        try:
            from web3 import Web3
            # Try configured RPC first, then reliable fallbacks
            rpc_candidates = [
                self.rpc_url,
                'https://rpc.ankr.com/polygon',
                'https://polygon.llamarpc.com',
                'https://polygon.drpc.org',
            ]
            w3 = None
            for rpc in rpc_candidates:
                try:
                    _w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'timeout': 10}))
                    if _w3.is_connected():
                        w3 = _w3
                        if rpc != self.rpc_url:
                            print(f'[Blockchain] Fallback RPC used: {rpc}')
                        break
                    else:
                        print(f'[Blockchain] RPC not connected: {rpc}')
                except Exception as rpc_err:
                    print(f'[Blockchain] RPC error {rpc}: {rpc_err}')
            if w3 is None:
                print('[Blockchain] No RPC reachable — using mock mode')
                return

            self.web3     = w3
            self.contract = w3.eth.contract(
                address=Web3.to_checksum_address(self.contract_address),
                abi=CONTRACT_ABI
            )
            self.live = True
            print(f'[Blockchain] LIVE — Connected to Polygon at {self.contract_address}')

        except BaseException as e:
            print(f'[Blockchain] Init error: {type(e).__name__}: {e} — using mock mode')

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
        """Sign and send a transaction to Polygon. Waits for the receipt and
        only returns a hash if the transaction was MINED AND SUCCEEDED.

        DEFECTO CORREGIDO — antes el resultado del recibo se descartaba:

            try:
                w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            except Exception:
                pass
            return tx_hash.hex()

        Eso devolvia el hash como exito en dos casos en los que el voto NO
        quedaba anclado:

          1. La espera agota los 30 s (red lenta, bloque no minado todavia).
             El `except ... pass` lo tragaba y devolvia el hash igual.
          2. La transaccion se mina pero REVIERTE (`status == 0`): por
             ejemplo si la consulta no esta abierta en el contrato o el
             codigo ya existe. El hash EXISTE en la cadena —de hecho
             `eth_getTransactionByHash` lo encuentra— pero el anclaje
             fracaso. El recibo nunca se miraba.

        Ahora el recibo decide: sin recibo o con `status != 1` no hay
        anclaje, y quien llama se entera.
        """
        try:
            w3 = self.web3
            wallet = w3.to_checksum_address(self.wallet_address)
            nonce = w3.eth.get_transaction_count(wallet)
            gas_price = int(w3.eth.gas_price * 1.2)
            pk = (self.private_key or '').strip()
            if pk and not pk.startswith('0x'):
                pk = '0x' + pk

            tx = func.build_transaction({
                'from':     wallet,
                'nonce':    nonce,
                'gas':      300000,
                'gasPrice': gas_price,
                'chainId':  self._chain_id(),
            })

            signed = w3.eth.account.sign_transaction(tx, pk)
            # web3.py v5 uses rawTransaction, v6 uses raw_transaction
            raw_tx = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)
            tx_hash = w3.eth.send_raw_transaction(raw_tx)
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            except Exception as wait_err:
                # El hash se envio, pero no hay confirmacion. Puede minarse
                # despues; lo que NO se puede hacer es declararlo anclado.
                print(f'[Blockchain] sin recibo para {tx_hash.hex()} '
                      f'({type(wait_err).__name__}): NO se declara anclado')
                return None
            estado = receipt.get('status') if isinstance(receipt, dict) else getattr(receipt, 'status', None)
            if estado != 1:
                print(f'[Blockchain] transaccion {tx_hash.hex()} minada pero '
                      f'REVERTIDA (status={estado}): NO se declara anclado')
                return None
            return tx_hash.hex()

        except Exception as e:
            print(f'[Blockchain] Transaction error: {e}')
            return None

    def _debate_exists_on_chain(self, debate_id: int) -> bool:
        """Read-only check — no gas."""
        try:
            result = self.contract.functions.debates(debate_id).call()
            return result[7]  # 'exists' field (index 7)
        except Exception as e:
            print(f'[Blockchain] debate_exists check error: {e}')
            return False

    def _ensure_debate_open(self, debate_id: int, title: str = '') -> bool:
        """Open the debate on-chain if not already there. Idempotent."""
        if self._debate_exists_on_chain(debate_id):
            return True
        try:
            func = self.contract.functions.openDebate(
                debate_id,
                title or f'Debate {debate_id}',
                'Preferendum'
            )
            tx = self._send_transaction(func)
            if tx:
                print(f'[Blockchain] Debate {debate_id} opened on-chain: {tx}')
                return True
            print(f'[Blockchain] Could not open debate {debate_id} on-chain')
            return False
        except Exception as e:
            print(f'[Blockchain] _ensure_debate_open error: {e}')
            return False

    # ── PUBLIC METHODS ────────────────────────────────────────

    def anchor_vote(self, debate_id: int, vote_hash: str, vcode: str,
                    debate_title: str = '') -> dict:
        self._ensure_init()
        if not self.live:
            # DEFECTO CORREGIDO — esta rama devolvia `success: True` con un
            # hash SIMULADO. main.py calcula `blockchain_anchored = success
            # AND live`, asi que la columna quedaba bien por casualidad,
            # pero el contrato de la funcion mentia: cualquier otro sitio
            # que mirase `success` daria por anclado un voto que no lo esta.
            # Un hash simulado NUNCA es exito de anclaje.
            return {'tx_hash': self._mock_tx(vote_hash), 'live': False,
                    'success': False, 'reason': 'sin conexion a Polygon'}

        try:
            # DEFECTO CORREGIDO — el resultado de abrir la consulta en el
            # contrato se IGNORABA. Si no se puede abrir, `anchorVote`
            # revierte: se gastaba gas real en una transaccion condenada y
            # ademas se devolvia su hash, que existe en la cadena pero NO
            # ancla nada. Ahora, si no se puede abrir, no se envia.
            if not self._ensure_debate_open(debate_id, debate_title):
                return {'tx_hash': self._mock_tx(vote_hash), 'live': False,
                        'success': False,
                        'reason': 'la consulta no esta abierta en el contrato'}

            hash_bytes = bytes.fromhex(vote_hash)
            func = self.contract.functions.anchorVote(debate_id, hash_bytes, vcode)
            tx_hash = self._send_transaction(func)

            if tx_hash:
                return {'tx_hash': tx_hash, 'live': True, 'success': True}
            # Sin recibo, o minada y revertida: no hay anclaje.
            return {'tx_hash': self._mock_tx(vote_hash), 'live': False,
                    'success': False,
                    'reason': 'la transaccion no se confirmo en la cadena'}

        except Exception as e:
            print(f'[Blockchain] anchor_vote error: {e}')
            return {'tx_hash': self._mock_tx(vote_hash), 'live': False,
                    'success': False, 'reason': f'error: {type(e).__name__}'}

    def anchor_vote_batch(self, debate_id: int, votes: list) -> dict:
        """
        Anchor multiple votes in one transaction. More gas efficient.

        Args:
            debate_id: Database debate ID
            votes: List of {'vote_hash': str, 'vcode': str}

        Returns:
            {'tx_hash': '0x...', 'count': int, 'live': bool}
        """
        self._ensure_init()
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
        self._ensure_init()
        if not self.live:
            return {'tx_hash': self._mock_tx(f'open-{debate_id}'), 'live': False}

        try:
            func = self.contract.functions.openDebate(debate_id, title, institution)
            tx_hash = self._send_transaction(func)
            # DEFECTO CORREGIDO — declaraba `live: True` incluso cuando
            # _send_transaction devolvia None, es decir cuando la
            # transaccion no se confirmo. `live` tiene que reflejar lo que
            # de verdad paso en la cadena.
            if tx_hash:
                return {'tx_hash': tx_hash, 'live': True}
            return {'tx_hash': self._mock_tx(f'open-{debate_id}'), 'live': False}
        except Exception as e:
            print(f'[Blockchain] open_debate error: {e}')
            return {'tx_hash': self._mock_tx(f'open-{debate_id}'), 'live': False}

    def close_debate(self, debate_id: int) -> dict:
        """Register a debate closing on-chain."""
        self._ensure_init()
        if not self.live:
            return {'tx_hash': self._mock_tx(f'close-{debate_id}'), 'live': False}

        try:
            func = self.contract.functions.closeDebate(debate_id)
            tx_hash = self._send_transaction(func)
            # DEFECTO CORREGIDO — declaraba `live: True` incluso cuando
            # _send_transaction devolvia None, es decir cuando la
            # transaccion no se confirmo. `live` tiene que reflejar lo que
            # de verdad paso en la cadena.
            if tx_hash:
                return {'tx_hash': tx_hash, 'live': True}
            return {'tx_hash': self._mock_tx(f'close-{debate_id}'), 'live': False}
        except Exception as e:
            print(f'[Blockchain] close_debate error: {e}')
            return {'tx_hash': self._mock_tx(f'close-{debate_id}'), 'live': False}

    def verify_by_code(self, vcode: str) -> dict:
        """
        Verify a vote on-chain using its verification code.
        This is a READ operation — free, no gas needed.
        """
        self._ensure_init()
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
        self._ensure_init()
        if not self.live:
            return -1
        try:
            return self.contract.functions.totalVotesAnchored().call()
        except:
            return -1

    def status(self) -> dict:
        """Return blockchain connection status — never raises."""
        self._ensure_init()
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
