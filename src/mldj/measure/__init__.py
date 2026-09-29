"""The three Phase 0 measurements, plus the report that assembles them.

Each module takes Play records from mldj.skips and returns a frozen result dataclass.
None of them touch the network except persistence, which needs Last.fm tags.

A shared rule: an `unknown` outcome must never silently become a denominator. novelty
counts unknown plays (a played track is a played track, however it ended); persistence and
repetition exclude them and report how many they dropped.
"""
