from pathlib import Path
import json

from solcx import install_solc, set_solc_version, compile_standard


# --------------------------------------------------
# PROJECT PATHS
# --------------------------------------------------

BLOCKCHAIN_DIR = Path(__file__).resolve().parent

CONTRACT_FILE = (
    BLOCKCHAIN_DIR
    / "contracts"
    / "CensusRegistry.sol"
)

BUILD_DIR = (
    BLOCKCHAIN_DIR
    / "build"
)


# --------------------------------------------------
# SOLIDITY VERSION
# --------------------------------------------------

SOLIDITY_VERSION = "0.8.20"


# --------------------------------------------------
# READ SMART CONTRACT
# --------------------------------------------------

if not CONTRACT_FILE.exists():
    raise FileNotFoundError(
        f"Smart contract not found: {CONTRACT_FILE}"
    )

source_code = CONTRACT_FILE.read_text(
    encoding="utf-8"
)


# --------------------------------------------------
# INSTALL SOLIDITY COMPILER
# --------------------------------------------------

print("Installing/checking Solidity compiler...")

install_solc(SOLIDITY_VERSION)
set_solc_version(SOLIDITY_VERSION)


# --------------------------------------------------
# COMPILE CONTRACT
# --------------------------------------------------

print("Compiling CensusRegistry.sol...")


compiled_contract = compile_standard(
    {
        "language": "Solidity",

        "sources": {
            "CensusRegistry.sol": {
                "content": source_code
            }
        },

        "settings": {
            "optimizer": {
                "enabled": True,
                "runs": 200
            },

            "outputSelection": {
                "*": {
                    "*": [
                        "abi",
                        "evm.bytecode",
                        "evm.deployedBytecode"
                    ]
                }
            }
        }
    },

    solc_version=SOLIDITY_VERSION
)


# --------------------------------------------------
# GET CONTRACT
# --------------------------------------------------

contract_data = (
    compiled_contract
    ["contracts"]
    ["CensusRegistry.sol"]
    ["CensusRegistry"]
)


abi = contract_data["abi"]

bytecode = contract_data["evm"]["bytecode"]["object"]


# --------------------------------------------------
# CREATE BUILD FOLDER
# --------------------------------------------------

BUILD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# --------------------------------------------------
# SAVE ABI
# --------------------------------------------------

abi_file = BUILD_DIR / "CensusRegistry_abi.json"

with open(
    abi_file,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        abi,
        file,
        indent=4
    )


# --------------------------------------------------
# SAVE BYTECODE
# --------------------------------------------------

bytecode_file = (
    BUILD_DIR
    / "CensusRegistry_bytecode.txt"
)

bytecode_file.write_text(
    bytecode,
    encoding="utf-8"
)


# --------------------------------------------------
# SUCCESS MESSAGE
# --------------------------------------------------

print()
print("=" * 55)
print("SMART CONTRACT COMPILED SUCCESSFULLY")
print("=" * 55)

print(f"Contract : CensusRegistry")
print(f"Solidity : {SOLIDITY_VERSION}")

print()
print("ABI file:")
print(abi_file)

print()
print("Bytecode file:")
print(bytecode_file)

print()
print("Blockchain contract is ready.")
print("=" * 55)