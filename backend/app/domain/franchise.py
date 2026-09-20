"""Porting 1:1 di ``src/server/franchise.ts`` — funzioni pure, zero I/O.

Ogni funzione cita il corrispondente simbolo TS.
"""

from __future__ import annotations

from app.shared.models import FranchiseInfo, FranchiseKind, ListEntry, MediaLite

SEEN: frozenset[str] = frozenset(["COMPLETED", "CURRENT", "REPEATING", "PAUSED"])


def analyze_franchises(
    candidates: list[MediaLite],
    list_map: dict[int, ListEntry],
) -> dict[int, FranchiseInfo]:
    """``analyzeFranchises``: classifica ogni candidato contro la lista via catene PREQUEL.

    Pure: relations solo dal pool; i prequel fuori dal pool terminano la catena
    (il loro id è comunque noto e fetchabile a parte).
    """
    prequel_of: dict[int, int | None] = {}
    for m in candidates:
        # ponytail: multiple prequels (compilations) — first edge wins
        prequel = next((r for r in m.relations if r.relationType == "PREQUEL"), None)
        prequel_of[m.id] = prequel.id if prequel is not None else None

    # memoized predecessor chains (root-most first); no hop cap — the memo makes
    # long chains linear overall, and the graph is finite (pool edges only)
    chain_memo: dict[int, list[int]] = {}

    def chain_of(id_: int) -> list[int]:
        memo = chain_memo.get(id_)
        if memo is not None:  # ATTN: [] è "truthy" in TS → qui `is not None`, non `if memo`
            return memo
        chain: list[int] = []
        visited = {id_}
        cur = id_
        while True:
            p = prequel_of.get(cur)
            if p is None or p in visited:
                break  # end of chain / cycle guard
            upstream = chain_memo.get(p)
            # a PREQUEL cycle would inject `id` into its own chain — skip memoized
            # chains that contain us (the normal branch below already truncates on visited)
            if upstream is not None and id_ not in upstream:
                # p + upstream's predecessors, predecessor-first like the loop below
                chain.extend([p, *reversed(upstream)])
                break
            visited.add(p)
            chain.append(p)
            cur = p
        chain.reverse()  # built predecessor-first → canonical root-most first
        chain_memo[id_] = chain
        return chain

    info: dict[int, FranchiseInfo] = {}
    for m in candidates:
        chain = chain_of(m.id)

        dropped_id = next((i for i in chain if list_map.get(i) is not None and list_map[i].status == "DROPPED"), None)
        first_unseen = next(
            (
                i
                for i in chain
                if (e := list_map.get(i)) is None or e.status == "PLANNING" or e.status not in SEEN
            ),
            None,
        )

        kind: FranchiseKind
        entry_point_id: int | None = None
        if dropped_id is not None:
            kind = "EXCLUDED"
        elif len(chain) == 0:
            kind = "STANDALONE"
        elif first_unseen is None:
            kind = "NEXT_STEP"
        else:
            kind = "ENTRY_POINT"
            entry_point_id = first_unseen
        info[m.id] = FranchiseInfo(
            kind=kind,
            # canonical root: min id so cyclic clusters collapse into one group
            rootId=min([m.id, *chain]),
            entryPointId=entry_point_id,
            droppedId=dropped_id,
        )
    return info


def is_spin_off(m: MediaLite) -> bool:
    """``isSpinOff``: spin-off / side-story (badge informativo solo)."""
    return any(r.relationType == "SPIN_OFF" or r.relationType == "SIDE_STORY" for r in m.relations)
