# H-05 H5 VIP Modal Product Acceptance

Status: approved  
Task: H-05 - 确认 H5 VIP 弹窗文案与支付跳转路径  
Approved on: 2026-05-20  
Approved by: product_owner_pending_final_review

## Scope

This document is the product acceptance baseline for the H5 VIP modal and the
payment redirect path. It is intended to unblock P4-09 implementation.

Canonical machine-readable config:

- `config/h05_vip_h5_approval.json`

Related implementation references:

- `app/api/payments.py`
- `.env.example`
- `docs/product/business-flow.html`

## Approved VIP Offer

| Field | Approved value |
|---|---|
| Product id | `vip` |
| Price | `$4.99` |
| API amount | `499` cents |
| Currency | `USD` |
| Fulfillment | Stripe `checkout.session.completed` upgrades `users.vip_level` by 1 |

## Approved Modal Copy

Title: Upgrade to VIP

Subtitle: Unlock deeper replies and priority care for this chat.

Body:

- Get a warmer, more complete conversation experience.
- Your payment is processed securely by Stripe.
- You can close this window and continue chatting anytime.

Benefits:

- Priority response experience
- More complete character replies
- VIP profile badge after payment

Primary CTA: Continue to secure payment  
Secondary CTA: Maybe later  
Trust note: Secure checkout powered by Stripe.

Age gate note: VIP purchase is available only after age verification.  
Minor block message: VIP purchase is not available for this account.  
Error message: Payment could not be started. Please try again later.

## Approved Payment Path

1. H5 opens the VIP modal from a VIP entry, conversion CTA, or premium feature
   gate.
2. User taps the primary CTA.
3. H5 calls:

```http
POST /api/v1/orders
Content-Type: application/json

{
  "user_id": "{current_user_id}",
  "product_id": "vip",
  "amount": 499,
  "currency": "USD"
}
```

4. API returns:

```json
{
  "order_id": "{uuid}",
  "checkout_url": "{stripe_checkout_url}",
  "status": "pending"
}
```

5. H5 opens `checkout_url` in the current webview or browser tab.
6. Stripe redirects to:

| Outcome | URL |
|---|---|
| Success | `https://hugme2.com/payment/success?session_id={CHECKOUT_SESSION_ID}` |
| Cancel | `https://hugme2.com/payment/cancel` |

7. The success page shows: Payment complete / Your VIP upgrade is being
   activated. You can return to chat now. / Back to chat.
8. The cancel page shows: Payment canceled / No charge was made. You can try
   again whenever you are ready. / Back to chat.

## Product Acceptance Checklist

- [x] VIP modal title, subtitle, body, benefits, CTA, secondary CTA, trust note,
  age gate note, blocked-minor message, and error message are approved.
- [x] CTA calls `POST /api/v1/orders` with `product_id=vip`, `amount=499`, and
  `currency=USD`.
- [x] H5 opens the returned `checkout_url`; it does not construct Stripe URLs in
  frontend code.
- [x] Success and cancel redirects match `.env.example` defaults.
- [x] Age-unverified and suspected-minor accounts are blocked before checkout by
  the existing payments API.
- [x] Product acceptance for H-05 is complete and ready for P4-09.

## Change Control

Any later change to price, copy, CTA wording, product id, redirect URL, or
blocked-state messaging should update `config/h05_vip_h5_approval.json`, this
document, and the validation test in the same PR.
