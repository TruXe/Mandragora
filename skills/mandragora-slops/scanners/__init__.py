"""Mandragora slop scanners (Layer A: deterministic static rules).

core.py holds the domain-agnostic registry and CLI. Every scan_<domain>.py
module in this package is discovered automatically and registers its domain
and rules on import. Standard library only.
"""
