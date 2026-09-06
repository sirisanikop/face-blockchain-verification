"""
Blockchain connection plumbing: Web3 instance, signing account, contract handle.

Everything is driven by environment variables (loaded from a local .env file):

    RPC_URL           JSON-RPC endpoint of the target chain
                      (e.g. an Alchemy/Infura Sepolia URL). If unset -> LOCAL mode.
    PRIVATE_KEY       hex private key of the account that pays gas / signs txs.
                      NEVER commit this. In LOCAL mode it defaults to eth-tester key #1.
    CONTRACT_ADDRESS  address of the deployed FaceVerification contract.
    CHAIN_ID          optional sanity check against the chain's reported id.
    BLOCKCHAIN_LOCAL  set to 1 to force the in-process eth-tester chain even if RPC_URL is set.

LOCAL mode uses web3's EthereumTesterProvider - a full in-process EVM. It needs no
node, no faucet and no keys, so the whole Part 3 flow can be demonstrated offline.
"""

import json
import os
import warnings
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3

try:  # optional - only needed for LOCAL mode
    from web3 import EthereumTesterProvider
except ImportError:  # pragma: no cover
    EthereumTesterProvider = None


@contextmanager
def _quiet_deprecations():
    """
    Suppress the harmless DeprecationWarning that `eth-tester` / `py-evm` raise
    (via a legacy `cached_property`) on Python 3.12+. Scoped to the block only, and
    re-applied each time because some deps reset the global warnings filters.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*asyncio\.iscoroutinefunction.*",
            category=DeprecationWarning,
        )
        yield

load_dotenv()

_HERE = Path(__file__).resolve().parent
ABI_PATH = _HERE / "FaceVerification_abi.json"

# eth-tester's default account #0 has this well-known private key. Used only in LOCAL mode.
_DEFAULT_LOCAL_PRIVATE_KEY = "0x" + "0" * 63 + "1"

# In LOCAL mode the chain lives inside this process. Cache the Web3 instance and the
# auto-deployed contract address so that repeated get_web3()/get_contract() calls in the
# same run (e.g. pipeline.py -> record_and_verify) all talk to the SAME chain.
_LOCAL_STATE = {"w3": None, "contract_address": None}


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def is_local() -> bool:
    """LOCAL mode = forced by BLOCKCHAIN_LOCAL, or simply no RPC_URL configured."""
    if _truthy(os.getenv("BLOCKCHAIN_LOCAL", "")):
        return True
    return not os.getenv("RPC_URL")


def get_web3() -> Web3:
    """Build a connected Web3 instance for either the local test chain or a real RPC."""
    if is_local():
        if EthereumTesterProvider is None:
            raise RuntimeError(
                "LOCAL mode needs the test chain: pip install 'eth-tester' 'py-evm'"
            )
        if _LOCAL_STATE["w3"] is None:
            with _quiet_deprecations():
                _LOCAL_STATE["w3"] = Web3(EthereumTesterProvider())
        return _LOCAL_STATE["w3"]

    rpc_url = os.getenv("RPC_URL")
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 60}))

    # Proof-of-authority testnets (e.g. Polygon Amoy) put extra bytes in the block
    # 'extraData' field; this middleware stops web3 from rejecting those blocks.
    try:
        from web3.middleware import ExtraDataToPOAMiddleware

        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except Exception:  # pragma: no cover - middleware name varies by web3 version
        pass

    if not w3.is_connected():
        raise ConnectionError(f"Could not connect to RPC_URL: {rpc_url}")

    expected = os.getenv("CHAIN_ID")
    if expected and int(expected) != w3.eth.chain_id:
        raise RuntimeError(
            f"CHAIN_ID mismatch: .env says {expected}, RPC reports {w3.eth.chain_id}"
        )
    return w3


def get_account(w3: Web3):
    """Return the local signing account (LocalAccount) derived from PRIVATE_KEY."""
    pk = os.getenv("PRIVATE_KEY")
    if not pk and is_local():
        pk = _DEFAULT_LOCAL_PRIVATE_KEY
    if not pk:
        raise RuntimeError("PRIVATE_KEY is not set (required for non-local chains)")
    if not pk.startswith("0x"):
        pk = "0x" + pk
    return w3.eth.account.from_key(pk)


def load_abi():
    if not ABI_PATH.exists():
        raise FileNotFoundError(
            f"ABI not found at {ABI_PATH}. Run:  python -m blockchain.deploy"
        )
    return json.loads(ABI_PATH.read_text())


def get_contract(w3: Web3, address: str = None):
    """
    Return a contract handle bound to the deployed FaceVerification address.

    On a real chain the address must come from the CONTRACT_ADDRESS env var.
    In LOCAL mode, if no address is known yet, the contract is compiled and deployed
    once and cached for the rest of the process - so `python pipeline.py` works with
    zero blockchain configuration.
    """
    address = address or os.getenv("CONTRACT_ADDRESS")

    if not address and is_local():
        if _LOCAL_STATE["contract_address"] is None:
            from .deploy import deploy  # lazy import avoids a circular import

            addr, _ = deploy(w3, get_account(w3), write_abi=True)
            _LOCAL_STATE["contract_address"] = addr
            print(f"[chain] LOCAL mode: auto-deployed FaceVerification at {addr}")
        address = _LOCAL_STATE["contract_address"]

    if not address:
        raise RuntimeError(
            "CONTRACT_ADDRESS is not set - deploy first:  python -m blockchain.deploy"
        )
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=load_abi())


def send_tx(w3: Web3, account, bound_call):
    """
    Sign and broadcast a transaction, then wait for its receipt.

    `bound_call` is either `Contract.constructor()` or `contract.functions.foo(args)` -
    anything exposing `.build_transaction(...)`.

    We always send a legacy (type-0) transaction with an explicit gasPrice: every
    chain we target (eth-tester, Sepolia, Amoy) accepts that, so there is exactly
    one code path to explain in the demo.
    """
    with _quiet_deprecations():
        tx_params = {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "chainId": w3.eth.chain_id,
        }
        try:
            tx_params["gasPrice"] = w3.eth.gas_price
        except Exception:  # pragma: no cover
            pass

        tx = bound_call.build_transaction(tx_params)
        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction  # web3 v6/v7
        tx_hash = w3.eth.send_raw_transaction(raw)
        return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)


def call_fn(bound_call):
    """Read-only contract call, with the same deprecation-warning suppression as send_tx."""
    with _quiet_deprecations():
        return bound_call.call()
