// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract CensusRegistry {

    struct AuditRecord {
        uint256 recordId;
        bytes32 dataHash;
        string action;
        uint256 timestamp;
        address submittedBy;
    }

    // Each census record can have multiple blockchain audit entries
    mapping(uint256 => AuditRecord[]) private auditHistory;

    // Event generated whenever a census record is logged
    event CensusRecordLogged(
        uint256 indexed recordId,
        bytes32 indexed dataHash,
        string action,
        uint256 timestamp,
        address indexed submittedBy
    );

    // Store a census record's hash and action on blockchain
    function logRecord(
        uint256 recordId,
        bytes32 dataHash,
        string calldata action
    ) external {

        AuditRecord memory entry = AuditRecord({
            recordId: recordId,
            dataHash: dataHash,
            action: action,
            timestamp: block.timestamp,
            submittedBy: msg.sender
        });

        auditHistory[recordId].push(entry);

        emit CensusRecordLogged(
            recordId,
            dataHash,
            action,
            block.timestamp,
            msg.sender
        );
    }

    // Get the latest blockchain entry for a census record
    function getLatestRecord(uint256 recordId)
        external
        view
        returns (
            uint256,
            bytes32,
            string memory,
            uint256,
            address
        )
    {
        require(
            auditHistory[recordId].length > 0,
            "No audit record found"
        );

        AuditRecord memory entry =
            auditHistory[recordId][auditHistory[recordId].length - 1];

        return (
            entry.recordId,
            entry.dataHash,
            entry.action,
            entry.timestamp,
            entry.submittedBy
        );
    }

    // Get number of blockchain entries for a record
    function getHistoryCount(uint256 recordId)
        external
        view
        returns (uint256)
    {
        return auditHistory[recordId].length;
    }

    // Get a particular history entry
    function getHistoryEntry(
        uint256 recordId,
        uint256 index
    )
        external
        view
        returns (
            uint256,
            bytes32,
            string memory,
            uint256,
            address
        )
    {
        require(
            index < auditHistory[recordId].length,
            "Invalid history index"
        );

        AuditRecord memory entry =
            auditHistory[recordId][index];

        return (
            entry.recordId,
            entry.dataHash,
            entry.action,
            entry.timestamp,
            entry.submittedBy
        );
    }
}