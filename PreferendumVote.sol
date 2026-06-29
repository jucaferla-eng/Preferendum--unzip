// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title PreferendumVote
 * @author CAIP Task Force
 * @notice Anchors every vote hash on Polygon blockchain.
 *         No vote content is stored — only the SHA-256 hash.
 *         Identity is never stored — bridge destruction is enforced off-chain.
 *
 * En memoria de Jose Ignacio Fernandez (1989-2024)
 * Co-founder of Preferendum. His vision lives in every line of code.
 *
 * WHAT THIS CONTRACT DOES:
 * ========================
 * 1. Stores the SHA-256 hash of every encrypted vote — immutably.
 * 2. Stores the verification code (XXXX-XXXX-XXXX) linked to each hash.
 * 3. Allows anyone to verify a vote by its code — public audit.
 * 4. Records debate opening and closing — tamper-proof timestamps.
 * 5. Emits events for every action — full transparency.
 *
 * WHAT THIS CONTRACT DOES NOT DO:
 * ================================
 * - Does NOT store vote content (which option was chosen).
 * - Does NOT store voter identity (name, ID, email, IMEI).
 * - Does NOT store demographic data (gender, age, location).
 * - Cannot be modified after deployment — immutable by design.
 *
 * DEPLOYMENT:
 * ===========
 * Network: Polygon Mainnet (or Mumbai Testnet for testing)
 * Gas: ~50,000 gas per vote anchor (~$0.001 USD at normal gas prices)
 */

contract PreferendumVote {

    // ── OWNER ─────────────────────────────────────────────────
    address public owner;

    modifier onlyOwner() {
        require(msg.sender == owner, "Only Preferendum can call this");
        _;
    }

    // ── STRUCTS ───────────────────────────────────────────────

    struct VoteAnchor {
        bytes32 voteHash;      // SHA-256 hash of the encrypted vote
        string  vcode;         // Verification code XXXX-XXXX-XXXX
        uint256 debateId;      // Which debate this vote belongs to
        uint256 timestamp;     // When the vote was anchored
        bool    exists;        // Whether this anchor exists
    }

    struct Debate {
        uint256 id;
        string  title;
        string  institution;
        uint256 openedAt;
        uint256 closedAt;
        bool    isOpen;
        uint256 totalVotes;
        bool    exists;
    }

    // ── STORAGE ───────────────────────────────────────────────

    // vcode => VoteAnchor
    mapping(string => VoteAnchor) public voteAnchors;

    // voteHash => vcode (reverse lookup)
    mapping(bytes32 => string) public hashToVcode;

    // debateId => Debate
    mapping(uint256 => Debate) public debates;

    // debateId => list of vcodes (for full audit)
    mapping(uint256 => string[]) private debateVcodes;

    // Total votes anchored across all debates
    uint256 public totalVotesAnchored;

    // ── EVENTS ────────────────────────────────────────────────

    event VoteAnchored(
        uint256 indexed debateId,
        bytes32 indexed voteHash,
        string  vcode,
        uint256 timestamp
    );

    event DebateOpened(
        uint256 indexed debateId,
        string  title,
        string  institution,
        uint256 timestamp
    );

    event DebateClosed(
        uint256 indexed debateId,
        uint256 totalVotes,
        uint256 timestamp
    );

    event OwnershipTransferred(
        address indexed previousOwner,
        address indexed newOwner
    );

    // ── CONSTRUCTOR ───────────────────────────────────────────

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // ── DEBATE MANAGEMENT ─────────────────────────────────────

    /**
     * @notice Register a new debate on-chain.
     * @param debateId  Unique ID from Preferendum database
     * @param title     Title of the debate question
     * @param institution Name of the institution running the debate
     */
    function openDebate(
        uint256 debateId,
        string calldata title,
        string calldata institution
    ) external onlyOwner {
        require(!debates[debateId].exists, "Debate already exists");

        debates[debateId] = Debate({
            id:          debateId,
            title:       title,
            institution: institution,
            openedAt:    block.timestamp,
            closedAt:    0,
            isOpen:      true,
            totalVotes:  0,
            exists:      true
        });

        emit DebateOpened(debateId, title, institution, block.timestamp);
    }

    /**
     * @notice Close a debate — no more votes can be anchored after this.
     * @param debateId The debate to close
     */
    function closeDebate(uint256 debateId) external onlyOwner {
        require(debates[debateId].exists, "Debate does not exist");
        require(debates[debateId].isOpen, "Debate already closed");

        debates[debateId].isOpen    = false;
        debates[debateId].closedAt  = block.timestamp;

        emit DebateClosed(
            debateId,
            debates[debateId].totalVotes,
            block.timestamp
        );
    }

    // ── VOTE ANCHORING ────────────────────────────────────────

    /**
     * @notice Anchor a vote hash on-chain. Called by Preferendum backend
     *         immediately after a vote is cast. No vote content stored.
     *
     * @param debateId  The debate this vote belongs to
     * @param voteHash  SHA-256 hash of the encrypted vote (bytes32)
     * @param vcode     Verification code given to the voter (XXXX-XXXX-XXXX)
     */
    function anchorVote(
        uint256 debateId,
        bytes32 voteHash,
        string calldata vcode
    ) external onlyOwner {
        require(debates[debateId].exists, "Debate does not exist");
        require(debates[debateId].isOpen, "Debate is closed");
        require(!voteAnchors[vcode].exists, "Vote already anchored");
        require(bytes(hashToVcode[voteHash]).length == 0, "Hash already anchored");

        // Store the anchor
        voteAnchors[vcode] = VoteAnchor({
            voteHash:  voteHash,
            vcode:     vcode,
            debateId:  debateId,
            timestamp: block.timestamp,
            exists:    true
        });

        // Reverse lookup
        hashToVcode[voteHash] = vcode;

        // Update debate counter
        debates[debateId].totalVotes++;
        debateVcodes[debateId].push(vcode);
        totalVotesAnchored++;

        emit VoteAnchored(debateId, voteHash, vcode, block.timestamp);
    }

    /**
     * @notice Batch anchor multiple votes in one transaction.
     *         More gas efficient for high-volume debates.
     * @param debateId   The debate ID
     * @param voteHashes Array of SHA-256 vote hashes
     * @param vcodes     Array of verification codes
     */
    function anchorVoteBatch(
        uint256 debateId,
        bytes32[] calldata voteHashes,
        string[]  calldata vcodes
    ) external onlyOwner {
        require(debates[debateId].exists, "Debate does not exist");
        require(debates[debateId].isOpen, "Debate is closed");
        require(voteHashes.length == vcodes.length, "Arrays must match");
        require(voteHashes.length <= 100, "Max 100 votes per batch");

        for (uint256 i = 0; i < voteHashes.length; i++) {
            if (voteAnchors[vcodes[i]].exists) continue;
            if (bytes(hashToVcode[voteHashes[i]]).length != 0) continue;

            voteAnchors[vcodes[i]] = VoteAnchor({
                voteHash:  voteHashes[i],
                vcode:     vcodes[i],
                debateId:  debateId,
                timestamp: block.timestamp,
                exists:    true
            });

            hashToVcode[voteHashes[i]] = vcodes[i];
            debates[debateId].totalVotes++;
            debateVcodes[debateId].push(vcodes[i]);
            totalVotesAnchored++;

            emit VoteAnchored(debateId, voteHashes[i], vcodes[i], block.timestamp);
        }
    }

    // ── VERIFICATION — PUBLIC ─────────────────────────────────

    /**
     * @notice Verify a vote using its verification code.
     *         Anyone can call this — full public transparency.
     * @param vcode The XXXX-XXXX-XXXX code the voter received
     * @return exists    Whether this vote exists on-chain
     * @return voteHash  The hash anchored for this vote
     * @return debateId  Which debate this vote belongs to
     * @return timestamp When this vote was anchored
     */
    function verifyByCode(string calldata vcode)
        external view
        returns (
            bool    exists,
            bytes32 voteHash,
            uint256 debateId,
            uint256 timestamp
        )
    {
        VoteAnchor memory anchor = voteAnchors[vcode];
        return (
            anchor.exists,
            anchor.voteHash,
            anchor.debateId,
            anchor.timestamp
        );
    }

    /**
     * @notice Verify a vote using its hash.
     * @param voteHash The SHA-256 hash of the encrypted vote
     * @return exists  Whether this hash is anchored
     * @return vcode   The verification code for this vote
     */
    function verifyByHash(bytes32 voteHash)
        external view
        returns (bool exists, string memory vcode)
    {
        string memory code = hashToVcode[voteHash];
        bool found = bytes(code).length > 0;
        return (found, code);
    }

    /**
     * @notice Get full debate information.
     * @param debateId The debate to query
     */
    function getDebate(uint256 debateId)
        external view
        returns (
            string memory title,
            string memory institution,
            uint256 openedAt,
            uint256 closedAt,
            bool    isOpen,
            uint256 totalVotes
        )
    {
        require(debates[debateId].exists, "Debate does not exist");
        Debate memory d = debates[debateId];
        return (d.title, d.institution, d.openedAt, d.closedAt, d.isOpen, d.totalVotes);
    }

    /**
     * @notice Get all verification codes for a debate (for full audit).
     *         Only available after debate closes.
     * @param debateId The debate to audit
     */
    function getDebateVcodes(uint256 debateId)
        external view
        returns (string[] memory)
    {
        require(debates[debateId].exists, "Debate does not exist");
        require(!debates[debateId].isOpen, "Debate still open - audit available after closing");
        return debateVcodes[debateId];
    }

    // ── OWNERSHIP ─────────────────────────────────────────────

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Invalid address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }
}
