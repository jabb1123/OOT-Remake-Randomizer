"""Choose which Hyrule Field segments play after the first Kaepora talk, to find the time trigger.

The Kaepora entry of `Goto_HyruleCastle` (`Goto_HyruleCastle_Kaepora_00`) runs three transitions in
order: `Dm_HrlField_0000`, `Dm_HrlField_0005`, and `Dm_HrlField_0010`. Each segment outside
`KAEPORA_SEGMENTS_TO_PLAY` is unlinked from that chain with `unlink_transition`, so the rest of the
flow still runs. The segment's own flow stays in the NUP, but it is no longer reached from this entry.
"""

from .cutscene_skips import unlink_transition

KAEPORA_FLOW = "Goto_HyruleCastle.bfevfl.zs"
KAEPORA_ENTRY_POINT = "Goto_HyruleCastle_Kaepora_00"
KAEPORA_SEGMENTS = ("Dm_HrlField_0000", "Dm_HrlField_0005", "Dm_HrlField_0010")

# Segments that still play. Change this set to test one segment at a time.
KAEPORA_SEGMENTS_TO_PLAY = frozenset({})


def isolate_kaepora_segments(data: bytes, play: frozenset = KAEPORA_SEGMENTS_TO_PLAY) -> bytes:
    """Unlink every Kaepora segment that is not in `play` from the Kaepora entry chain."""
    for segment in KAEPORA_SEGMENTS:
        if segment not in play:
            data = unlink_transition(data, KAEPORA_ENTRY_POINT, segment)
    return data
