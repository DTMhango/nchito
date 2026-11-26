"""Budget ledger: caps, concurrency, expiry, reconciliation, notices, billed vs unbilled."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.clock import FakeClock
from app.core.db import get_sessionmaker
from app.llm.client import BudgetExhausted
from app.llm.ledger import Ledger
from app.llm.money import MICROS_PER_MINOR as M
from app.models.platform import AuditEvent, LedgerEntry, LedgerKind
from tests.llm.conftest import make_run, set_settings


async def reserve(ledger: Ledger, amount: int, *, billed: bool = True, run_id: uuid.UUID | None = None):
    """``amount`` is in minor units, converted to micros."""
    return await ledger.reserve(stage="score", provider="anthropic", model="claude-haiku-5-5",
                                amount_micros=amount * M, billed=billed, run_id=run_id)


async def test_no_monthly_cap_means_paid_work_stays_off() -> None:
    with pytest.raises(BudgetExhausted) as exc:
        await reserve(Ledger(), 1)
    assert exc.value.scope == "no_cap"


async def test_unbilled_calls_need_no_cap_and_never_count_against_it() -> None:
    ledger = Ledger()
    res = await reserve(ledger, 500, billed=False)
    await ledger.reconcile(res, cost_micros=500 * M, input_tokens=10, output_tokens=10)
    await set_settings(budget__monthly_cap_minor=100)
    await reserve(ledger, 100)  # the full cap is still free
    async with get_sessionmaker()() as s:
        summary = await ledger.summary(s)
    assert summary.estimated_unbilled_minor == 500 and summary.month_to_date_minor == 0
    assert summary.reserved_minor == 100


async def test_monthly_cap_counts_spend_plus_open_reservations() -> None:
    await set_settings(budget__monthly_cap_minor=100)
    ledger = Ledger()
    first = await reserve(ledger, 60)
    with pytest.raises(BudgetExhausted) as exc:
        await reserve(ledger, 50)
    assert exc.value.scope == "monthly" and exc.value.available_micros == 40 * M
    await ledger.reconcile(first, cost_micros=20 * M, input_tokens=100, output_tokens=10)
    await reserve(ledger, 80)  # 20 spent + 80 = cap exactly


async def test_per_run_cap() -> None:
    await set_settings(budget__monthly_cap_minor=1000, budget__per_run_cap_minor=30)
    ledger, run_a, run_b = Ledger(), await make_run(), await make_run()
    await reserve(ledger, 20, run_id=run_a)
    with pytest.raises(BudgetExhausted) as exc:
        await reserve(ledger, 20, run_id=run_a)
    assert exc.value.scope == "per_run"
    await reserve(ledger, 20, run_id=run_b)


async def test_concurrent_reservations_never_overshoot_the_cap() -> None:
    await set_settings(budget__monthly_cap_minor=100)
    ledger = Ledger()
    results = await asyncio.gather(*(reserve(ledger, 7) for _ in range(40)), return_exceptions=True)
    granted = [r for r in results if not isinstance(r, Exception)]
    refused = [r for r in results if isinstance(r, BudgetExhausted)]
    assert len(granted) == 14 and len(refused) == 26  # 14 * 7 = 98 <= 100 < 105
    async with get_sessionmaker()() as s:
        total = await s.scalar(select(func.sum(LedgerEntry.amount_micros)).where(
            LedgerEntry.kind == LedgerKind.reservation))
    assert total == 98 * M


async def test_stale_reservations_expire_charged_at_estimate() -> None:
    await set_settings(budget__monthly_cap_minor=100, budget__reservation_stale_minutes=30)
    clock = FakeClock(datetime.now(UTC))
    ledger = Ledger(clock=clock)
    await reserve(ledger, 70)
    clock.advance(minutes=31)
    assert await ledger.expire_stale() == 1
    async with get_sessionmaker()() as s:
        summary = await ledger.summary(s)
        closing = await s.scalar(select(LedgerEntry).where(LedgerEntry.kind == LedgerKind.reconciliation))
    assert summary.reserved_minor == 0 and summary.month_to_date_minor == 70
    assert closing is not None and "expired" in (closing.note or "")


async def test_stale_reservation_is_closed_before_the_next_reservation() -> None:
    await set_settings(budget__monthly_cap_minor=100, budget__reservation_stale_minutes=10)
    clock = FakeClock(datetime.now(UTC))
    ledger = Ledger(clock=clock)
    await reserve(ledger, 50)
    clock.advance(minutes=11)
    await reserve(ledger, 50)
    async with get_sessionmaker()() as s:
        summary = await ledger.summary(s)
    assert (summary.month_to_date_minor, summary.reserved_minor) == (50, 50)


async def test_a_reservation_closes_once_and_rows_are_append_only() -> None:
    await set_settings(budget__monthly_cap_minor=100)
    ledger = Ledger()
    res = await reserve(ledger, 10)
    await ledger.reconcile(res, cost_micros=4 * M, input_tokens=1, output_tokens=1)
    with pytest.raises(IntegrityError):
        await ledger.release(res)
    async with get_sessionmaker()() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text("UPDATE ledger_entry SET amount_micros = 0"))
        await s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text("DELETE FROM ledger_entry"))


async def test_warning_and_exhaustion_are_told_once_per_month() -> None:
    await set_settings(budget__monthly_cap_minor=100, budget__warning_percent=50)
    ledger = Ledger()
    for _ in range(3):
        res = await reserve(ledger, 30)
        await ledger.reconcile(res, cost_micros=30 * M, input_tokens=1, output_tokens=1)
    for _ in range(2):
        with pytest.raises(BudgetExhausted):
            await reserve(ledger, 30)
    async with get_sessionmaker()() as s:
        actions = (await s.scalars(select(AuditEvent.action).where(AuditEvent.action.like("budget.%")))).all()
        summary = await ledger.summary(s)
    assert sorted(actions) == ["budget.exhausted.monthly", "budget.warning"]
    assert summary.warning_reached and summary.remaining_minor == 10


async def test_summary_groups_by_stage_model_run_and_day() -> None:
    await set_settings(budget__monthly_cap_minor=1000)
    ledger = Ledger()
    for stage, model, cost in (("score", "claude-haiku-5-5", 3), ("tailor", "claude-sonnet-5-5", 40),
                               ("score", "claude-haiku-5-5", 2)):
        res = await ledger.reserve(stage=stage, provider="anthropic", model=model, amount_micros=50 * M, billed=True)
        await ledger.reconcile(res, cost_micros=cost * M, input_tokens=1, output_tokens=1)
    async with get_sessionmaker()() as s:
        summary = await ledger.summary(s)
    assert [(b.key, b.billed_minor, b.calls) for b in summary.by_stage] == [("tailor", 40, 1), ("score", 5, 2)]
    assert summary.by_model[0].key == "anthropic/claude-sonnet-5-5"
    assert summary.by_run[0].key == "none" and sum(d.billed_minor for d in summary.daily) == 45


async def test_months_reset_in_owner_timezone() -> None:
    await set_settings(budget__monthly_cap_minor=1000, general__timezone="Pacific/Kiritimati")  # UTC+14
    ledger = Ledger()
    res = await reserve(ledger, 5)
    await ledger.reconcile(res, cost_micros=5 * M, input_tokens=1, output_tokens=1)
    async with get_sessionmaker()() as s:
        now_local = datetime.now(UTC) + timedelta(hours=14)
        summary = await ledger.summary(s)
        other = await ledger.summary(s, "2001-01")
    assert summary.month == now_local.strftime("%Y-%m") and summary.month_to_date_minor == 5
    assert other.month_to_date_minor == 0
