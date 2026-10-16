// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";
import {RefundEscrow} from "escrow/RefundEscrow.sol";
import {JudgeVectors as V} from "./JudgeVectors.sol";

contract Stable is ERC20 {
    mapping(address => bool) public blocked;

    constructor(string memory name) ERC20(name, name) {}

    function decimals() public pure override returns (uint8) { return 6; }

    function mint(address to, uint256 amount) external { _mint(to, amount); }

    /// Mimics a stablecoin blocklist: transfers to or from a blocked address revert.
    function setBlocked(address who, bool b) external { blocked[who] = b; }

    function _update(address from, address to, uint256 value) internal override {
        require(!blocked[from] && !blocked[to], "blocked");
        super._update(from, to, value);
    }
}

/// Shared setup and the JSON the judge reads, built the way its canonical form looks.
abstract contract Base is Test {
    RefundEscrow escrow;
    Stable usdc;
    Stable eurc;
    address owner = address(0xA11CE);
    address relayer = address(0xBEEF);
    address guardian = address(0x6A2D);
    address buyer = address(0xB0B);
    address merchant = address(0x5E11);
    address stranger = address(0x5757);
    bytes32 constant ORDER = keccak256("order-1");
    uint128 constant AMOUNT = 25_000_000; // 25.00 in 6 decimals
    uint64 constant HOLD = 30 days;
    bytes32 constant TERMS = keccak256("terms-v1 text");
    uint64 constant T0 = 1_788_264_000;
    // Windows of the escrow under test: the live one (evm/src) or the demo one (evm/demo,
    // FOUNDRY_PROFILE=demo), read from its constants in setUp.
    uint256 RESPONSE_W;
    uint256 CLOSING_W;
    uint256 PROOF_W;
    uint256 MIN_DELAY;

    function setUp() public virtual {
        vm.warp(T0);
        usdc = new Stable("USDC");
        eurc = new Stable("EURC");
        escrow = new RefundEscrow(owner, relayer, guardian, _tokens(), _caps(), 24 hours);
        RESPONSE_W = escrow.RESPONSE_WINDOW();
        CLOSING_W = escrow.CLOSING_WINDOW();
        PROOF_W = escrow.PROOF_WINDOW();
        MIN_DELAY = escrow.MIN_VERDICT_DELAY();
        vm.startPrank(relayer);
        escrow.setMerchantTerms(merchant, HOLD, TERMS);
        escrow.setMerchantTerms(V.MERCHANT, HOLD, V.TERMS);
        vm.stopPrank();
        for (uint256 i = 0; i < 2; ++i) {
            address who = i == 0 ? buyer : V.BUYER;
            usdc.mint(who, 1_000_000_000);
            eurc.mint(who, 1_000_000_000);
            vm.startPrank(who);
            usdc.approve(address(escrow), type(uint256).max);
            eurc.approve(address(escrow), type(uint256).max);
            vm.stopPrank();
        }
    }

    function _tokens() internal view returns (address[] memory tokens) {
        tokens = new address[](2);
        tokens[0] = address(usdc);
        tokens[1] = address(eurc);
    }

    function _caps() internal pure returns (uint256[] memory caps) {
        caps = new uint256[](2);
        caps[0] = 100_000_000;
        caps[1] = 100_000_000;
    }

    function _pay(bytes32 ref, Stable token, uint128 amount) internal {
        vm.prank(buyer);
        escrow.pay(ref, merchant, address(token), amount, HOLD, TERMS);
    }

    function _hex(address a) internal pure returns (string memory) { return Strings.toHexString(a); }

    function _hex32(bytes32 b) internal pure returns (string memory) { return Strings.toHexString(uint256(b), 32); }

    /// A claim as the judge reads it (keys sorted, no spaces), with each checked field settable.
    function _claimJson(bytes32 ref, address b, address m, uint256 cents, uint256 paid, uint256 claimed, bytes32 terms)
        internal pure returns (bytes memory)
    {
        return abi.encodePacked(
            '{"amount_cents":', Strings.toString(cents), ',"buyer":"', _hex(b), '","claimed_at":', Strings.toString(claimed),
            ',"event":"late","merchant":"', _hex(m), '","order_number":"X-1","order_ref":"', _hex32(ref),
            '","paid_at":', Strings.toString(paid), ',"terms_hash":"', _hex32(terms), '","v":"claim-v1"}');
    }

    function _o(bytes32 ref) internal view returns (RefundEscrow.Order memory) {
        return escrow.getOrder(ref);
    }

    function _paidAt(bytes32 ref) internal view returns (uint64) {
        return _o(ref).paidAt;
    }

    function _claimOf(bytes32 ref) internal view returns (bytes memory) {
        return _claimJson(ref, buyer, merchant, AMOUNT / 1e4, _paidAt(ref), block.timestamp, TERMS);
    }

    function _claim(bytes32 ref) internal {
        bytes memory c = _claimOf(ref);
        vm.prank(buyer);
        escrow.openClaim(ref, c);
    }

    function _sub(string memory kind, string memory party) internal pure returns (bytes memory) {
        return abi.encodePacked('{"content":"x","kind":"', kind, '","party":"', party, '"}');
    }

    function _chain(bytes32 ref) internal view returns (bytes32) {
        return _o(ref).chain;
    }

    function _claimHash(bytes32 ref) internal view returns (bytes32) {
        return _o(ref).claimHash;
    }

    function _state(bytes32 ref) internal view returns (RefundEscrow.State) {
        return _o(ref).state;
    }

    function _claimedAt(bytes32 ref) internal view returns (uint64) {
        return _o(ref).claimedAt;
    }

    function _propose(bytes32 ref, RefundEscrow.Outcome o, uint128 cents) internal {
        bytes32 h = _claimHash(ref);
        bytes32 c = _chain(ref);
        vm.prank(relayer);
        escrow.proposeVerdict(ref, o, cents, h, c, bytes32("gl"));
    }
}

contract RefundEscrowTest is Base {
    // ---- E1: what the Phase 0 v3 did and still does ------------------------------------------

    function test_E1_pay_holds_funds_per_order() public {
        _pay(ORDER, usdc, AMOUNT);
        assertEq(usdc.balanceOf(address(escrow)), AMOUNT);
        assertEq(uint8(_state(ORDER)), uint8(RefundEscrow.State.Open));
    }

    function test_E1_pay_rejects_unknown_token_cap_merchant_hold_terms_and_duplicates() public {
        Stable other = new Stable("X");
        vm.startPrank(buyer);
        vm.expectRevert(RefundEscrow.TokenNotAccepted.selector);
        escrow.pay(ORDER, merchant, address(other), AMOUNT, HOLD, TERMS);
        vm.expectRevert(RefundEscrow.BadAmount.selector);
        escrow.pay(ORDER, merchant, address(usdc), 100_010_000, HOLD, TERMS);
        vm.expectRevert(RefundEscrow.BadAmount.selector);
        escrow.pay(ORDER, merchant, address(usdc), 0, HOLD, TERMS);
        vm.expectRevert(RefundEscrow.BadAddress.selector);
        escrow.pay(ORDER, buyer, address(usdc), AMOUNT, HOLD, TERMS);
        vm.expectRevert(RefundEscrow.MerchantNotRegistered.selector);
        escrow.pay(ORDER, address(0x0DD), address(usdc), AMOUNT, HOLD, TERMS);
        vm.expectRevert(RefundEscrow.BadHold.selector);
        escrow.pay(ORDER, merchant, address(usdc), AMOUNT, HOLD - 1, TERMS);
        vm.expectRevert(RefundEscrow.BadTerms.selector);
        escrow.pay(ORDER, merchant, address(usdc), AMOUNT, HOLD, keccak256("other"));
        escrow.pay(ORDER, merchant, address(usdc), AMOUNT, HOLD, TERMS);
        vm.expectRevert(RefundEscrow.OrderExists.selector);
        escrow.pay(ORDER, merchant, address(eurc), AMOUNT, HOLD, TERMS);
        vm.stopPrank();
    }

    function test_E1_only_relayer_sets_terms_within_bounds_for_new_orders_only() public {
        vm.expectRevert(RefundEscrow.NotRelayer.selector);
        vm.prank(merchant);
        escrow.setMerchantTerms(merchant, 60 days, TERMS);
        vm.startPrank(relayer);
        vm.expectRevert(RefundEscrow.BadHold.selector);
        escrow.setMerchantTerms(merchant, 7 days - 1, TERMS);
        vm.expectRevert(RefundEscrow.BadHold.selector);
        escrow.setMerchantTerms(merchant, 180 days + 1, TERMS);
        vm.expectRevert(RefundEscrow.BadTerms.selector);
        escrow.setMerchantTerms(merchant, HOLD, bytes32(0));
        vm.stopPrank();
        _pay(ORDER, usdc, AMOUNT);
        vm.prank(relayer);
        escrow.setMerchantTerms(merchant, 111 days, keccak256("terms v2"));
        assertEq(_o(ORDER).expiresAt, block.timestamp + HOLD);
        assertEq(_o(ORDER).termsHash, TERMS);
    }

    function test_E1_claim_freezes_order_past_expiry_until_verdict() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        vm.warp(block.timestamp + HOLD + 1);
        vm.expectRevert(RefundEscrow.ClaimOpen.selector);
        escrow.releaseExpired(ORDER);
        _propose(ORDER, RefundEscrow.Outcome.Refund, 2500);
        vm.warp(block.timestamp + 24 hours);
        escrow.executeVerdict(ORDER);
        assertEq(escrow.claimable(buyer, address(usdc)), AMOUNT);
    }

    function test_E1_only_relayer_requests_proof_once_and_not_with_a_pending_verdict() public {
        _pay(ORDER, usdc, AMOUNT);
        vm.expectRevert(RefundEscrow.NoClaim.selector);
        vm.prank(relayer);
        escrow.requestProof(ORDER);
        _claim(ORDER);
        vm.expectRevert(RefundEscrow.NotRelayer.selector);
        escrow.requestProof(ORDER);
        vm.prank(relayer);
        escrow.requestProof(ORDER);
        vm.expectRevert(RefundEscrow.ProofAlreadyRequested.selector);
        vm.prank(relayer);
        escrow.requestProof(ORDER);
        _pay(keccak256("o2"), usdc, AMOUNT);
        _claim(keccak256("o2"));
        _propose(keccak256("o2"), RefundEscrow.Outcome.Deny, 0);
        vm.expectRevert(RefundEscrow.VerdictPending.selector);
        vm.prank(relayer);
        escrow.requestProof(keccak256("o2"));
    }

    function test_E1_unproven_claim_releases_to_merchant_after_window_and_waits_for_pending_verdict() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        vm.prank(relayer);
        escrow.requestProof(ORDER);
        vm.warp(block.timestamp + PROOF_W - 1);
        vm.expectRevert(RefundEscrow.TooEarly.selector);
        escrow.releaseUnproven(ORDER);
        _propose(ORDER, RefundEscrow.Outcome.Deny, 0);
        vm.warp(block.timestamp + 1);
        vm.expectRevert(RefundEscrow.VerdictPending.selector);
        escrow.releaseUnproven(ORDER);
        vm.prank(guardian);
        escrow.vetoVerdict(ORDER);
        vm.prank(stranger);
        escrow.releaseUnproven(ORDER);
        assertEq(escrow.claimable(merchant, address(usdc)), AMOUNT);
    }

    function test_E1_only_relayer_proposes_bounded_by_amount_and_executes_after_delay() public {
        _pay(ORDER, usdc, AMOUNT);
        vm.expectRevert(RefundEscrow.NoClaim.selector);
        vm.prank(relayer);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Deny, 0, bytes32(0), bytes32(0), bytes32("gl"));
        _claim(ORDER);
        bytes32 h = _claimHash(ORDER);
        bytes32 c = _chain(ORDER);
        vm.expectRevert(RefundEscrow.NotRelayer.selector);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Deny, 0, h, c, bytes32("gl"));
        vm.startPrank(relayer);
        vm.expectRevert(RefundEscrow.BadAmount.selector);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Refund, 2501, h, c, bytes32("gl"));
        vm.expectRevert(RefundEscrow.BadAmount.selector);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Refund, 0, h, c, bytes32("gl"));
        vm.expectRevert(RefundEscrow.BadAmount.selector);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Deny, 1, h, c, bytes32("gl"));
        vm.expectRevert(RefundEscrow.BadVerdict.selector);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.None, 0, h, c, bytes32("gl"));
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Refund, 1250, h, c, bytes32("gl"));
        vm.expectRevert(RefundEscrow.VerdictPending.selector);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Refund, 1250, h, c, bytes32("gl"));
        vm.stopPrank();
        vm.warp(block.timestamp + 24 hours - 1);
        vm.expectRevert(RefundEscrow.TooEarly.selector);
        escrow.executeVerdict(ORDER);
        vm.warp(block.timestamp + 1);
        vm.prank(stranger);
        escrow.executeVerdict(ORDER);
        assertEq(escrow.claimable(buyer, address(usdc)), 12_500_000);
        assertEq(escrow.claimable(merchant, address(usdc)), 12_500_000);
        vm.prank(buyer);
        escrow.withdraw(address(usdc));
        vm.prank(merchant);
        escrow.withdraw(address(usdc));
        assertEq(usdc.balanceOf(address(escrow)), 0);
        vm.expectRevert(RefundEscrow.NothingToWithdraw.selector);
        vm.prank(buyer);
        escrow.withdraw(address(usdc));
    }

    function test_E1_only_guardian_vetoes_without_moving_funds() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        _propose(ORDER, RefundEscrow.Outcome.Refund, 2500);
        vm.expectRevert(RefundEscrow.NotGuardian.selector);
        vm.prank(relayer);
        escrow.vetoVerdict(ORDER);
        vm.prank(guardian);
        escrow.vetoVerdict(ORDER);
        vm.expectRevert(RefundEscrow.NoVerdict.selector);
        escrow.executeVerdict(ORDER);
        assertEq(usdc.balanceOf(address(escrow)), AMOUNT);
        assertEq(uint8(_state(ORDER)), uint8(RefundEscrow.State.Open));
        _propose(ORDER, RefundEscrow.Outcome.Deny, 0);
        vm.warp(block.timestamp + 24 hours);
        escrow.executeVerdict(ORDER);
        assertEq(escrow.claimable(merchant, address(usdc)), AMOUNT);
    }

    function test_E1_guardian_and_relayer_keys_must_differ_and_changes_wait() public {
        vm.expectRevert(RefundEscrow.BadAddress.selector);
        new RefundEscrow(owner, relayer, relayer, _tokens(), _caps(), 24 hours);
        vm.startPrank(owner);
        vm.expectRevert(RefundEscrow.BadAddress.selector);
        escrow.proposeRelayer(guardian);
        vm.expectRevert(RefundEscrow.BadAddress.selector);
        escrow.proposeGuardian(relayer);
        escrow.proposeRelayer(address(0x1234));
        vm.expectRevert(RefundEscrow.TooEarly.selector);
        escrow.applyRelayer();
        vm.warp(block.timestamp + 48 hours);
        escrow.applyRelayer();
        vm.stopPrank();
        assertEq(escrow.relayer(), address(0x1234));
    }

    function test_E1_expiry_without_claim_pays_merchant_and_merchant_refunds_any_time() public {
        _pay(ORDER, usdc, AMOUNT);
        vm.expectRevert(RefundEscrow.TooEarly.selector);
        escrow.releaseExpired(ORDER);
        vm.warp(block.timestamp + HOLD);
        escrow.releaseExpired(ORDER);
        assertEq(escrow.claimable(merchant, address(usdc)), AMOUNT);
        _pay(keccak256("o2"), usdc, AMOUNT);
        _claim(keccak256("o2"));
        vm.expectRevert(RefundEscrow.NotMerchant.selector);
        escrow.merchantRefund(keccak256("o2"));
        vm.prank(merchant);
        escrow.merchantRefund(keccak256("o2"));
        assertEq(escrow.claimable(buyer, address(usdc)), AMOUNT);
    }

    function test_E1_blocked_buyer_cannot_block_settlement() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        usdc.setBlocked(buyer, true);
        _propose(ORDER, RefundEscrow.Outcome.Refund, 1000);
        vm.warp(block.timestamp + 24 hours);
        escrow.executeVerdict(ORDER);
        vm.prank(merchant);
        escrow.withdraw(address(usdc));
        assertEq(usdc.balanceOf(merchant), 15_000_000);
    }

    function test_E1_pause_stops_orders_and_relayer_steps_but_not_claims_submissions_or_settlement() public {
        _pay(ORDER, usdc, AMOUNT);
        vm.prank(owner);
        escrow.pause();
        vm.expectRevert();
        _pay(keccak256("o2"), usdc, AMOUNT);
        _claim(ORDER);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("response", "merchant"));
        bytes32 h = _claimHash(ORDER);
        bytes32 c = _chain(ORDER);
        vm.startPrank(relayer);
        vm.expectRevert();
        escrow.requestProof(ORDER);
        vm.expectRevert();
        escrow.openClosingRound(ORDER);
        vm.expectRevert();
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Deny, 0, h, c, bytes32("gl"));
        vm.stopPrank();
        vm.warp(block.timestamp + 60 days);
        escrow.releaseStalled(ORDER);
        vm.prank(merchant);
        escrow.withdraw(address(usdc));
        assertEq(usdc.balanceOf(merchant), AMOUNT);
    }

    function test_E1_verdict_delay_bounds() public {
        vm.expectRevert(RefundEscrow.BadDelay.selector);
        new RefundEscrow(owner, relayer, guardian, _tokens(), _caps(), MIN_DELAY - 1);
        vm.expectRevert(RefundEscrow.BadDelay.selector);
        new RefundEscrow(owner, relayer, guardian, _tokens(), _caps(), 7 days + 1);
    }

    // ---- E2: the claim is checked against the order ------------------------------------------

    function test_E2_valid_claim_only_by_buyer_once() public {
        _pay(ORDER, usdc, AMOUNT);
        bytes memory c = _claimOf(ORDER);
        vm.expectRevert(RefundEscrow.NotBuyer.selector);
        vm.prank(relayer);
        escrow.openClaim(ORDER, c);
        vm.prank(buyer);
        escrow.openClaim(ORDER, c);
        assertEq(_claimHash(ORDER), sha256(c));
        assertEq(_chain(ORDER), sha256(abi.encodePacked(sha256(c))));
        vm.expectRevert(RefundEscrow.ClaimOpen.selector);
        vm.prank(buyer);
        escrow.openClaim(ORDER, c);
    }

    function test_E2a_claim_time_in_the_future_is_rejected() public {
        _pay(ORDER, usdc, AMOUNT);
        vm.warp(block.timestamp + 1 days);
        bytes memory c = _claimJson(ORDER, buyer, merchant, 2500, _paidAt(ORDER), block.timestamp + 1, TERMS);
        vm.expectRevert(RefundEscrow.BadClaimTime.selector);
        vm.prank(buyer);
        escrow.openClaim(ORDER, c);
    }

    function test_E2b_claim_time_more_than_15_minutes_back_is_rejected_15_exactly_accepted() public {
        _pay(ORDER, usdc, AMOUNT);
        vm.warp(block.timestamp + 1 days);
        bytes memory late = _claimJson(ORDER, buyer, merchant, 2500, _paidAt(ORDER), block.timestamp - 15 minutes - 1, TERMS);
        vm.expectRevert(RefundEscrow.BadClaimTime.selector);
        vm.prank(buyer);
        escrow.openClaim(ORDER, late);
        bytes memory edge = _claimJson(ORDER, buyer, merchant, 2500, _paidAt(ORDER), block.timestamp - 15 minutes, TERMS);
        vm.prank(buyer);
        escrow.openClaim(ORDER, edge);
        assertEq(_claimedAt(ORDER), block.timestamp);
    }

    function test_E2c_expired_order_rejects_claim_whatever_claimed_at_says() public {
        _pay(ORDER, usdc, AMOUNT);
        uint256 p = _paidAt(ORDER);
        vm.warp(p + HOLD);
        bytes memory c = _claimJson(ORDER, buyer, merchant, 2500, p, p + HOLD - 1 days, TERMS);
        vm.expectRevert(RefundEscrow.TooLate.selector);
        vm.prank(buyer);
        escrow.openClaim(ORDER, c);
        c = _claimJson(ORDER, buyer, merchant, 2500, p, block.timestamp, TERMS);
        vm.expectRevert(RefundEscrow.TooLate.selector);
        vm.prank(buyer);
        escrow.openClaim(ORDER, c);
    }

    function test_E2d_amount_other_than_the_total_is_rejected() public {
        _pay(ORDER, usdc, AMOUNT);
        uint256 p = _paidAt(ORDER);
        uint256[3] memory wrong = [uint256(2499), 2501, 250];
        for (uint256 i = 0; i < 3; ++i) {
            bytes memory c = _claimJson(ORDER, buyer, merchant, wrong[i], p, block.timestamp, TERMS);
            vm.expectRevert(RefundEscrow.BadClaim.selector);
            vm.prank(buyer);
            escrow.openClaim(ORDER, c);
        }
    }

    function test_E2e_buyer_other_than_the_caller_is_rejected() public {
        _pay(ORDER, usdc, AMOUNT);
        bytes memory c = _claimJson(ORDER, stranger, merchant, 2500, _paidAt(ORDER), block.timestamp, TERMS);
        vm.expectRevert(RefundEscrow.BadClaim.selector);
        vm.prank(buyer);
        escrow.openClaim(ORDER, c);
    }

    function test_E2f_reference_payment_time_merchant_or_terms_mismatch_is_rejected() public {
        _pay(ORDER, usdc, AMOUNT);
        uint256 p = _paidAt(ORDER);
        bytes[4] memory bad = [
            _claimJson(keccak256("other"), buyer, merchant, 2500, p, block.timestamp, TERMS),
            _claimJson(ORDER, buyer, merchant, 2500, p - 1, block.timestamp, TERMS),
            _claimJson(ORDER, buyer, stranger, 2500, p, block.timestamp, TERMS),
            _claimJson(ORDER, buyer, merchant, 2500, p, block.timestamp, keccak256("other terms"))
        ];
        for (uint256 i = 0; i < 4; ++i) {
            vm.expectRevert(RefundEscrow.BadClaim.selector);
            vm.prank(buyer);
            escrow.openClaim(ORDER, bad[i]);
        }
    }

    function test_E2g_total_without_whole_cents_is_rejected_at_payment() public {
        vm.startPrank(buyer);
        vm.expectRevert(RefundEscrow.BadAmount.selector);
        escrow.pay(ORDER, merchant, address(usdc), 25_000_001, HOLD, TERMS);
        vm.expectRevert(RefundEscrow.BadAmount.selector);
        escrow.pay(ORDER, merchant, address(usdc), 9_999, HOLD, TERMS);
        escrow.pay(ORDER, merchant, address(usdc), 10_000, HOLD, TERMS);
        vm.stopPrank();
    }

    // ---- E3: hashes and chain equal to the judge's (vectors from the judge contract) ----------

    function _vpay(bytes32 ref) internal {
        vm.warp(V.PAID);
        vm.prank(V.BUYER);
        escrow.pay(ref, V.MERCHANT, address(usdc), 50_000_000, HOLD, V.TERMS);
        vm.warp(V.CLAIMED);
    }

    function _vclaim(bytes32 ref, bytes memory claim, bytes32 h, bytes32 c0) internal {
        _vpay(ref);
        vm.prank(V.BUYER);
        escrow.openClaim(ref, claim);
        assertEq(_claimHash(ref), h);
        assertEq(_chain(ref), c0);
    }

    function test_E3_vector_late_two_buyer_emails() public {
        _vclaim(V.V1_REF, V.V1_CLAIM, V.V1_CLAIM_HASH, V.V1_CHAIN0);
        vm.prank(V.BUYER);
        escrow.submit(V.V1_REF, V.V1_S1);
        assertEq(_chain(V.V1_REF), V.V1_C1);
        vm.prank(V.BUYER);
        escrow.submit(V.V1_REF, V.V1_S2);
        assertEq(_chain(V.V1_REF), V.V1_C2);
        assertEq(_chain(V.V1_REF), V.V1_JUDGE_CHAIN);
    }

    function test_E3_vector_not_as_described_spanish_closing_round() public {
        _vclaim(V.V2_REF, V.V2_CLAIM, V.V2_CLAIM_HASH, V.V2_CHAIN0);
        vm.prank(V.MERCHANT);
        escrow.submit(V.V2_REF, V.V2_S1);
        assertEq(_chain(V.V2_REF), V.V2_C1);
        vm.prank(relayer);
        escrow.openClosingRound(V.V2_REF);
        assertEq(_chain(V.V2_REF), V.V2_C2);
        vm.prank(V.BUYER);
        escrow.submit(V.V2_REF, V.V2_S3);
        assertEq(_chain(V.V2_REF), V.V2_C3);
        vm.prank(V.MERCHANT);
        escrow.submit(V.V2_REF, V.V2_S4);
        assertEq(_chain(V.V2_REF), V.V2_JUDGE_CHAIN);
        vm.prank(relayer);
        escrow.proposeVerdict(V.V2_REF, RefundEscrow.Outcome.Deny, 0, V.V2_CLAIM_HASH, V.V2_JUDGE_CHAIN, bytes32("gl"));
    }

    function test_E3_vector_not_delivered_no_response_marker() public {
        _vclaim(V.V3_REF, V.V3_CLAIM, V.V3_CLAIM_HASH, V.V3_CHAIN0);
        vm.warp(V.CLAIMED + RESPONSE_W);
        vm.prank(stranger);
        escrow.markNoResponse(V.V3_REF);
        assertEq(_chain(V.V3_REF), V.V3_JUDGE_CHAIN);
        vm.prank(relayer);
        escrow.proposeVerdict(V.V3_REF, RefundEscrow.Outcome.Refund, 5000, V.V3_CLAIM_HASH, V.V3_JUDGE_CHAIN, bytes32("gl"));
        vm.warp(block.timestamp + 24 hours);
        escrow.executeVerdict(V.V3_REF);
        assertEq(escrow.claimable(V.BUYER, address(usdc)), 50_000_000);
    }

    // ---- E4: submissions ----------------------------------------------------------------------

    function test_E4_allowed_pairs_from_the_right_address() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        bytes32 c = _chain(ORDER);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("evidence", "buyer"));
        c = sha256(abi.encodePacked(c, sha256(_sub("evidence", "buyer"))));
        assertEq(_chain(ORDER), c);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("response", "merchant"));
        vm.prank(relayer);
        escrow.openClosingRound(ORDER);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("closing_statement", "buyer"));
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("closing_response", "merchant"));
        vm.prank(relayer);
        escrow.requestProof(ORDER);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("proof", "buyer"));
    }

    function test_E4_wrong_pair_wrong_address_or_changed_tail_is_rejected() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        vm.startPrank(buyer);
        vm.expectRevert(RefundEscrow.BadSubmission.selector);
        escrow.submit(ORDER, _sub("response", "buyer"));
        vm.expectRevert(RefundEscrow.BadSubmission.selector);
        escrow.submit(ORDER, _sub("response", "merchant")); // buyer posing as the merchant
        vm.expectRevert(RefundEscrow.BadSubmission.selector);
        escrow.submit(ORDER, _sub("no_response", "escrow"));
        vm.expectRevert(RefundEscrow.BadSubmission.selector);
        escrow.submit(ORDER, abi.encodePacked('{"content":"x","kind":"evidence","party":"buyer"} '));
        vm.expectRevert(RefundEscrow.BadSubmission.selector);
        escrow.submit(ORDER, abi.encodePacked('{"content":"x","kind":"evidence","party":"buyer","x":1}'));
        vm.stopPrank();
        vm.startPrank(merchant);
        vm.expectRevert(RefundEscrow.BadSubmission.selector);
        escrow.submit(ORDER, _sub("evidence", "buyer"));
        vm.expectRevert(RefundEscrow.BadSubmission.selector);
        escrow.submit(ORDER, _sub("evidence", "merchant"));
        vm.expectRevert(RefundEscrow.BadSubmission.selector);
        escrow.submit(ORDER, _sub("proof", "merchant"));
        vm.stopPrank();
        vm.expectRevert(RefundEscrow.NotParty.selector);
        vm.prank(stranger);
        escrow.submit(ORDER, _sub("evidence", "buyer"));
    }

    function test_E4_store_response_only_within_72_hours_and_once() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        uint256 t = block.timestamp;
        vm.warp(t + RESPONSE_W + 1);
        vm.expectRevert(RefundEscrow.TooLate.selector);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("response", "merchant"));
        vm.warp(t + RESPONSE_W);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("response", "merchant"));
        vm.expectRevert(RefundEscrow.AlreadyRegistered.selector);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("response", "merchant"));
    }

    function test_E4_proof_only_after_request_once_within_7_days() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        vm.expectRevert(RefundEscrow.NoProofRequest.selector);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("proof", "buyer"));
        vm.prank(relayer);
        escrow.requestProof(ORDER);
        uint256 t = block.timestamp;
        vm.warp(t + PROOF_W);
        vm.expectRevert(RefundEscrow.TooLate.selector);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("proof", "buyer"));
        vm.warp(t + PROOF_W - 1);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("proof", "buyer"));
        vm.expectRevert(RefundEscrow.ProofAlreadySubmitted.selector);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("proof", "buyer"));
    }

    function test_E4_closing_items_only_in_an_open_round_once_within_72_hours() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        vm.expectRevert(RefundEscrow.ClosingNotOpen.selector);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("closing_response", "merchant"));
        vm.prank(relayer);
        escrow.openClosingRound(ORDER);
        vm.expectRevert(RefundEscrow.AlreadyRegistered.selector);
        vm.prank(relayer);
        escrow.openClosingRound(ORDER);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("closing_proof", "buyer"));
        vm.expectRevert(RefundEscrow.AlreadyRegistered.selector);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("closing_statement", "buyer"));
        vm.warp(block.timestamp + CLOSING_W + 1);
        vm.expectRevert(RefundEscrow.TooLate.selector);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("closing_response", "merchant"));
    }

    function test_E4_no_response_marker_not_early_not_after_a_response() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        uint256 t = block.timestamp;
        vm.warp(t + RESPONSE_W - 1);
        vm.expectRevert(RefundEscrow.TooEarly.selector);
        escrow.markNoResponse(ORDER);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("response", "merchant"));
        vm.warp(t + RESPONSE_W);
        vm.expectRevert(RefundEscrow.AlreadyRegistered.selector);
        escrow.markNoResponse(ORDER);
        _pay(keccak256("o2"), usdc, AMOUNT);
        _claim(keccak256("o2"));
        vm.warp(block.timestamp + RESPONSE_W);
        vm.prank(buyer);
        escrow.markNoResponse(keccak256("o2"));
        vm.expectRevert(RefundEscrow.AlreadyRegistered.selector);
        vm.prank(merchant);
        escrow.submit(keccak256("o2"), _sub("response", "merchant"));
    }

    function test_E4_closing_timeout_not_early_not_when_both_answered() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        vm.prank(relayer);
        escrow.openClosingRound(ORDER);
        uint256 t = block.timestamp;
        vm.warp(t + CLOSING_W - 1);
        vm.expectRevert(RefundEscrow.TooEarly.selector);
        escrow.markClosingTimeout(ORDER);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("closing_proof", "buyer"));
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("closing_response", "merchant"));
        vm.warp(t + CLOSING_W);
        vm.expectRevert(RefundEscrow.AlreadyRegistered.selector);
        escrow.markClosingTimeout(ORDER);
    }

    function test_E4_no_submission_while_a_verdict_is_pending() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        _propose(ORDER, RefundEscrow.Outcome.Deny, 0);
        vm.expectRevert(RefundEscrow.VerdictPending.selector);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("evidence", "buyer"));
    }

    // ---- E5: the verdict is bound to the claim and the chain ---------------------------------

    function test_E5_other_claim_hash_or_chain_is_rejected() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        bytes32 h = _claimHash(ORDER);
        bytes32 c0 = _chain(ORDER);
        vm.prank(buyer);
        escrow.submit(ORDER, _sub("evidence", "buyer"));
        bytes32 c1 = _chain(ORDER);
        bytes32 fake = sha256(abi.encodePacked(c1, sha256(_sub("response", "merchant"))));
        bytes32 reordered = sha256(abi.encodePacked(sha256(abi.encodePacked(c0, sha256(_sub("x", "y")))), sha256(_sub("evidence", "buyer"))));
        bytes32[4] memory badChains = [c0, fake, reordered, bytes32(0)];
        vm.startPrank(relayer);
        for (uint256 i = 0; i < 4; ++i) {
            vm.expectRevert(RefundEscrow.BadVerdict.selector);
            escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Deny, 0, h, badChains[i], bytes32("gl"));
        }
        vm.expectRevert(RefundEscrow.BadVerdict.selector);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Deny, 0, keccak256("other claim"), c1, bytes32("gl"));
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Deny, 0, h, c1, bytes32("gl"));
        vm.stopPrank();
    }

    // ---- E6: INVALID_CLAIM ---------------------------------------------------------------------

    function test_E6_invalid_claim_clears_without_moving_funds_and_buyer_reopens_in_time() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("response", "merchant"));
        _propose(ORDER, RefundEscrow.Outcome.Invalid, 0);
        vm.warp(block.timestamp + 24 hours);
        escrow.executeVerdict(ORDER);
        assertEq(usdc.balanceOf(address(escrow)), AMOUNT);
        assertEq(escrow.claimable(buyer, address(usdc)) + escrow.claimable(merchant, address(usdc)), 0);
        assertEq(_claimedAt(ORDER), 0);
        assertEq(_chain(ORDER), bytes32(0));
        assertEq(uint8(_state(ORDER)), uint8(RefundEscrow.State.Open));
        _claim(ORDER);
        vm.prank(merchant);
        escrow.submit(ORDER, _sub("response", "merchant")); // the new claim has its own window
    }

    function test_E6_invalid_claim_after_expiry_cannot_reopen_and_order_expires_normally() public {
        _pay(ORDER, usdc, AMOUNT);
        vm.warp(block.timestamp + HOLD - 1 hours);
        _claim(ORDER);
        _propose(ORDER, RefundEscrow.Outcome.Invalid, 0);
        vm.warp(block.timestamp + 24 hours);
        escrow.executeVerdict(ORDER);
        bytes memory c = _claimOf(ORDER);
        vm.expectRevert(RefundEscrow.TooLate.selector);
        vm.prank(buyer);
        escrow.openClaim(ORDER, c);
        escrow.releaseExpired(ORDER);
        assertEq(escrow.claimable(merchant, address(usdc)), AMOUNT);
    }

    // ---- E7: release after 60 days without a final verdict ------------------------------------

    function test_E7_stalled_release_not_before_60_days_then_anyone_including_buyer() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        uint256 t = block.timestamp;
        vm.warp(t + 60 days - 1);
        vm.expectRevert(RefundEscrow.TooEarly.selector);
        escrow.releaseStalled(ORDER);
        vm.warp(t + 60 days);
        vm.prank(buyer);
        escrow.releaseStalled(ORDER);
        assertEq(escrow.claimable(merchant, address(usdc)), AMOUNT);
    }

    function test_E7_stalled_release_blocked_while_a_verdict_is_pending() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        vm.warp(block.timestamp + 60 days);
        _propose(ORDER, RefundEscrow.Outcome.Refund, 2500);
        vm.expectRevert(RefundEscrow.VerdictPending.selector);
        escrow.releaseStalled(ORDER);
        vm.warp(block.timestamp + 24 hours);
        escrow.executeVerdict(ORDER);
        assertEq(escrow.claimable(buyer, address(usdc)), AMOUNT);
    }

    function test_E7_verdict_after_the_release_has_no_effect() public {
        _pay(ORDER, usdc, AMOUNT);
        _claim(ORDER);
        bytes32 h = _claimHash(ORDER);
        bytes32 c = _chain(ORDER);
        vm.warp(block.timestamp + 60 days);
        escrow.releaseStalled(ORDER);
        vm.expectRevert(RefundEscrow.OrderNotOpen.selector);
        vm.prank(relayer);
        escrow.proposeVerdict(ORDER, RefundEscrow.Outcome.Refund, 2500, h, c, bytes32("gl"));
        vm.expectRevert(RefundEscrow.NoVerdict.selector);
        escrow.executeVerdict(ORDER);
        assertEq(escrow.claimable(buyer, address(usdc)), 0);
        assertEq(escrow.claimable(merchant, address(usdc)), AMOUNT);
    }

    // ---- E9: no funds trapped ------------------------------------------------------------------

    function test_E9_every_open_order_can_close_even_while_paused() public {
        bytes32 a = keccak256("no-claim");
        bytes32 b = keccak256("claim");
        bytes32 c = keccak256("proof-requested");
        bytes32 d = keccak256("closing-open");
        bytes32 e = keccak256("vetoed");
        _pay(a, usdc, AMOUNT);
        _pay(b, usdc, AMOUNT);
        _pay(c, eurc, AMOUNT);
        _pay(d, usdc, AMOUNT);
        _pay(e, usdc, AMOUNT);
        _claim(b);
        _claim(c);
        _claim(d);
        _claim(e);
        vm.startPrank(relayer);
        escrow.requestProof(c);
        escrow.openClosingRound(d);
        vm.stopPrank();
        _propose(e, RefundEscrow.Outcome.Refund, 2500);
        vm.prank(guardian);
        escrow.vetoVerdict(e);
        vm.prank(owner);
        escrow.pause();
        vm.warp(block.timestamp + 61 days);
        vm.startPrank(stranger);
        escrow.releaseExpired(a);
        escrow.releaseStalled(b);
        escrow.releaseUnproven(c);
        escrow.releaseStalled(d);
        escrow.releaseStalled(e);
        vm.stopPrank();
        bytes32[5] memory all = [a, b, c, d, e];
        for (uint256 i = 0; i < 5; ++i) assertEq(uint8(_state(all[i])), uint8(RefundEscrow.State.Settled));
        assertEq(escrow.claimable(merchant, address(usdc)), 4 * uint256(AMOUNT));
        assertEq(escrow.claimable(merchant, address(eurc)), AMOUNT);
    }
}

/// E8: random sequences of everything anyone can do; the handler keeps the expected balances.
contract Handler is Base {
    bytes32[] public refs;
    mapping(bytes32 => uint256) public amountOf;
    uint256 public settledRefund;
    uint256 public settledRelease;
    uint256 public withdrawn;
    uint256 public paidIn;
    bool public broken; // a settlement whose refund + release is not the order total
    uint256 public settlements;
    uint256 public claims;

    function setUp() public override {}

    function init(RefundEscrow e, Stable u) external {
        escrow = e;
        usdc = u;
    }

    function _ref(uint256 seed) internal view returns (bytes32) {
        return refs.length == 0 ? bytes32(0) : refs[seed % refs.length];
    }

    function pay(uint256 cents) external {
        cents = bound(cents, 1, 10_000);
        bytes32 ref = keccak256(abi.encode(refs.length));
        vm.prank(buyer);
        escrow.pay(ref, merchant, address(usdc), uint128(cents * 1e4), HOLD, TERMS);
        refs.push(ref);
        amountOf[ref] = cents * 1e4;
        paidIn += cents * 1e4;
    }

    function claim(uint256 seed) external {
        bytes32 ref = _ref(seed);
        RefundEscrow.Order memory o = escrow.getOrder(ref);
        bytes memory c = _claimJson(ref, buyer, merchant, o.amount / 1e4, o.paidAt, block.timestamp, TERMS);
        vm.prank(buyer);
        try escrow.openClaim(ref, c) { claims++; } catch {}
    }

    function respond(uint256 seed) external {
        vm.prank(merchant);
        try escrow.submit(_ref(seed), _sub("response", "merchant")) {} catch {}
    }

    function evidence(uint256 seed) external {
        vm.prank(buyer);
        try escrow.submit(_ref(seed), _sub("evidence", "buyer")) {} catch {}
    }

    function noResponse(uint256 seed) external {
        try escrow.markNoResponse(_ref(seed)) {} catch {}
    }

    function propose(uint256 seed, uint8 outcome, uint256 cents) external {
        bytes32 ref = _ref(seed);
        RefundEscrow.Outcome o = RefundEscrow.Outcome(bound(outcome, 1, 3));
        cents = o == RefundEscrow.Outcome.Refund ? bound(cents, 1, 20_000) : 0;
        RefundEscrow.Order memory od = escrow.getOrder(ref);
        vm.prank(relayer);
        try escrow.proposeVerdict(ref, o, uint128(cents), od.claimHash, od.chain, bytes32("gl")) {} catch {}
    }

    function veto(uint256 seed) external {
        vm.prank(guardian);
        try escrow.vetoVerdict(_ref(seed)) {} catch {}
    }

    function _track(bytes32 ref, function () external f) internal {
        uint256 b = escrow.claimable(buyer, address(usdc));
        uint256 m = escrow.claimable(merchant, address(usdc));
        try f() {
            uint256 db = escrow.claimable(buyer, address(usdc)) - b;
            uint256 dm = escrow.claimable(merchant, address(usdc)) - m;
            if (db + dm > 0) {
                settlements++;
                if (db + dm != amountOf[ref]) broken = true;
                settledRefund += db;
                settledRelease += dm;
            }
        } catch {}
    }

    bytes32 internal cur;

    function _execute() external { escrow.executeVerdict(cur); }
    function _expire() external { escrow.releaseExpired(cur); }
    function _stall() external { escrow.releaseStalled(cur); }
    function _merchantRefund() external { vm.prank(merchant); escrow.merchantRefund(cur); }

    function execute(uint256 seed) external { cur = _ref(seed); _track(cur, this._execute); }
    function expire(uint256 seed) external { cur = _ref(seed); _track(cur, this._expire); }
    function stall(uint256 seed) external { cur = _ref(seed); _track(cur, this._stall); }
    function merchantRefunds(uint256 seed) external { cur = _ref(seed); _track(cur, this._merchantRefund); }

    function withdraw(bool fromBuyer) external {
        address who = fromBuyer ? buyer : merchant;
        uint256 c = escrow.claimable(who, address(usdc));
        if (c == 0) return;
        vm.prank(who);
        escrow.withdraw(address(usdc));
        withdrawn += c;
    }

    function warp(uint256 secs) external {
        vm.warp(block.timestamp + bound(secs, 1, 20 days));
    }

    function openAmount() external view returns (uint256 sum) {
        for (uint256 i = 0; i < refs.length; ++i) {
            RefundEscrow.Order memory o = escrow.getOrder(refs[i]);
            if (o.state == RefundEscrow.State.Open) sum += o.amount;
        }
    }

    function refCount() external view returns (uint256) { return refs.length; }
}

contract RefundEscrowInvariant is Base {
    Handler h;

    function setUp() public override {
        super.setUp();
        h = new Handler();
        h.init(escrow, usdc);
        usdc.mint(buyer, 1_000_000_000_000);
        targetContract(address(h));
        bytes4[] memory s = new bytes4[](13);
        s[0] = Handler.pay.selector;
        s[1] = Handler.claim.selector;
        s[2] = Handler.respond.selector;
        s[3] = Handler.evidence.selector;
        s[4] = Handler.noResponse.selector;
        s[5] = Handler.propose.selector;
        s[6] = Handler.veto.selector;
        s[7] = Handler.execute.selector;
        s[8] = Handler.expire.selector;
        s[9] = Handler.stall.selector;
        s[10] = Handler.merchantRefunds.selector;
        s[11] = Handler.withdraw.selector;
        s[12] = Handler.warp.selector;
        targetSelector(FuzzSelector({addr: address(h), selectors: s}));
    }

    uint256 maxSettlements;
    uint256 maxClaims;

    function afterInvariant() public {
        if (h.settlements() > maxSettlements) maxSettlements = h.settlements();
        if (h.claims() > maxClaims) maxClaims = h.claims();
        emit log_named_uint("claims in this run", h.claims());
        emit log_named_uint("settlements in this run", h.settlements());
    }

    /// Escrow balance = credited balances not yet withdrawn + open orders.
    function invariant_E8_balance_equals_credited_plus_open() public view {
        uint256 credited = escrow.claimable(buyer, address(usdc)) + escrow.claimable(merchant, address(usdc));
        assertEq(usdc.balanceOf(address(escrow)), credited + h.openAmount());
    }

    /// Every payment in is either still open, credited, or withdrawn; nothing is created or lost.
    function invariant_E8_each_settlement_splits_exactly_its_own_total() public view {
        assertFalse(h.broken());
    }

    function invariant_E8_money_is_conserved() public view {
        assertEq(h.paidIn(), h.openAmount() + h.settledRefund() + h.settledRelease());
        assertEq(h.settledRefund() + h.settledRelease(), escrow.claimable(buyer, address(usdc))
            + escrow.claimable(merchant, address(usdc)) + h.withdrawn());
    }
}
