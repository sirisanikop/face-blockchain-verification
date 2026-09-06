"""
Compile blockchain/contract.sol and deploy FaceVerification.

Usage:
    python -m blockchain.deploy

LOCAL mode (no RPC_URL in .env): deploys to the in-process eth-tester chain and
prints the address - handy for a quick sanity check.

Real testnet (RPC_URL + PRIVATE_KEY in .env): deploys to Sepolia / Amoy / etc.
Copy the printed CONTRACT_ADDRESS line into your .env afterwards.
"""

import json

import solcx

from .chain import ABI_PATH, get_account, get_contract, get_web3, is_local, send_tx

_SOLC_VERSION = "0.8.26"
_SOL_FILE = ABI_PATH.parent / "contract.sol"
_CONTRACT_NAME = "FaceVerification"


def compile_contract():
    """Compile contract.sol, returning (abi, bytecode_hex)."""
    try:
        solcx.set_solc_version(_SOLC_VERSION)
    except Exception:
        # solc not installed yet - fetch it once (downloads a small binary).
        solcx.install_solc(_SOLC_VERSION, show_progress=False)
        solcx.set_solc_version(_SOLC_VERSION)

    compiled = solcx.compile_files(
        [str(_SOL_FILE)],
        output_values=["abi", "bin"],
        solc_version=_SOLC_VERSION,
    )
    key = next(k for k in compiled if k.endswith(f":{_CONTRACT_NAME}"))
    return compiled[key]["abi"], compiled[key]["bin"]


def deploy(w3=None, account=None, write_abi=True):
    """
    Deploy FaceVerification. Returns (contract_address, abi).

    If write_abi is True the compiled ABI is saved to blockchain/FaceVerification_abi.json
    (that file is what the Python client loads to talk to the contract).
    """
    w3 = w3 or get_web3()
    account = account or get_account(w3)

    abi, bytecode = compile_contract()
    if write_abi:
        ABI_PATH.write_text(json.dumps(abi, indent=2))

    factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    receipt = send_tx(w3, account, factory.constructor())
    if receipt.status != 1:
        raise RuntimeError("deployment transaction reverted")
    return receipt.contractAddress, abi


def main():
    w3 = get_web3()
    account = get_account(w3)
    print(f"Mode          : {'LOCAL (eth-tester)' if is_local() else 'REMOTE RPC'}")
    print(f"Chain id      : {w3.eth.chain_id}")
    print(f"Deployer      : {account.address}")
    print(f"Deployer bal. : {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} ETH")
    print("Compiling and deploying contract.sol ...")

    address, _ = deploy(w3, account)

    print("\nFaceVerification deployed successfully.")
    print(f"  address : {address}")
    print(f"  abi     : {ABI_PATH}")
    print("\n--- add this line to your .env ---")
    print(f"CONTRACT_ADDRESS={address}")


if __name__ == "__main__":
    main()
