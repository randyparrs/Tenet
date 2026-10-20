# Roadmap

What comes after the live test. Nothing here is built yet. The live test judges, the Demo Shop and escrow v3
stay as they are.

## 1. Payment gateway for stores

Any store can offer Tenet's buyer protection at checkout, not only the test store. The gateway is a product
of its own, on its own site, separate from this page.

- **Store registration.** The store proves it owns its domain with a DNS TXT record
  (`_tenet.<domain>` with `tenet-merchant=<wallet>`), read through two DNS over HTTPS resolvers that have
  to agree. The store pastes its refund policy; a fixed model (Llama 3.3 70B) drafts the structured
  terms, the form flags preconditions and excluded causes for review, and the store always confirms.
  Nothing is registered from the draft alone. The relayer then registers the store's terms on the judges
  and on the escrow.
- **Checkout page.** A "Pay with Tenet" button on the store's site opens Tenet's checkout page. The buyer
  pays from a browser wallet or with Google through Circle, and returns to the store. The store confirms
  the payment by reading the `OrderPaid` event and can also receive a signed webhook.
- **Store panel.** The store answers claims in free text, with a length limit.
- **Store emails.** The store sends its order emails to an address of Tenet for each order
  (`order-<id>@orders.rpmdev.app`). Tenet receives them, picks the DKIM signature aligned with the store's
  domain and attests it on Lacre. The buyer's own email address is never in the signed headers that Lacre
  publishes. The buyer sees the emails in My orders.
- **Email judge for the gateway.** A separate deployment, only for the gateway:
  - the store declares at registration the label of the promised date in its emails (for example
    "Estimated delivery:") and, optionally, the label of the delivery date. The judge reads the promised
    date from that label in any signed and aligned email of the store, whatever type the committee gives
    the email;
  - email bodies up to 12 KB. A larger body is refused with a clear error code, and the page warns before
    sending.
- **Example store.** techshopping.site, a separate brand and domain that sends real signed emails.

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
