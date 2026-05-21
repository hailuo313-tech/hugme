# P4-09 H5 VIP Modal + Payment Redirect

Task: P4-09  
Acceptance: CTA can redirect to payment checkout

## Scope

P4-09 implements the approved H5 VIP modal from `config/h05_vip_h5_approval.json`
inside `admin/app/h5/chat/page.tsx`.

## User Flow

1. User opens the H5 chat page.
2. User taps the `VIP` entry in the top bar.
3. The approved VIP modal appears with price, benefits, CTA copy, age-gate note,
   blocked-state copy, and Stripe trust note.
4. User taps `Continue to secure payment`.
5. H5 calls:

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

6. H5 opens only the returned `checkout_url` via `window.location.assign`.

The frontend does not construct Stripe URLs. Success and cancel URLs remain owned
by backend Stripe configuration.

## Error Handling

- Non-OK payment responses keep the user inside chat and show a retryable error.
- HTTP 403 responses use the approved blocked-account message.
- Missing `checkout_url` is treated as a payment-start failure.
- The secondary CTA closes the modal unless checkout is already in progress.

## Verification

- `npm exec tsc -- --noEmit --project tsconfig.json`
- `npm run build`
- `node scripts/check-bf-html.js docs/product/business-flow.html`
- `tests/test_p4_09_h5_vip_modal.py` covers the static CTA contract in CI.
