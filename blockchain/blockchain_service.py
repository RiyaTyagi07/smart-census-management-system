import json
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime

from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider



# ============================================================
# PATH CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

BUILD_DIR = BASE_DIR / "build"

ABI_FILE = BUILD_DIR / "CensusRegistry_abi.json"
BYTECODE_FILE = BUILD_DIR / "CensusRegistry_bytecode.txt"

DATABASE_FILE = PROJECT_DIR / "database" / "census.db"

# Persistent blockchain audit file
PERSISTENCE_FILE = BASE_DIR / "persistent_blockchain_ledger.json"

# ============================================================
# LOAD CONTRACT FILES
# ============================================================

if not ABI_FILE.exists():
    raise FileNotFoundError(
        f"ABI file not found: {ABI_FILE}\n"
        "Please compile the smart contract first."
    )

if not BYTECODE_FILE.exists():
    raise FileNotFoundError(
        f"Bytecode file not found: {BYTECODE_FILE}\n"
        "Please compile the smart contract first."
    )


with open(ABI_FILE, "r", encoding="utf-8") as file:
    CONTRACT_ABI = json.load(file)


with open(BYTECODE_FILE, "r", encoding="utf-8") as file:
    CONTRACT_BYTECODE = file.read().strip()


# ============================================================
# PERSISTENT LEDGER
# ============================================================

def load_persistent_ledger():
    """
    Load saved blockchain audit entries from JSON.

    EthereumTester itself is temporary.
    The JSON ledger allows us to rebuild the audit history
    whenever Flask restarts.
    """

    if not PERSISTENCE_FILE.exists():
        return []

    try:
        with open(PERSISTENCE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, list):
            return data

        return []

    except Exception as error:
        print("Persistent Ledger Load Error:", error)
        return []


def save_persistent_ledger(ledger):
    """
    Save blockchain audit entries safely.
    """

    temporary_file = PERSISTENCE_FILE.with_suffix(".tmp")

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(
            ledger,
            file,
            indent=4,
            ensure_ascii=False
        )

    temporary_file.replace(PERSISTENCE_FILE)


PERSISTENT_LEDGER = load_persistent_ledger()


# ============================================================
# SQLITE HELPERS
# ============================================================

def get_existing_sqlite_records():
    """
    Reads current census records from SQLite.

    This is used only to synchronize existing records
    that were created before blockchain persistence was added.
    """

    records = []

    if not DATABASE_FILE.exists():
        print("SQLite database not found:", DATABASE_FILE)
        return records

    try:
        connection = sqlite3.connect(DATABASE_FILE)
        connection.row_factory = sqlite3.Row

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                full_name,
                age,
                gender,
                date_of_birth,
                mobile_number,
                address,
                city,
                occupation
            FROM census_records
            ORDER BY id
            """
        )

        rows = cursor.fetchall()

        for row in rows:

            records.append({
                "id": int(row["id"]),
                "full_name": row["full_name"],
                "age": int(row["age"]),
                "gender": row["gender"],
                "date_of_birth": row["date_of_birth"],
                "mobile_number": row["mobile_number"],
                "address": row["address"],
                "city": row["city"],
                "occupation": row["occupation"]
            })

        connection.close()

    except Exception as error:
        print("SQLite Record Read Error:", error)

    return records


# ============================================================
# CONNECT TO LOCAL TEST BLOCKCHAIN
# ============================================================

web3 = Web3(EthereumTesterProvider())


if not web3.is_connected():
    raise ConnectionError(
        "Blockchain connection failed."
    )


ACCOUNT = web3.eth.accounts[0]


# ============================================================
# DEPLOY SMART CONTRACT
# ============================================================

Contract = web3.eth.contract(
    abi=CONTRACT_ABI,
    bytecode=CONTRACT_BYTECODE
)


deployment_transaction = Contract.constructor().transact(
    {
        "from": ACCOUNT
    }
)


deployment_receipt = web3.eth.wait_for_transaction_receipt(
    deployment_transaction
)


CONTRACT_ADDRESS = deployment_receipt.contractAddress


contract = web3.eth.contract(
    address=CONTRACT_ADDRESS,
    abi=CONTRACT_ABI
)


# ============================================================
# HASH CREATION
# ============================================================

def create_data_hash(record_data):
    """
    Creates SHA-256 hash from census record data.

    Actual citizen information is NOT stored on blockchain.
    Only the SHA-256 hash is stored.
    """

    normalized_data = json.dumps(
        record_data,
        sort_keys=True,
        separators=(",", ":")
    )

    data_hash = hashlib.sha256(
        normalized_data.encode("utf-8")
    ).hexdigest()

    return data_hash


# ============================================================
# CONVERT HASH TO BYTES32
# ============================================================

def hash_to_bytes32(hex_hash):
    """
    Convert hexadecimal SHA-256 hash to bytes32.
    """

    return bytes.fromhex(hex_hash)


# ============================================================
# CHECK WHETHER ENTRY EXISTS
# ============================================================

def has_persistent_entry(record_id, action=None):
    """
    Checks whether a particular audit entry already exists
    in the persistent ledger.
    """

    record_id = int(record_id)

    for entry in PERSISTENT_LEDGER:

        if int(entry.get("record_id", -1)) != record_id:
            continue

        if action is None:
            return True

        if entry.get("action") == action:
            return True

    return False


# ============================================================
# REBUILD BLOCKCHAIN FROM JSON LEDGER
# ============================================================

def rebuild_blockchain_from_ledger():
    """
    Replays the persistent audit ledger onto the newly
    created EthereumTester blockchain.
    """

    if not PERSISTENT_LEDGER:
        print()
        print("========================================")
        print(" No Persistent Blockchain Entries")
        print("========================================")
        print()
        return

    print()
    print("========================================")
    print(" REBUILDING PERSISTENT BLOCKCHAIN STATE")
    print("========================================")

    rebuilt_count = 0

    for entry in PERSISTENT_LEDGER:

        try:

            record_id = int(entry["record_id"])
            data_hash = entry["data_hash"]
            action = entry["action"]

            bytes32_hash = hash_to_bytes32(
                data_hash
            )

            transaction = contract.functions.logRecord(
                record_id,
                bytes32_hash,
                action
            ).transact(
                {
                    "from": ACCOUNT
                }
            )

            receipt = web3.eth.wait_for_transaction_receipt(
                transaction
            )

            rebuilt_count += 1

            print(
                f"Rebuilt: Record {record_id} | "
                f"{action} | "
                f"Block {receipt.blockNumber}"
            )

        except Exception as error:

            print(
                "Blockchain rebuild error:",
                error
            )

    print(
        f"Blockchain rebuild complete. "
        f"{rebuilt_count}/{len(PERSISTENT_LEDGER)} "
        f"entries restored."
    )

    print("========================================")
    print()


# ============================================================
# REBUILD EXISTING BLOCKCHAIN STATE
# ============================================================

rebuild_blockchain_from_ledger()


# ============================================================
# LOG RECORD
# ============================================================

def log_record(record_id, record_data, action):
    """
    Store census audit information on blockchain
    and in the persistent JSON ledger.

    Actions:
        CREATE
        UPDATE
        DELETE
    """

    record_id = int(record_id)

    data_hash = create_data_hash(
        record_data
    )

    bytes32_hash = hash_to_bytes32(
        data_hash
    )

    transaction = contract.functions.logRecord(
        record_id,
        bytes32_hash,
        action
    ).transact(
        {
            "from": ACCOUNT
        }
    )

    receipt = web3.eth.wait_for_transaction_receipt(
        transaction
    )

    transaction_hash = receipt.transactionHash.hex()
    block_number = receipt.blockNumber

    # Save persistent audit information
    ledger_entry = {
        "record_id": record_id,
        "data_hash": data_hash,
        "action": action,
        "saved_at": datetime.now().isoformat()
    }

    PERSISTENT_LEDGER.append(
        ledger_entry
    )

    save_persistent_ledger(
        PERSISTENT_LEDGER
    )

    print(
        f"Blockchain Logged: "
        f"Record {record_id} | {action}"
    )

    return {
        "success": True,
        "record_id": record_id,
        "data_hash": data_hash,
        "action": action,
        "transaction_hash": transaction_hash,
        "block_number": block_number,
        "contract_address": CONTRACT_ADDRESS
    }


# ============================================================
# SYNCHRONIZE EXISTING SQLITE RECORDS
# ============================================================

def synchronize_existing_records():
    """
    Synchronizes existing SQLite census records that are
    missing from the persistent blockchain ledger.

    This fixes records that were created before the
    persistent blockchain system was introduced.
    """

    records = get_existing_sqlite_records()

    if not records:
        print("No existing SQLite census records to synchronize.")
        return

    print()
    print("========================================")
    print(" SYNCHRONIZING EXISTING CENSUS RECORDS")
    print("========================================")

    synced_count = 0
    skipped_count = 0

    for record in records:

        record_id = record["id"]

        # Remove database-only ID from hash data.
        record_data = {
            "full_name": record["full_name"],
            "age": record["age"],
            "gender": record["gender"],
            "date_of_birth": record["date_of_birth"],
            "mobile_number": record["mobile_number"],
            "address": record["address"],
            "city": record["city"],
            "occupation": record["occupation"]
        }

        current_hash = create_data_hash(
            record_data
        )

        # If this exact CREATE hash already exists,
        # do not create a duplicate.
        already_synced = False

        for entry in PERSISTENT_LEDGER:

            if int(entry.get("record_id", -1)) != record_id:
                continue

            if entry.get("data_hash") == current_hash:
                already_synced = True
                break

        if already_synced:

            print(
                f"Already synced: Record {record_id}"
            )

            skipped_count += 1
            continue

        # If record has a DELETE entry but is currently
        # present in SQLite, do not automatically add a
        # duplicate CREATE unless its current data differs.
        print(
            f"Syncing existing record: {record_id}"
        )

        try:

            result = log_record(
                record_id,
                record_data,
                "CREATE"
            )

            if result["success"]:
                synced_count += 1

        except Exception as error:

            print(
                f"Sync failed for Record {record_id}:",
                error
            )

    print()
    print(
        f"Existing record synchronization complete."
    )

    print(
        f"Synced : {synced_count}"
    )

    print(
        f"Skipped: {skipped_count}"
    )

    print("========================================")
    print()


# ============================================================
# SYNCHRONIZE EXISTING DATABASE RECORDS
# ============================================================

synchronize_existing_records()


# ============================================================
# GET LATEST BLOCKCHAIN RECORD
# ============================================================

def get_latest_record(record_id):
    """
    Returns the latest blockchain audit entry
    for a census record.
    """

    try:

        result = contract.functions.getLatestRecord(
            int(record_id)
        ).call()

        return {
            "record_id": result[0],
            "data_hash": result[1].hex(),
            "action": result[2],
            "timestamp": result[3],
            "submitted_by": result[4]
        }

    except Exception as error:

        return {
            "error": str(error)
        }


# ============================================================
# GET HISTORY COUNT
# ============================================================

def get_history_count(record_id):
    """
    Returns number of blockchain audit entries
    for a record.
    """

    try:

        count = contract.functions.getHistoryCount(
            int(record_id)
        ).call()

        return count

    except Exception as error:

        print(
            "History Count Error:",
            error
        )

        return 0


# ============================================================
# GET COMPLETE BLOCKCHAIN HISTORY
# ============================================================

def get_record_history(record_id):
    """
    Returns complete blockchain audit history.
    """

    history = []

    try:

        record_id = int(record_id)

        count = get_history_count(
            record_id
        )

        if count == 0:
            return history

        # Get blockchain events
        event_logs = (
            contract.events.CensusRecordLogged.get_logs(
                from_block=0,
                to_block="latest"
            )
        )

        record_events = []

        for event in event_logs:

            args = event["args"]

            if int(args["recordId"]) == record_id:
                record_events.append(event)

        # Read history entries
        for index in range(count):

            result = contract.functions.getHistoryEntry(
                record_id,
                index
            ).call()

            entry_record_id = result[0]
            entry_hash = result[1].hex()
            entry_action = result[2]
            entry_timestamp = result[3]
            entry_submitted_by = result[4]

            transaction_hash = "N/A"
            block_number = "N/A"

            if index < len(record_events):

                event = record_events[index]

                transaction_hash = (
                    event["transactionHash"].hex()
                )

                block_number = event["blockNumber"]

            history.append(
                {
                    "record_id": entry_record_id,
                    "data_hash": entry_hash,
                    "action": entry_action,
                    "timestamp": entry_timestamp,
                    "submitted_by": entry_submitted_by,
                    "transaction_hash": transaction_hash,
                    "block_number": block_number
                }
            )

        return history

    except Exception as error:

        print(
            "Blockchain History Error:",
            error
        )

        return [
            {
                "error": str(error)
            }
        ]


# ============================================================
# VERIFY RECORD INTEGRITY
# ============================================================

def verify_record(record_id, record_data):
    """
    Compare current SQLite record hash with
    the latest blockchain hash.
    """

    blockchain_record = get_latest_record(
        record_id
    )

    if "error" in blockchain_record:

        return {
            "verified": False,
            "message": blockchain_record["error"]
        }

    current_hash = create_data_hash(
        record_data
    )

    blockchain_hash = blockchain_record[
        "data_hash"
    ]

    blockchain_hash = blockchain_hash.replace(
        "0x",
        ""
    )

    if current_hash.lower() == blockchain_hash.lower():

        return {
            "verified": True,
            "message": "Record integrity is intact.",
            "current_hash": current_hash,
            "blockchain_hash": blockchain_hash,
            "action": blockchain_record["action"],
            "timestamp": blockchain_record["timestamp"]
        }

    return {
        "verified": False,
        "message": "Record integrity verification failed.",
        "current_hash": current_hash,
        "blockchain_hash": blockchain_hash,
        "action": blockchain_record["action"],
        "timestamp": blockchain_record["timestamp"]
    }


# ============================================================
# BLOCKCHAIN INFORMATION
# ============================================================

def get_blockchain_info():
    """
    Returns basic blockchain information.
    """

    return {
        "connected": web3.is_connected(),
        "account": ACCOUNT,
        "contract_address": CONTRACT_ADDRESS,
        "chain_id": web3.eth.chain_id,
        "latest_block": web3.eth.block_number,
        "persistent_entries": len(PERSISTENT_LEDGER)
    }