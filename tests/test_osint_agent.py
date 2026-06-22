"""Tests for OSINT agent query classification and pipeline."""

from __future__ import annotations

import pytest
from agents.osint import _classify_query, _extract_usernames, _extract_domains, _extract_emails


class TestQueryClassification:
    def test_email_query(self):
        cats = _classify_query("check breaches for user@example.com")
        assert "email" in cats
        assert "breach" in cats

    def test_username_query(self):
        cats = _classify_query("scan @johndoe username across social media")
        assert "username" in cats

    def test_domain_recon_query(self):
        cats = _classify_query("recon on example.com subdomains and DNS")
        assert "domain" in cats

    def test_darkweb_query(self):
        cats = _classify_query("search dark web for leaked data")
        assert "darkweb" in cats

    def test_generic_search(self):
        cats = _classify_query("research AI agent frameworks 2026")
        assert "web" in cats

    def test_multi_tool_query(self):
        cats = _classify_query("investigate john@company.com email breach and social media")
        assert "email" in cats
        assert "username" in cats

    def test_breach_query(self):
        cats = _classify_query("check if my email has been leaked in data breaches")
        assert "breach" in cats


class TestExtraction:
    def test_extract_usernames(self):
        assert _extract_usernames("scan @johndoe") == ["johndoe"]
        assert _extract_usernames("check username testuser123") == ["testuser123"]
        assert _extract_usernames("random text") == []

    def test_extract_domains(self):
        domains = _extract_domains("recon on example.com")
        assert "example.com" in domains

    def test_extract_emails(self):
        emails = _extract_emails("check user@example.com and admin@test.org")
        assert "user@example.com" in emails
        assert "admin@test.org" in emails

    def test_extract_no_emails(self):
        assert _extract_emails("no emails here") == []
