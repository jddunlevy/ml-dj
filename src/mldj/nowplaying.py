"""Parse Spotify currently-playing payloads and interpolate progress between polls.

Ported from cd-player's spotify.ts (parseNowPlaying) and player-state.ts
(interpolateProgress). artUrl is dropped: Phase 0 renders nothing.

interpolate_progress is the skip detector's core primitive. A skip is "the track
changed and the outgoing track's interpolated progress fell well short of its
duration", so the accuracy of that number is the accuracy of the whole measurement.
"""

from dataclasses import dataclass

ENDPOINT = "https://api.spotify.com/v1/me/player/currently-playing?additional_types=episode"


@dataclass(frozen=True)
class NowPlaying:
    kind: str  # 'track' | 'episode' | 'ad'
    id: str
    title: str
    artist: str
    duration_ms: int
    progress_ms: int
    is_playing: bool
    fetched_at: int  # epoch ms when this snapshot was taken


def parse_now_playing(payload: object, fetched_at: int) -> NowPlaying | None:
    """Return a NowPlaying, or None when the payload carries nothing playable."""
    if not isinstance(payload, dict):
        return None
    kind = payload.get("currently_playing_type")
    progress_ms = int(payload.get("progress_ms") or 0)
    is_playing = bool(payload.get("is_playing"))

    if kind == "ad":
        # Ads carry no item. They are logged so the analysis can exclude the transition
        # rather than mistake it for a skip.
        return NowPlaying("ad", "ad", "", "", 0, progress_ms, is_playing, fetched_at)

    item = payload.get("item")
    if not isinstance(item, dict) or kind not in ("track", "episode"):
        return None

    if kind == "track":
        artists = item.get("artists") or []
        artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict))
    else:
        artist = (item.get("show") or {}).get("name", "")

    return NowPlaying(
        kind=kind,
        id=item.get("id") or "",
        title=item.get("name") or "",
        artist=artist,
        duration_ms=int(item.get("duration_ms") or 0),
        progress_ms=progress_ms,
        is_playing=is_playing,
        fetched_at=fetched_at,
    )


def interpolate_progress(np: NowPlaying, now: int) -> int:
    """Where the track would be at `now`, given its last snapshot. Clamped to duration."""
    if not np.is_playing:
        return np.progress_ms
    return min(np.duration_ms, np.progress_ms + (now - np.fetched_at))
