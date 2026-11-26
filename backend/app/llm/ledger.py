"""Budget ledger (DESIGN.md 11, 18.5). Integrity is an invariant, never a setting.

Rows are append-only (a database trigger rejects UPDATE and DELETE). A paid call:

1. ``reserve``: under one PostgreSQL advisory lock, closes stale reservations, then refuses with
   ``BudgetExhausted`` when no monthly cap is set, or when month-to-date spend plus open
   reservations plus this estimate would pass the monthly cap or the per-run cap; otherwise writes
   a ``reservation`` row. The lock serialises every reservation, so concurrent callers cannot
   overshoot a cap.
2. ``reconcile`` writes a ``reconciliation`` row with the reported cost; ``release`` writes a
   ``release`` row (amount 0) when nothing was spent. A unique index closes a reservation once.
3. A reservation still open after ``budget.reservation_stale_minutes`` is closed by a
   reconciliation charged at its full estimate (the call's real cost is unknown, so the bound holds).

Amounts are integer micros (``app.llm.money``); the owner's caps are entered in minor units and
converted to micros for every comparison, and the spend summary converts back only for display.

Billed spend and estimated subscription (CLI) spend are kept apart: unbilled rows never count
against a cap and are reported separately. Months run in the owner's time zone
(``general.timezone``).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import Select, and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core import audit
from app.core.clock import Clock, SystemClock
from app.core.db import get_sessionmaker
from app.core.events import publish
from app.core.settings import service as settings_service
from app.llm.client import BudgetExhausted
from app.llm.money import micros_to_minor, minor_to_micros
from app.models.platform import AuditEvent, LedgerEntry, LedgerKind

LEDGER_LOCK_KEY = 0x4E43_4C44  # "NCLD": one advisory lock for every reservation
SYSTEM_ACTOR = "system"


@dataclass(frozen=True)
class Reservation:
    id: uuid.UUID
    amount_micros: int
    currency: str
    billed: bool
    stage: str
    provider: str
    model: str
    run_id: uuid.UUID | None


class SpendBucket(BaseModel):
    key: str
    billed_minor: int = 0
    unbilled_minor: int = 0
    calls: int = 0


class SpendDay(BaseModel):
    day: date
    billed_minor: int = 0
    unbilled_minor: int = 0


class SpendSummary(BaseModel):
    month: str
    timezone: str
    currency: str
    cap_minor: int | None
    per_run_cap_minor: int | None
    warning_percent: int
    month_to_date_minor: int
    reserved_minor: int
    estimated_unbilled_minor: int
    remaining_minor: int | None
    warning_reached: bool
    by_stage: list[SpendBucket]
    by_model: list[SpendBucket]
    by_run: list[SpendBucket]
    daily: list[SpendDay]


def month_bounds(now: datetime, tz_name: str, month: str | None = None) -> tuple[datetime, datetime, str]:
    """UTC bounds of the owner's calendar month containing ``now`` (or ``month`` = 'YYYY-MM')."""
    tz = ZoneInfo(tz_name)
    if month:
        year, mon = (int(p) for p in month.split("-"))
    else:
        local = now.astimezone(tz)
        year, mon = local.year, local.month
    start = datetime(year, mon, 1, tzinfo=tz)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=tz)
    return start, end, f"{year:04d}-{mon:02d}"


def _open_reservations_query() -> Select[tuple[LedgerEntry]]:
    closing = aliased(LedgerEntry)
    return (select(LedgerEntry)
            .outerjoin(closing, closing.reservation_id == LedgerEntry.id)
            .where(LedgerEntry.kind == LedgerKind.reservation, closing.id.is_(None)))


class Ledger:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession] | None = None,
                 clock: Clock | None = None) -> None:
        self._sessionmaker = sessionmaker
        self.clock = clock or SystemClock()

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker or get_sessionmaker()

    # ----- reserve --------------------------------------------------------------------------

    async def reserve(self, *, stage: str, provider: str, model: str, amount_micros: int, billed: bool,
                      run_id: uuid.UUID | None = None, agent_task_id: uuid.UUID | None = None) -> Reservation:
        if amount_micros < 0:
            raise ValueError("a reservation cannot be negative")
        refusal: BudgetExhausted | None = None
        async with self.sessionmaker() as session, session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LEDGER_LOCK_KEY})
            values = await settings_service.values(session)
            now = self.clock.now()
            await self._expire_stale(session, now, values["budget.reservation_stale_minutes"])
            currency = values["budget.currency"]
            if billed:
                refusal = await self._check_caps(session, values, now, amount_micros, run_id)
            if refusal is None:
                row = LedgerEntry(kind=LedgerKind.reservation, amount_micros=amount_micros, currency=currency,
                                  billed=billed, stage=stage, provider=provider, model=model, run_id=run_id,
                                  agent_task_id=agent_task_id)
                session.add(row)
                await session.flush()
                await publish(session, "spend.updated", {"stage": stage})
                return Reservation(id=row.id, amount_micros=amount_micros, currency=currency, billed=billed,
                                   stage=stage, provider=provider, model=model, run_id=run_id)
        await self._tell_owner_once(refusal)
        raise refusal

    async def _check_caps(self, session: AsyncSession, values: dict, now: datetime, amount: int,
                          run_id: uuid.UUID | None) -> BudgetExhausted | None:
        currency = values["budget.currency"]
        cap_minor = values["budget.monthly_cap_minor"]
        if cap_minor is None:
            return BudgetExhausted("no_cap", needed_micros=amount, available_micros=None, currency=currency)
        cap = minor_to_micros(cap_minor)
        start, end, _ = month_bounds(now, values["general.timezone"])
        committed = await self._committed(session, start, end)
        if committed + amount > cap:
            return BudgetExhausted("monthly", needed_micros=amount, available_micros=max(cap - committed, 0),
                                   currency=currency)
        run_cap_minor = values["budget.per_run_cap_minor"]
        if run_id is not None and run_cap_minor is not None:
            run_cap = minor_to_micros(run_cap_minor)
            used = await self._run_committed(session, run_id)
            if used + amount > run_cap:
                return BudgetExhausted("per_run", needed_micros=amount, available_micros=max(run_cap - used, 0),
                                       currency=currency)
        return None

    async def _committed(self, session: AsyncSession, start: datetime, end: datetime) -> int:
        spent = await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_micros), 0)).where(
                LedgerEntry.kind == LedgerKind.reconciliation, LedgerEntry.billed.is_(True),
                LedgerEntry.created_at >= start, LedgerEntry.created_at < end))
        open_q = _open_reservations_query().where(LedgerEntry.billed.is_(True)).subquery()
        reserved = await session.scalar(select(func.coalesce(func.sum(open_q.c.amount_micros), 0)))
        return int(spent or 0) + int(reserved or 0)

    async def _run_committed(self, session: AsyncSession, run_id: uuid.UUID) -> int:
        spent = await session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount_micros), 0)).where(
                LedgerEntry.kind == LedgerKind.reconciliation, LedgerEntry.billed.is_(True),
                LedgerEntry.run_id == run_id))
        open_q = _open_reservations_query().where(LedgerEntry.billed.is_(True), LedgerEntry.run_id == run_id).subquery()
        reserved = await session.scalar(select(func.coalesce(func.sum(open_q.c.amount_micros), 0)))
        return int(spent or 0) + int(reserved or 0)

    async def _expire_stale(self, session: AsyncSession, now: datetime, stale_minutes: int) -> int:
        cutoff = now - timedelta(minutes=stale_minutes)
        stale = (await session.scalars(_open_reservations_query().where(LedgerEntry.created_at < cutoff))).all()
        for res in stale:
            session.add(LedgerEntry(kind=LedgerKind.reconciliation, reservation_id=res.id,
                                    amount_micros=res.amount_micros, currency=res.currency, billed=res.billed,
                                    stage=res.stage, provider=res.provider, model=res.model, run_id=res.run_id,
                                    agent_task_id=res.agent_task_id,
                                    note="expired: charged at the reserved estimate (real cost unknown)"))
        if stale:
            await session.flush()
        return len(stale)

    async def expire_stale(self) -> int:
        """Close stale reservations now (also done before every reservation)."""
        async with self.sessionmaker() as session, session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LEDGER_LOCK_KEY})
            minutes = await settings_service.get_value(session, "budget.reservation_stale_minutes")
            return await self._expire_stale(session, self.clock.now(), minutes)

    # ----- close ----------------------------------------------------------------------------

    async def reconcile(self, reservation: Reservation, *, cost_micros: int, input_tokens: int, output_tokens: int,
                        note: str | None = None) -> None:
        await self._close(reservation, LedgerKind.reconciliation, cost_micros, input_tokens, output_tokens, note)

    async def release(self, reservation: Reservation, *, note: str | None = None) -> None:
        await self._close(reservation, LedgerKind.release, 0, None, None, note)

    async def _close(self, res: Reservation, kind: LedgerKind, amount: int, input_tokens: int | None,
                     output_tokens: int | None, note: str | None) -> None:
        async with self.sessionmaker() as session, session.begin():
            session.add(LedgerEntry(kind=kind, reservation_id=res.id, amount_micros=max(amount, 0),
                                    currency=res.currency, billed=res.billed, stage=res.stage,
                                    provider=res.provider, model=res.model, run_id=res.run_id,
                                    input_tokens=input_tokens, output_tokens=output_tokens, note=note))
            await session.flush()
            await publish(session, "spend.updated", {"stage": res.stage})
            if res.billed and amount > 0:
                await self._warn_once(session)

    # ----- owner notices --------------------------------------------------------------------

    async def _already_told(self, session: AsyncSession, action: str, since: datetime) -> bool:
        return bool(await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == action, AuditEvent.created_at >= since)))

    async def _warn_once(self, session: AsyncSession) -> None:
        values = await settings_service.values(session)
        cap_minor = values["budget.monthly_cap_minor"]
        if not cap_minor:
            return
        cap = minor_to_micros(cap_minor)
        start, end, month = month_bounds(self.clock.now(), values["general.timezone"])
        spent = await self._spent(session, start, end)
        if spent * 100 < values["budget.warning_percent"] * cap or await self._already_told(
                session, "budget.warning", start):
            return
        detail = {"month": month, "spent_minor": micros_to_minor(spent), "cap_minor": cap_minor,
                  "percent": values["budget.warning_percent"]}
        await audit.record(session, actor=SYSTEM_ACTOR, action="budget.warning", subject_type="budget",
                           subject_id=month, detail=detail)
        await publish(session, "budget.warning", detail)

    async def _tell_owner_once(self, refusal: BudgetExhausted | None) -> None:
        if refusal is None:
            return
        async with self.sessionmaker() as session, session.begin():
            tz = await settings_service.get_value(session, "general.timezone")
            start, _, month = month_bounds(self.clock.now(), tz)
            if await self._already_told(session, f"budget.exhausted.{refusal.scope}", start):
                return
            detail = {"month": month, "scope": refusal.scope}
            await audit.record(session, actor=SYSTEM_ACTOR, action=f"budget.exhausted.{refusal.scope}",
                               subject_type="budget", subject_id=month, detail=detail)
            await publish(session, "budget.exhausted", detail)

    # ----- reporting ------------------------------------------------------------------------

    async def _spent(self, session: AsyncSession, start: datetime, end: datetime) -> int:
        return int(await session.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_micros), 0)).where(
            LedgerEntry.kind == LedgerKind.reconciliation, LedgerEntry.billed.is_(True),
            LedgerEntry.created_at >= start, LedgerEntry.created_at < end)) or 0)

    async def summary(self, session: AsyncSession, month: str | None = None) -> SpendSummary:
        values = await settings_service.values(session)
        tz_name = values["general.timezone"]
        tz = ZoneInfo(tz_name)
        start, end, label = month_bounds(self.clock.now(), tz_name, month)
        rows = (await session.scalars(select(LedgerEntry).where(and_(
            LedgerEntry.kind == LedgerKind.reconciliation, LedgerEntry.created_at >= start,
            LedgerEntry.created_at < end)))).all()
        open_rows = (await session.scalars(_open_reservations_query())).all()
        stage: dict[str, SpendBucket] = {}
        model: dict[str, SpendBucket] = {}
        run: dict[str, SpendBucket] = {}
        daily: dict[date, SpendDay] = defaultdict(lambda: SpendDay(day=date.min))
        billed_total = unbilled_total = 0
        for row in rows:
            for key, table in ((row.stage, stage), (f"{row.provider}/{row.model}", model),
                               (str(row.run_id) if row.run_id else "none", run)):
                bucket = table.setdefault(key, SpendBucket(key=key))
                bucket.calls += 1
                if row.billed:
                    bucket.billed_minor += row.amount_micros
                else:
                    bucket.unbilled_minor += row.amount_micros
            day = row.created_at.astimezone(tz).date()
            entry = daily[day]
            entry.day = day
            if row.billed:
                entry.billed_minor += row.amount_micros
                billed_total += row.amount_micros
            else:
                entry.unbilled_minor += row.amount_micros
                unbilled_total += row.amount_micros
        reserved = sum(r.amount_micros for r in open_rows if r.billed)
        cap_minor = values["budget.monthly_cap_minor"]
        cap = None if cap_minor is None else minor_to_micros(cap_minor)
        # Buckets were summed in micros; convert once, for display.
        for item in [*stage.values(), *model.values(), *run.values(), *daily.values()]:
            item.billed_minor, item.unbilled_minor = micros_to_minor(item.billed_minor), micros_to_minor(
                item.unbilled_minor)

        def ordered(table: dict[str, SpendBucket]) -> list[SpendBucket]:
            return sorted(table.values(), key=lambda b: (-(b.billed_minor + b.unbilled_minor), b.key))

        return SpendSummary(
            month=label, timezone=tz_name, currency=values["budget.currency"], cap_minor=cap_minor,
            per_run_cap_minor=values["budget.per_run_cap_minor"], warning_percent=values["budget.warning_percent"],
            month_to_date_minor=micros_to_minor(billed_total), reserved_minor=micros_to_minor(reserved),
            estimated_unbilled_minor=micros_to_minor(unbilled_total),
            remaining_minor=None if cap is None else micros_to_minor(max(cap - billed_total - reserved, 0)),
            warning_reached=bool(cap) and billed_total * 100 >= values["budget.warning_percent"] * (cap or 0),
            by_stage=ordered(stage), by_model=ordered(model), by_run=ordered(run)[:50],
            daily=sorted(daily.values(), key=lambda d: d.day),
        )
