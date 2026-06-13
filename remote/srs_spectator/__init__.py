"""SRS Spectator — cloud-based game watching service.

Channel B of the zero-touch architecture:
    extractor (hotspot) → relay :8000 → srs_spectator :8003 → game server

Does NOT touch the existing VPN relay.
"""
