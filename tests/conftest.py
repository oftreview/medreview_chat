"""
tests/conftest.py — Shared pytest fixtures for Closi AI test suite.

Ensures the project root is in sys.path so `from src.*` imports work.
"""
import sys
import os

# Add project root to path so `from src.core.security import ...` works
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
