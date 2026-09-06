// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * FaceVerification
 * ----------------
 * Minimal, tamper-evident registry for Part 3 of the pipeline.
 *
 * We do NOT store the discovered image on-chain. We store only:
 *   - fingerprint: the 32-byte SHA-256 digest of (image bytes + URL + timestamp)
 *   - url:         the discovered post URL (kept for human-readable auditing)
 *   - timestamp:   the unix-seconds timestamp that went INTO the fingerprint
 *   - uploader:    msg.sender (who recorded it)
 *
 * Re-verification later = recompute the SHA-256 fingerprint from the discovered
 * data and check it equals `records[id].fingerprint`.
 */
contract FaceVerification {
    struct Record {
        bytes32 fingerprint; // SHA-256(image_bytes || 0x1F || normalized_url || 0x1F || canonical_timestamp)
        string  url;          // discovered post URL (as passed in by the pipeline)
        uint256 timestamp;    // unix seconds that was hashed into `fingerprint`
        address uploader;     // account that stored this record
    }

    Record[] private records;

    event RecordStored(
        uint256 indexed id,
        bytes32 fingerprint,
        address indexed uploader,
        uint256 timestamp
    );

    /// @notice Store a new verification record. Returns its numeric id.
    function storeRecord(bytes32 fingerprint, string calldata url, uint256 timestamp)
        external
        returns (uint256 id)
    {
        records.push(Record(fingerprint, url, timestamp, msg.sender));
        id = records.length - 1;
        emit RecordStored(id, fingerprint, msg.sender, timestamp);
    }

    /// @notice Read a stored record back for re-verification.
    function getRecord(uint256 id)
        external
        view
        returns (bytes32 fingerprint, string memory url, uint256 timestamp, address uploader)
    {
        require(id < records.length, "FaceVerification: unknown record id");
        Record storage r = records[id];
        return (r.fingerprint, r.url, r.timestamp, r.uploader);
    }

    /// @notice Total number of records stored so far.
    function totalRecords() external view returns (uint256) {
        return records.length;
    }
}
