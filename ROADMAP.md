# Roadmap

What comes after the live test. Nothing here is built yet, except the payment gateway (section 1). The live
test judges, the Demo Shop and escrow v3 stay as they are.

## 1. Tenet Pay, the payment gateway for stores

The gateway is live on testnet as Tenet Pay: [paytenet.site](https://paytenet.site), code at
[randyparrs/tenet-pay](https://github.com/randyparrs/tenet-pay), with its own
[ROADMAP.md](https://github.com/randyparrs/tenet-pay/blob/main/ROADMAP.md). Any store can offer Tenet's buyer protection at
checkout, not only the test store.

**Done**

- **Checkout with buyer protection.** The buyer pays into an escrow on Arc; the payment goes to the store when the hold ends, or
  back to the buyer if the judge decides a claim for them.
- **Store registration** with a DNS proof of the domain and terms drafted by AI from the store's refund policy, always confirmed by
  the store.
- **Store panel** for orders, answers to claims, the balance and the terms.
- **Signed webhooks** to the store.
- **Circle wallet with Google** for buyers.
- **Real DKIM signed emails** from the store to a Tenet address for each order.
- **HTML email reading.**
- **Versioned terms.**
- **Judges on Bradbury Phase 2:** the subjective judge is deployed; the email judge waits for Lacre on Phase 2.

**Next** (sections 2 to 4 below go into email bodies by URL, escrow v4 and the store registry)

- **Orvyn:** buyer protection for AI agents that shop. In progress: [orvyn.paytenet.site](https://orvyn.paytenet.site) and
  [randyparrs/orvyn](https://github.com/randyparrs/orvyn).
- **Delivery verification** for "not delivered" claims: the GenLayer judge reads the carrier's public tracking. Fallback: the
  carrier's emails, verified with Lacre.
- **Appeals:** either side can appeal a verdict with a deposit, and a larger GenLayer committee judges it again.
- **The "late" path again,** once Lacre is live on Bradbury Phase 2.
- **Escrow v4:** a fee on what is released to the store, and orders signed by the store.
- **Email bodies by URL,** for real store emails of any size. Required before the first real store.
- **Preconditions and exclusions** supported in the judges.
- **On chain store registry,** and 2048 bit DKIM keys for real stores.

## 2. Email body by URL

Before the first real store joins. A store email of 12 KB fits in one judge transaction on Bradbury, but real
store emails weigh 30 to 100 KB: a 31 KB body needs about twice the gas limit of one transaction, and a
63 KB body about four times. The judge will fetch the body from a URL and compare it with the `bh` hash of
the DKIM signature, as Lacre's Extractor does (`extract(record_id, body_url)`), so the size of the email
no longer matters.

## 3. Escrow v4

- A fee on the amount released to the store, never on refunds, taken in the same split: refund + released +
  fee = amount, to the cent. Executed in `executeVerdict`, `releaseExpired` and `releaseUnproven`; no fee on
  `merchantRefund`.
- `pay` requires the store's signature over the order (order reference, amount, token, terms hash, return
  URL and expiry), so a payment for an order the store never issued is refused on chain.

## 4. Store registry on chain

When there are real stores: a single registry contract on Bradbury that the judges read, mirrored on the
escrow by the relayer, in place of registration by the relayer alone.

## 5. Legal research

Pending, before charging any fee: whether holding third party funds in escrow and charging a fee falls
under money transmission or payment services rules, country by country, and what the GENIUS Act says
about intermediaries. This is research, not legal advice.
