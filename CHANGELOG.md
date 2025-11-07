# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2024-11-07

### Added
- Initial release of adsb-map
- ADS-B decoder using pyModeS library
- FastAPI REST API server with jet1090-compatible endpoints
- React frontend with Mapbox GL for real-time aircraft visualization
- Aircraft database integration with 566,000+ aircraft records from tar1090-db
- SQLite storage for aircraft state, positions, and metadata
- CLI tools for server management:
  - `adsb serve` - Start API server with network data source support
  - `adsb download` - Download aircraft database
  - `adsb init-db` - Initialize database tables
  - `adsb decode` - Decode single ADS-B messages
  - `adsb cleanup` - Remove stale aircraft
  - `adsb db-size` - Display database statistics
- Network client supporting Beast and raw formats (dump1090, readsb)
- Automatic aircraft enrichment with registration and type information
- Position decoding with CPR (Compact Position Reporting)
- Support for multiple ADS-B message types (DF4, DF5, DF17, DF20, DF21)
- Comprehensive test suite with 47 tests
- Pre-commit hooks with Ruff linting and formatting
- GitHub Actions CI workflow testing Python 3.12 and 3.13
- Tox configuration for multi-version testing
- Complete API documentation in README

