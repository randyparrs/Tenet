// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Ownable2Step, Ownable} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";

/// @title RefundEscrow v3 (Phase 1)
/// @notice Holds a buyer's stablecoin payment for one order until a refund verdict decided on
/// GenLayer is relayed here, or until the order's holding period ends without a claim.
/// Design notes:
/// - Per-order accounting: an order's amount is only ever split into a refund to its buyer and a
///   release to its merchant, and the two always add up to it. Totals are whole cents.
/// - The claim is the JSON the GenLayer judge reads. openClaim checks on chain that it names this
///   order (buyer, merchant, order reference, total, payment time, terms hash) and a claim time
///   within CLAIM_SKEW of the block; the holding period is enforced with block.timestamp.
/// - Every later input is registered here as the canonical JSON the judge reads ("submission"),
///   and its role is checked on chain from the JSON's tail: ...,"kind":"<k>","party":"<p>"}.
///   Deadlines are applied at registration and expiries become registered markers, so the judge
///   decides on exactly what was registered, in order. Each registration extends a hash chain
///   (chain = sha256(chain || sha256(submission))) and a verdict is accepted only for the chain the
///   judge saw: a submission that was never registered here cannot reach a settlement.
/// - The relayer proposes verdicts; the guardian, a distinct key, can veto one during
///   verdictDelay. A veto only discards the proposal. INVALID_CLAIM clears the claim with no
///   penalty. Without a final verdict 60 days after the claim, anyone releases to the merchant.
/// - Pull payments; ERC-20 interface only (on Arc, USDC is also the gas token; msg.value unused).
contract RefundEscrow is Ownable2Step, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    enum State { None, Open, Settled }
    enum Outcome { None, Refund, Deny, Invalid }

    struct Order {
        address buyer;
        address merchant;
        address token;
        uint128 amount;
        uint64 paidAt;
        uint64 expiresAt;
        uint64 claimedAt; // 0 = no claim
        uint64 proofRequestedAt; // 0 = no proof requested
        uint64 proofSubmittedAt; // 0 = not submitted
        uint64 closingOpenedAt; // 0 = no closing round
        uint16 flags; // once-only submissions and markers, see F_*
        State state;
        bytes32 termsHash; // SHA-256 of the refund terms the buyer accepted
        bytes32 claimHash; // SHA-256 of the claim JSON
        bytes32 chain; // hash chain over the claim and every registered submission
    }

    struct Verdict {
        Outcome outcome;
        uint128 refundCents;
        uint64 executeAfter;
        bytes32 verdictRef; // GenLayer transaction or record the verdict comes from
    }

    uint256 public constant CENT = 1e4; // 6-decimal stablecoins
    uint256 public constant MIN_VERDICT_DELAY = 10 minutes;
    uint256 public constant MAX_VERDICT_DELAY = 7 days;
    uint256 public constant ROLE_CHANGE_DELAY = 48 hours;
    uint256 public constant MIN_HOLD = 7 days;
    uint256 public constant MAX_HOLD = 180 days;
    uint256 public constant PROOF_WINDOW = 7 days;
    uint256 public constant RESPONSE_WINDOW = 72 hours;
    uint256 public constant CLOSING_WINDOW = 72 hours;
    uint256 public constant STALL_PERIOD = 60 days;
    uint256 public constant CLAIM_SKEW = 15 minutes;
    uint256 public constant MAX_CLAIM = 8192;
    uint256 public constant MAX_SUBMISSION = 49152;

    uint16 internal constant F_RESPONSE = 1;
    uint16 internal constant F_NO_RESPONSE = 2;
    uint16 internal constant F_CLOSING_RESPONSE = 4;
    uint16 internal constant F_CLOSING_BUYER = 8;
    uint16 internal constant F_CLOSING_TIMEOUT = 16;

    // Markers the escrow registers itself, canonical JSON as the judge reads them.
    bytes internal constant M_NO_RESPONSE = '{"content":null,"kind":"no_response","party":"escrow"}';
    bytes internal constant M_CLOSING_OPEN = '{"content":null,"kind":"closing_open","party":"escrow"}';
    bytes internal constant M_CLOSING_TIMEOUT = '{"content":null,"kind":"closing_timeout","party":"escrow"}';

    address public relayer;
    address public guardian;
    address public pendingRelayer;
    address public pendingGuardian;
    uint256 public relayerChangeAfter;
    uint256 public guardianChangeAfter;
    uint256 public immutable verdictDelay;

    mapping(address token => uint256 cap) public capPerOrder; // 0 = token not accepted
    mapping(address merchant => uint64 holdSeconds) public merchantHold; // 0 = not registered
    mapping(address merchant => bytes32 termsHash) public merchantTermsHash;
    mapping(bytes32 orderRef => Order) internal orders; // read with getOrder
    mapping(bytes32 orderRef => Verdict) public pendingVerdict;
    mapping(address account => mapping(address token => uint256)) public claimable;

    event OrderPaid(bytes32 indexed orderRef, address indexed buyer, address indexed merchant,
                    address token, uint256 amount, uint256 expiresAt, bytes32 termsHash);
    event MerchantTermsSet(address indexed merchant, uint256 holdSeconds, bytes32 termsHash);
    event ClaimOpened(bytes32 indexed orderRef, bytes32 claimHash, bytes32 chain, bytes claim);
    event Submitted(bytes32 indexed orderRef, address indexed by, bytes32 submissionHash, bytes32 chain,
                    bytes submission);
    event ClaimCleared(bytes32 indexed orderRef, bytes32 claimHash);
    event ProofRequested(bytes32 indexed orderRef, uint256 deadline);
    event VerdictProposed(bytes32 indexed orderRef, Outcome outcome, uint256 refundCents, bytes32 chain,
                          bytes32 verdictRef, uint256 executeAfter);
    event VerdictVetoed(bytes32 indexed orderRef, bytes32 verdictRef);
    event OrderSettled(bytes32 indexed orderRef, uint256 refund, uint256 released, bytes32 verdictRef);
    event Withdrawn(address indexed account, address indexed token, uint256 amount);
    event RelayerChangeProposed(address relayer, uint256 effectiveAfter);
    event RelayerChanged(address relayer);
    event GuardianChangeProposed(address guardian, uint256 effectiveAfter);
    event GuardianChanged(address guardian);
    event CapSet(address indexed token, uint256 cap);

    error NotRelayer();
    error NotGuardian();
    error NotBuyer();
    error NotParty();
    error TokenNotAccepted();
    error MerchantNotRegistered();
    error BadAmount();
    error BadHold();
    error BadTerms();
    error BadDelay();
    error BadAddress();
    error BadClaim();
    error BadClaimTime();
    error BadSubmission();
    error BadVerdict();
    error OrderExists();
    error OrderNotOpen();
    error ClaimOpen();
    error NoClaim();
    error ProofAlreadyRequested();
    error NoProofRequest();
    error ProofAlreadySubmitted();
    error AlreadyRegistered();
    error ClosingNotOpen();
    error VerdictPending();
    error NoVerdict();
    error TooEarly();
    error TooLate();
    error NotMerchant();
    error NothingToWithdraw();

    constructor(address owner_, address relayer_, address guardian_, address[] memory tokens,
                uint256[] memory caps, uint256 verdictDelay_)
        Ownable(owner_)
    {
        if (relayer_ == address(0) || guardian_ == address(0) || guardian_ == relayer_) revert BadAddress();
        if (tokens.length != caps.length) revert BadAddress();
        if (verdictDelay_ < MIN_VERDICT_DELAY || verdictDelay_ > MAX_VERDICT_DELAY) revert BadDelay();
        verdictDelay = verdictDelay_;
        relayer = relayer_;
        guardian = guardian_;
        for (uint256 i = 0; i < tokens.length; ++i) {
            if (tokens[i] == address(0)) revert BadAddress();
            capPerOrder[tokens[i]] = caps[i];
            emit CapSet(tokens[i], caps[i]);
        }
    }

    // ---- Buyer and merchant -----------------------------------------------------------------

    /// @notice Pays an order into escrow. orderRef is the SHA-256 of the merchant's order number
    /// (as the judge checks it); expectedHold and termsHash are what the buyer's client showed.
    function pay(bytes32 orderRef, address merchant, address token, uint128 amount, uint64 expectedHold,
                 bytes32 termsHash)
        external
        nonReentrant
        whenNotPaused
    {
        uint256 cap = capPerOrder[token];
        if (cap == 0) revert TokenNotAccepted();
        if (amount == 0 || amount > cap || amount % CENT != 0) revert BadAmount();
        if (merchant == address(0) || merchant == msg.sender) revert BadAddress();
        uint64 hold = merchantHold[merchant];
        if (hold == 0) revert MerchantNotRegistered();
        if (hold != expectedHold) revert BadHold();
        if (termsHash != merchantTermsHash[merchant]) revert BadTerms();
        if (orders[orderRef].state != State.None) revert OrderExists();
        Order storage o = orders[orderRef];
        o.buyer = msg.sender;
        o.merchant = merchant;
        o.token = token;
        o.amount = amount;
        o.paidAt = uint64(block.timestamp);
        o.expiresAt = uint64(block.timestamp) + hold;
        o.state = State.Open;
        o.termsHash = termsHash;
        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
        emit OrderPaid(orderRef, msg.sender, merchant, token, amount, o.expiresAt, termsHash);
    }

    /// @notice Opens a claim with its content. Checked against the order on chain; the deadline is
    /// block.timestamp against expiresAt whatever the claim says. Not stopped by a pause.
    function openClaim(bytes32 orderRef, bytes calldata claim) external {
        Order storage o = orders[orderRef];
        if (o.state != State.Open) revert OrderNotOpen();
        if (msg.sender != o.buyer) revert NotBuyer();
        if (block.timestamp >= o.expiresAt) revert TooLate();
        if (o.claimedAt != 0) revert ClaimOpen();
        if (claim.length > MAX_CLAIM) revert BadClaim();
        if (!_has(claim, abi.encodePacked('"buyer":"', Strings.toHexString(msg.sender), '"'))
            || !_has(claim, abi.encodePacked('"merchant":"', Strings.toHexString(o.merchant), '"'))
            || !_has(claim, abi.encodePacked('"order_ref":"', Strings.toHexString(uint256(orderRef), 32), '"'))
            || !_has(claim, abi.encodePacked('"terms_hash":"', Strings.toHexString(uint256(o.termsHash), 32), '"'))
            || !_has(claim, abi.encodePacked('"amount_cents":', Strings.toString(o.amount / CENT), ','))
            || !_has(claim, abi.encodePacked('"paid_at":', Strings.toString(o.paidAt), ','))) revert BadClaim();
        uint256 t = _number(claim, '"claimed_at":');
        if (t > block.timestamp || t + CLAIM_SKEW < block.timestamp) revert BadClaimTime();
        bytes32 h = sha256(claim);
        o.claimedAt = uint64(block.timestamp);
        o.claimHash = h;
        o.chain = sha256(abi.encodePacked(h));
        emit ClaimOpened(orderRef, h, o.chain, claim);
    }

    /// @notice Registers what one party sends for the open claim, as the canonical JSON the judge
    /// reads. Role and kind come from the JSON's tail and must match the caller; deadlines are
    /// applied here. Not stopped by a pause.
    function submit(bytes32 orderRef, bytes calldata submission) external {
        Order storage o = _claimed(orderRef);
        if (submission.length > MAX_SUBMISSION) revert BadSubmission();
        if (msg.sender == o.buyer) {
            if (_tail(submission, "evidence", "buyer")) {
                // no deadline: the claim is frozen until it is decided
            } else if (_tail(submission, "proof", "buyer")) {
                if (o.proofRequestedAt == 0) revert NoProofRequest();
                if (o.proofSubmittedAt != 0) revert ProofAlreadySubmitted();
                if (block.timestamp >= uint256(o.proofRequestedAt) + PROOF_WINDOW) revert TooLate();
                o.proofSubmittedAt = uint64(block.timestamp);
            } else if (_tail(submission, "closing_proof", "buyer") || _tail(submission, "closing_statement", "buyer")) {
                _closing(o, F_CLOSING_BUYER);
            } else {
                revert BadSubmission();
            }
        } else if (msg.sender == o.merchant) {
            if (_tail(submission, "response", "merchant")) {
                if (o.flags & (F_RESPONSE | F_NO_RESPONSE) != 0) revert AlreadyRegistered();
                if (block.timestamp > uint256(o.claimedAt) + RESPONSE_WINDOW) revert TooLate();
                o.flags |= F_RESPONSE;
            } else if (_tail(submission, "closing_response", "merchant")) {
                _closing(o, F_CLOSING_RESPONSE);
            } else {
                revert BadSubmission();
            }
        } else {
            revert NotParty();
        }
        _register(orderRef, o, submission);
    }

    /// @notice After RESPONSE_WINDOW with no store response registered, anyone registers the
    /// "no_response" marker; the store can no longer answer the first round.
    function markNoResponse(bytes32 orderRef) external {
        Order storage o = _claimed(orderRef);
        if (o.flags & (F_RESPONSE | F_NO_RESPONSE) != 0) revert AlreadyRegistered();
        if (block.timestamp < uint256(o.claimedAt) + RESPONSE_WINDOW) revert TooEarly();
        o.flags |= F_NO_RESPONSE;
        _register(orderRef, o, M_NO_RESPONSE);
    }

    /// @notice After CLOSING_WINDOW, if either side has not answered the closing round, anyone
    /// registers "closing_timeout" and the round is judged with what was registered.
    function markClosingTimeout(bytes32 orderRef) external {
        Order storage o = _claimed(orderRef);
        if (o.closingOpenedAt == 0) revert ClosingNotOpen();
        uint16 done = F_CLOSING_RESPONSE | F_CLOSING_BUYER;
        if (o.flags & F_CLOSING_TIMEOUT != 0 || o.flags & done == done) revert AlreadyRegistered();
        if (block.timestamp < uint256(o.closingOpenedAt) + CLOSING_WINDOW) revert TooEarly();
        o.flags |= F_CLOSING_TIMEOUT;
        _register(orderRef, o, M_CLOSING_TIMEOUT);
    }

    // ---- Relayer and guardian ---------------------------------------------------------------

    /// @notice Registers a merchant's holding period and the hash of its refund terms. Only affects
    /// orders paid afterwards.
    function setMerchantTerms(address merchant, uint64 holdSeconds, bytes32 termsHash) external {
        if (msg.sender != relayer) revert NotRelayer();
        if (merchant == address(0)) revert BadAddress();
        if (holdSeconds < MIN_HOLD || holdSeconds > MAX_HOLD) revert BadHold();
        if (termsHash == bytes32(0)) revert BadTerms();
        merchantHold[merchant] = holdSeconds;
        merchantTermsHash[merchant] = termsHash;
        emit MerchantTermsSet(merchant, holdSeconds, termsHash);
    }

    /// @notice Asks the buyer for proof, once per claim, when the judge's verdict asks for it.
    function requestProof(bytes32 orderRef) external whenNotPaused {
        if (msg.sender != relayer) revert NotRelayer();
        Order storage o = _claimed(orderRef);
        if (o.proofRequestedAt != 0) revert ProofAlreadyRequested();
        o.proofRequestedAt = uint64(block.timestamp);
        emit ProofRequested(orderRef, block.timestamp + PROOF_WINDOW);
    }

    /// @notice Opens the closing round, once per claim, when the judge's verdict asks for it.
    function openClosingRound(bytes32 orderRef) external whenNotPaused {
        if (msg.sender != relayer) revert NotRelayer();
        Order storage o = _claimed(orderRef);
        if (o.closingOpenedAt != 0) revert AlreadyRegistered();
        o.closingOpenedAt = uint64(block.timestamp);
        _register(orderRef, o, M_CLOSING_OPEN);
    }

    /// @notice Proposes the judge's verdict for the claim and the exact chain the judge saw.
    function proposeVerdict(bytes32 orderRef, Outcome outcome, uint128 refundCents, bytes32 claimHash,
                            bytes32 chain, bytes32 verdictRef) external whenNotPaused {
        if (msg.sender != relayer) revert NotRelayer();
        Order storage o = _claimed(orderRef);
        if (claimHash != o.claimHash || chain != o.chain) revert BadVerdict();
        if (outcome == Outcome.Refund) {
            if (refundCents == 0 || uint256(refundCents) * CENT > o.amount) revert BadAmount();
        } else if (outcome == Outcome.Deny || outcome == Outcome.Invalid) {
            if (refundCents != 0) revert BadAmount();
        } else {
            revert BadVerdict();
        }
        uint64 after_ = uint64(block.timestamp + verdictDelay);
        pendingVerdict[orderRef] = Verdict(outcome, refundCents, after_, verdictRef);
        emit VerdictProposed(orderRef, outcome, refundCents, chain, verdictRef, after_);
    }

    /// @notice Guardian veto during the delay. It only discards the proposal.
    function vetoVerdict(bytes32 orderRef) external {
        if (msg.sender != guardian) revert NotGuardian();
        Verdict memory v = pendingVerdict[orderRef];
        if (v.executeAfter == 0) revert NoVerdict();
        delete pendingVerdict[orderRef];
        emit VerdictVetoed(orderRef, v.verdictRef);
    }

    // ---- Settlement (anyone) ----------------------------------------------------------------

    function executeVerdict(bytes32 orderRef) external nonReentrant {
        Verdict memory v = pendingVerdict[orderRef];
        if (v.executeAfter == 0) revert NoVerdict();
        if (block.timestamp < v.executeAfter) revert TooEarly();
        delete pendingVerdict[orderRef];
        if (v.outcome == Outcome.Invalid) {
            Order storage o = orders[orderRef];
            bytes32 h = o.claimHash;
            o.claimedAt = 0;
            o.proofRequestedAt = 0;
            o.proofSubmittedAt = 0;
            o.closingOpenedAt = 0;
            o.flags = 0;
            o.claimHash = bytes32(0);
            o.chain = bytes32(0);
            emit ClaimCleared(orderRef, h);
        } else {
            _settle(orderRef, uint128(uint256(v.refundCents) * CENT), v.verdictRef);
        }
    }

    /// @notice After the holding period with no claim, the payment goes to the merchant.
    function releaseExpired(bytes32 orderRef) external nonReentrant {
        Order storage o = orders[orderRef];
        if (o.state != State.Open) revert OrderNotOpen();
        if (block.timestamp < o.expiresAt) revert TooEarly();
        if (o.claimedAt != 0) revert ClaimOpen();
        _settle(orderRef, 0, bytes32(0));
    }

    /// @notice If the buyer did not register the requested proof within PROOF_WINDOW, the payment
    /// goes to the merchant ("proof not provided").
    function releaseUnproven(bytes32 orderRef) external nonReentrant {
        Order storage o = _claimed(orderRef);
        if (o.proofRequestedAt == 0) revert NoProofRequest();
        if (o.proofSubmittedAt != 0) revert ProofAlreadySubmitted();
        if (block.timestamp < uint256(o.proofRequestedAt) + PROOF_WINDOW) revert TooEarly();
        _settle(orderRef, 0, bytes32("proof not provided"));
    }

    /// @notice STALL_PERIOD after the claim without a final verdict executed (a system failure, such
    /// as rounds without consensus), anyone releases the payment to the merchant.
    function releaseStalled(bytes32 orderRef) external nonReentrant {
        Order storage o = _claimed(orderRef);
        if (block.timestamp < uint256(o.claimedAt) + STALL_PERIOD) revert TooEarly();
        _settle(orderRef, 0, bytes32("claim not completed"));
    }

    /// @notice The merchant can refund the whole order at any time without a verdict.
    function merchantRefund(bytes32 orderRef) external nonReentrant {
        Order storage o = orders[orderRef];
        if (o.state != State.Open) revert OrderNotOpen();
        if (msg.sender != o.merchant) revert NotMerchant();
        delete pendingVerdict[orderRef];
        _settle(orderRef, o.amount, bytes32("merchant"));
    }

    function withdraw(address token) external nonReentrant {
        uint256 amount = claimable[msg.sender][token];
        if (amount == 0) revert NothingToWithdraw();
        claimable[msg.sender][token] = 0;
        IERC20(token).safeTransfer(msg.sender, amount);
        emit Withdrawn(msg.sender, token, amount);
    }

    function getOrder(bytes32 orderRef) external view returns (Order memory) {
        return orders[orderRef];
    }

    // ---- Internal ---------------------------------------------------------------------------

    /// An open order with an open claim and no verdict waiting: what every claim step needs.
    function _claimed(bytes32 orderRef) internal view returns (Order storage o) {
        o = orders[orderRef];
        if (o.state != State.Open) revert OrderNotOpen();
        if (o.claimedAt == 0) revert NoClaim();
        if (pendingVerdict[orderRef].executeAfter != 0) revert VerdictPending();
    }

    function _closing(Order storage o, uint16 flag) internal {
        if (o.closingOpenedAt == 0) revert ClosingNotOpen();
        if (o.flags & (flag | F_CLOSING_TIMEOUT) != 0) revert AlreadyRegistered();
        if (block.timestamp > uint256(o.closingOpenedAt) + CLOSING_WINDOW) revert TooLate();
        o.flags |= flag;
    }

    function _register(bytes32 orderRef, Order storage o, bytes memory submission) internal {
        bytes32 h = sha256(submission);
        o.chain = sha256(abi.encodePacked(o.chain, h));
        emit Submitted(orderRef, msg.sender, h, o.chain, submission);
    }

    function _settle(bytes32 orderRef, uint128 refund, bytes32 verdictRef) internal {
        Order storage o = orders[orderRef];
        uint128 released = o.amount - refund; // reverts on underflow: refund is bounded by amount
        o.state = State.Settled;
        if (refund > 0) claimable[o.buyer][o.token] += refund;
        if (released > 0) claimable[o.merchant][o.token] += released;
        emit OrderSettled(orderRef, refund, released, verdictRef);
    }

    /// True when the canonical JSON ends with ,"kind":"<kind>","party":"<party>"} (its last two
    /// keys in sorted order, so content earlier in the JSON cannot change them).
    function _tail(bytes calldata s, bytes memory kind, bytes memory party) internal pure returns (bool) {
        bytes memory t = abi.encodePacked(',"kind":"', kind, '","party":"', party, '"}');
        if (s.length < t.length) return false;
        uint256 off = s.length - t.length;
        for (uint256 i = 0; i < t.length; ++i) {
            if (s[off + i] != t[i]) return false;
        }
        return true;
    }

    /// Index just past the first occurrence of needle in hay, or 0 when absent. A key with its
    /// quotes and colon cannot occur inside a JSON string value, where quotes are escaped.
    function _find(bytes calldata hay, bytes memory needle) internal pure returns (uint256) {
        uint256 n = needle.length;
        if (hay.length < n) return 0;
        for (uint256 i = 0; i + n <= hay.length; ++i) {
            if (hay[i] != needle[0]) continue;
            uint256 j = 1;
            while (j < n && hay[i + j] == needle[j]) ++j;
            if (j == n) return i + n;
        }
        return 0;
    }

    function _has(bytes calldata hay, bytes memory needle) internal pure returns (bool) {
        return _find(hay, needle) != 0;
    }

    /// The unsigned integer right after key (for example "claimed_at":); reverts if absent.
    function _number(bytes calldata hay, bytes memory key) internal pure returns (uint256 v) {
        uint256 i = _find(hay, key);
        if (i == 0 || i >= hay.length || hay[i] < "0" || hay[i] > "9") revert BadClaimTime();
        uint256 digits;
        while (i < hay.length && hay[i] >= "0" && hay[i] <= "9") {
            v = v * 10 + (uint8(hay[i]) - 48);
            ++i;
            if (++digits > 12) revert BadClaimTime();
        }
    }

    // ---- Owner ------------------------------------------------------------------------------

    /// @notice Relayer and guardian changes wait ROLE_CHANGE_DELAY, and the two keys must differ.
    function proposeRelayer(address next) external onlyOwner {
        if (next == address(0) || next == guardian) revert BadAddress();
        pendingRelayer = next;
        relayerChangeAfter = block.timestamp + ROLE_CHANGE_DELAY;
        emit RelayerChangeProposed(next, relayerChangeAfter);
    }

    function applyRelayer() external onlyOwner {
        if (pendingRelayer == address(0) || pendingRelayer == guardian) revert BadAddress();
        if (block.timestamp < relayerChangeAfter) revert TooEarly();
        relayer = pendingRelayer;
        pendingRelayer = address(0);
        emit RelayerChanged(relayer);
    }

    function proposeGuardian(address next) external onlyOwner {
        if (next == address(0) || next == relayer) revert BadAddress();
        pendingGuardian = next;
        guardianChangeAfter = block.timestamp + ROLE_CHANGE_DELAY;
        emit GuardianChangeProposed(next, guardianChangeAfter);
    }

    function applyGuardian() external onlyOwner {
        if (pendingGuardian == address(0) || pendingGuardian == relayer) revert BadAddress();
        if (block.timestamp < guardianChangeAfter) revert TooEarly();
        guardian = pendingGuardian;
        pendingGuardian = address(0);
        emit GuardianChanged(guardian);
    }

    /// @notice Lowering or removing a cap only affects new orders; open orders keep their funds.
    function setCap(address token, uint256 cap) external onlyOwner {
        if (token == address(0)) revert BadAddress();
        capPerOrder[token] = cap;
        emit CapSet(token, cap);
    }

    /// @notice Pause stops new orders, verdict proposals, proof requests and closing rounds;
    /// claims, submissions, markers, executing a proposed verdict (still subject to veto), expiry,
    /// unproven and stalled releases, merchant refunds and withdrawals keep working, so funds cannot
    /// be trapped by a pause.
    function pause() external onlyOwner { _pause(); }

    function unpause() external onlyOwner { _unpause(); }
}
