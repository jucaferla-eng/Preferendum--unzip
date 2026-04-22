"""
deploy.py - Deploy PreferendumVote.sol to Polygon
Run once to deploy the contract.

Requirements:
    pip install web3 py-solc-x

Usage:
    python deploy.py --network testnet   # Mumbai testnet (free MATIC)
    python deploy.py --network mainnet   # Polygon mainnet (real MATIC)

En memoria de Jose Ignacio Fernandez (1989-2024)
"""

import os, sys, json, argparse

NETWORKS = {
    'testnet': {
        'name':    'Polygon Mumbai Testnet',
        'rpc':     'https://rpc-mumbai.maticvigil.com',
        'chain_id': 80001,
        'explorer': 'https://mumbai.polygonscan.com/tx/',
        'faucet':  'https://faucet.polygon.technology/',
        'note':    'Free MATIC from faucet. Use for testing.',
    },
    'mainnet': {
        'name':    'Polygon Mainnet',
        'rpc':     'https://polygon-rpc.com',
        'chain_id': 137,
        'explorer': 'https://polygonscan.com/tx/',
        'faucet':  None,
        'note':    'Real MATIC required. ~0.01 MATIC (~$0.01) to deploy.',
    }
}

CONTRACT_SOURCE = open('PreferendumVote.sol').read()

def deploy(network: str):
    net = NETWORKS[network]
    print(f'\n[Deploy] Network: {net["name"]}')
    print(f'[Deploy] RPC: {net["rpc"]}')

    # Get wallet from environment
    private_key     = os.getenv('WALLET_PRIVATE_KEY')
    wallet_address  = os.getenv('WALLET_ADDRESS')

    if not private_key or not wallet_address:
        print('\n[Error] Set environment variables:')
        print('  export WALLET_PRIVATE_KEY=0x...')
        print('  export WALLET_ADDRESS=0x...')
        sys.exit(1)

    try:
        from web3 import Web3
        from solcx import compile_source, install_solc
    except ImportError:
        print('\n[Error] Install dependencies:')
        print('  pip install web3 py-solc-x')
        sys.exit(1)

    # Connect
    w3 = Web3(Web3.HTTPProvider(net['rpc']))
    if not w3.is_connected():
        print(f'[Error] Cannot connect to {net["rpc"]}')
        sys.exit(1)

    print(f'[Deploy] Connected to {net["name"]}')

    # Check balance
    balance = w3.eth.get_balance(wallet_address)
    balance_matic = w3.from_wei(balance, 'ether')
    print(f'[Deploy] Wallet: {wallet_address}')
    print(f'[Deploy] Balance: {balance_matic:.4f} MATIC')

    if balance == 0:
        print(f'\n[Error] Wallet has no MATIC.')
        if net['faucet']:
            print(f'[Help] Get free testnet MATIC: {net["faucet"]}')
        sys.exit(1)

    # Compile
    print('[Deploy] Compiling PreferendumVote.sol...')
    install_solc('0.8.19')
    compiled = compile_source(
        CONTRACT_SOURCE,
        output_values=['abi', 'bin'],
        solc_version='0.8.19'
    )
    contract_id = '<stdin>:PreferendumVote'
    contract_interface = compiled[contract_id]

    print('[Deploy] Compilation successful')

    # Deploy
    Contract = w3.eth.contract(
        abi=contract_interface['abi'],
        bytecode=contract_interface['bin']
    )

    nonce     = w3.eth.get_transaction_count(wallet_address)
    gas_price = int(w3.eth.gas_price * 1.1)

    print(f'[Deploy] Deploying contract...')
    tx = Contract.constructor().build_transaction({
        'from':     wallet_address,
        'nonce':    nonce,
        'gas':      2000000,
        'gasPrice': gas_price,
        'chainId':  net['chain_id']
    })

    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)

    print(f'[Deploy] Transaction sent: {tx_hash.hex()}')
    print(f'[Deploy] Waiting for confirmation...')

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    contract_address = receipt.contractAddress

    print(f'\n[Deploy] SUCCESS!')
    print(f'[Deploy] Contract address: {contract_address}')
    print(f'[Deploy] Transaction: {net["explorer"]}{tx_hash.hex()}')
    print(f'[Deploy] Gas used: {receipt.gasUsed}')

    # Save ABI and address
    deployment_info = {
        'contract_address': contract_address,
        'tx_hash':          tx_hash.hex(),
        'network':          network,
        'chain_id':         net['chain_id'],
        'abi':              contract_interface['abi'],
        'deployed_at':      str(__import__('datetime').datetime.utcnow()),
        'dedication':       'En memoria de Jose Ignacio Fernandez (1989-2024)'
    }

    with open('deployment.json', 'w') as f:
        json.dump(deployment_info, f, indent=2)

    print(f'\n[Deploy] Saved to deployment.json')
    print(f'\n[Next steps]')
    print(f'  1. Set in Render environment variables:')
    print(f'     CONTRACT_ADDRESS   = {contract_address}')
    print(f'     WALLET_ADDRESS     = {wallet_address}')
    print(f'     WALLET_PRIVATE_KEY = [your key — NEVER share]')
    print(f'     POLYGON_RPC_URL    = {net["rpc"]}')
    print(f'  2. Add to requirements.txt: web3==6.11.1')
    print(f'  3. Redeploy on Render')
    print(f'\n[Verify on PolygonScan]')
    print(f'  {net["explorer"]}{tx_hash.hex()}')

    return contract_address


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Deploy PreferendumVote to Polygon')
    parser.add_argument('--network', choices=['testnet','mainnet'],
                        default='testnet', help='Network to deploy to')
    args = parser.parse_args()
    deploy(args.network)
