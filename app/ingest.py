"""Versioned, idempotent ingestion of legislation.

Re-running this pipeline over an unchanged source is a no-op. Re-running it over an amended
source closes the outgoing version and opens a new one, leaving history intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LegalAct, Provision, ProvisionVersion


@dataclass(frozen=True)
class IngestedProvision:
    """One provision as scraped from a source, before it is reconciled against history."""

    celex: str
    act_title: str
    jurisdiction: str
    label: str
    text: str
    in_force_from: date
    source_url: str
    amended_by: str | None = None


def _get_or_create_act(session: Session, record: IngestedProvision) -> LegalAct:
    act = session.scalar(select(LegalAct).where(LegalAct.celex == record.celex))
    if act is None:
        act = LegalAct(
            celex=record.celex,
            title=record.act_title,
            jurisdiction=record.jurisdiction,
        )
        session.add(act)
        session.flush()
    return act


def _get_or_create_provision(session: Session, act: LegalAct, label: str) -> Provision:
    provision = session.scalar(
        select(Provision).where(Provision.act_id == act.id, Provision.label == label)
    )
    if provision is None:
        provision = Provision(act_id=act.id, label=label)
        session.add(provision)
        session.flush()
    return provision


def _current_version(session: Session, provision: Provision) -> ProvisionVersion | None:
    """The version with the latest start date, whether or not it is still open."""
    return session.scalar(
        select(ProvisionVersion)
        .where(ProvisionVersion.provision_id == provision.id)
        .order_by(ProvisionVersion.in_force_from.desc())
        .limit(1)
    )


def ingest(session: Session, records: list[IngestedProvision]) -> int:
    """Reconcile scraped provisions against stored history. Returns versions created.

    Raises:
        ValueError: if a record is backdated before the version already in force. That is
            an upstream bug, and accepting it would produce overlapping intervals — two
            contradictory texts valid on the same date. Fail loudly instead.
    """
    created = 0

    for record in records:
        act = _get_or_create_act(session, record)
        provision = _get_or_create_provision(session, act, record.label)
        latest = _current_version(session, provision)
        incoming_hash = ProvisionVersion.hash_text(record.text)

        if latest is not None:
            if latest.content_hash == incoming_hash:
                continue  # unchanged source: idempotent no-op

            if record.in_force_from < latest.in_force_from:
                raise ValueError(
                    f"backdated amendment for {record.celex} {record.label}: incoming "
                    f"{record.in_force_from} precedes stored {latest.in_force_from}"
                )

            # Half-open interval: the outgoing version ends the day the new one begins.
            latest.in_force_to = record.in_force_from

        session.add(
            ProvisionVersion(
                provision_id=provision.id,
                text=record.text,
                content_hash=incoming_hash,
                in_force_from=record.in_force_from,
                in_force_to=None,
                source_url=record.source_url,
                amended_by=record.amended_by,
            )
        )
        created += 1

    session.commit()
    return created
