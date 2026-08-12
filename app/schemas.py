from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """The one dummy billable endpoint from the brief's 'realistic scope':
    POST /generate -> records usage -> checks quota -> calculates cost."""
    tenant_id: int
    idempotency_key: str = Field(min_length=1, max_length=200)
    usage_type: str = Field(pattern="^(api_call|ai_tokens)$")

    api_call_quantity: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


class GenerateResponse(BaseModel):
    usage_event_id: int
    duplicate: bool
    cost_cents: int
    billing_period: str


class UsageSummaryResponse(BaseModel):
    tenant_id: int
    plan: str
    billing_period: str
    api_calls_used: int
    api_calls_limit: int
    tokens_used: int
    tokens_limit: int
    total_cost_cents: int


class CheckoutRequest(BaseModel):
    tenant_id: int
    target_plan: str = Field(pattern="^(pro)$")
    success_url: str = "https://example.com/billing/success"
    cancel_url: str = "https://example.com/billing/cancel"


class CheckoutResponse(BaseModel):
    checkout_session_id: str
    checkout_url: str
