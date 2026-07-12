# Security Policy

## Reporting a Vulnerability

auGIT analyzes supply-chain signals and handles GitHub tokens locally. If you
discover a security vulnerability, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, email the maintainer at **adrian.thees@t-online.de** with:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You should receive a response within 7 days. We will work with you to understand
and address the issue before any public disclosure.

## Scope

In scope:

- Credential leakage or unsafe token handling
- SQL injection or unsafe deserialization in the audit database
- Integrity bypass in the append-only audit log
- Remote code execution via collectors or report rendering

Out of scope:

- Findings in third-party repositories analyzed by auGIT
- Social engineering against GitHub, PyPI, or Maven Central

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
