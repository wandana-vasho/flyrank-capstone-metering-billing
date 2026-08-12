from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.stripe_service import verify_and_parse_event, SignatureVerificationError
from app.services.webhook_processor import process_event

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_and_parse_event(payload, sig_header)
    except SignatureVerificationError as exc:
        # Forged or malformed signatures are ALWAYS 400, never 500, and
        # never applied to the database.
        raise HTTPException(status_code=400, detail=f"invalid webhook signature: {exc}")

    try:
        result = process_event(db, event)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"received": True, "processed": result.processed, "detail": result.detail}
