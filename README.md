# ADS-B Decoder and REST API
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/jbencina/adsb/actions/workflows/ci.yml/badge.svg)](https://github.com/jbencina/adsb/actions/workflows/ci.yml)

ADS-B decoder and REST API server using [pyModeS](https://github.com/junzis/pyModeS) for decoding Mode-S and ADS-B messages. This application mirrors the functionality of [jet1090](https://github.com/xoolive/rs1090/) with a Python-based solution 
that provides the same REST API interface.

![Map interface demo](docs/map.png)


## Quickstart
Install and start backend. Update `localhost` to point to your SDR along with its lat lon coordinates.

```bash
uv sync
uv run adsb serve --host 0.0.0.0 --port 8000 --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
```

Install and start the React frontend.
```bash
cd frontend

# Copy environment template and configure
cp .env.example .env
# Edit .env and set:
# - VITE_API_URL to your API server URL (e.g., http://localhost:8000)
# - VITE_MAPBOX_TOKEN to your MapBox token (get from https://www.mapbox.com/)

bun install
bun run dev
```

Visit http://localhost:3000/

## Features

- **pyModeS Integration**: Decode ADS-B messages using the pyModeS library
- **Aircraft Database**: Automatic enrichment with aircraft registration and type information
- **REST API**: FastAPI-based REST API compatible with jet1090 endpoints
- **SQLite Storage**: Persistent storage of aircraft data and trajectories
- **Interactive Map**: React-based frontend with Mapbox GL for real-time aircraft visualization

## Installation

### Option 1: PyPI Installation (Backend Only)

Install just the Python backend and CLI tools:

```bash
pip install adsb-map

# Download the aircraft database (required for aircraft info enrichment)
adsb download

# Start the server
adsb serve --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
```

**Note**: The PyPI package includes only the Python backend (API server, decoder, CLI). For the full web interface with interactive map, use Option 2.

### Option 2: Full Installation from Source (Backend + Frontend)

For the complete experience with the React-based map interface:

```bash
# Clone the repository
git clone https://github.com/jbencina/adsb.git
cd adsb

# Install backend using uv (or pip)
uv sync

# Install dev dependencies (for testing)
uv sync --dev

# Download the aircraft database (required for aircraft info enrichment)
uv run adsb download
```

### Frontend Setup

```bash
cd frontend

# Copy environment template and configure
cp .env.example .env
# Edit .env and set:
# - VITE_API_URL to your API server URL (e.g., http://localhost:8000)
# - VITE_MAPBOX_TOKEN to your MapBox token (get from https://www.mapbox.com/)

# Install dependencies
bun install

# Start development server
bun run dev
```

## Usage

### Download Aircraft Database

Before starting the server, download the aircraft database to enable aircraft information enrichment:

```bash
# Download the aircraft database (566k+ records, ~9MB download)
uv run adsb download

# The database will be extracted to data/aircraft.csv (~32MB)
```

This is required for automatic aircraft registration and type information lookup.

### Start the API Server

```bash
# Start server with default settings (http://0.0.0.0:8000)
uv run adsb serve

# Start server on custom host and port
uv run adsb serve --host 127.0.0.1 --port 8080

# Start server with custom database path
uv run adsb serve --db-path /path/to/adsb.db

# Connect to a network data source (e.g., dump1090, readsb)
# Note: --lat and --lon are required for accurate position decoding
uv run adsb serve --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0

# Full example with all options
uv run adsb serve --host 0.0.0.0 --port 8000 --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0 --stale-timeout 60
```

### Initialize Database

```bash
# Create database tables
uv run adsb init-db
```

### Decode Single Message

```bash
# Decode a single ADS-B message
uv run adsb decode 8D4840D6202CC371C32CE0576098
```

### Cleanup Stale Aircraft

```bash
# Remove aircraft not seen in the last 60 seconds
uv run adsb cleanup
```

## API Endpoints

The server provides the following endpoints, compatible with jet1090:

### `GET /all`
Returns all currently tracked aircraft state vectors.

**Response**: Array of aircraft objects with full state information

### `GET /icao24`
Returns all ICAO 24-bit addresses currently being tracked.

**Response**: Array of ICAO24 strings

### `GET /track?icao24={icao24}&since={timestamp}`
Returns trajectory track for a specific aircraft.

**Parameters**:
- `icao24` (required): ICAO 24-bit address
- `since` (optional): Unix timestamp to filter positions since

**Response**: Array of track points with timestamp, latitude, longitude, altitude

### `GET /sensors`
Returns information about all sensors/receivers.

**Response**: Array of sensor objects with serial numbers

### Building Custom Frontends

The REST API is fully self-contained and can be used with any frontend framework or application. If you install via PyPI or want to build your own interface:

```bash
# Install and run the backend
pip install adsb-map
adsb serve --host 0.0.0.0 --port 8000

# The API is now available at http://localhost:8000
# Build your own frontend using the endpoints above
```

The included React frontend in this repository serves as a reference implementation. You can:
- Use the API with mobile apps
- Integrate with existing monitoring systems
- Build custom dashboards
- Export data for analysis

## Development

### Running Tests

```bash
# Run all tests with uv
uv run pytest

# Run specific test file
uv run pytest tests/test_api.py

# Run with coverage
uv run pytest --cov=adsb --cov-report=term-missing

# Test across multiple Python versions with tox
uv run tox

# Run specific tox environment
uv run tox -e py312      # Test on Python 3.12
uv run tox -e py313      # Test on Python 3.13
uv run tox -e lint       # Run linting only
uv run tox -e cov        # Run with coverage report
```

### Code Quality & Pre-commit Hooks

This project uses [pre-commit](https://pre-commit.com/) hooks with [Ruff](https://docs.astral.sh/ruff/) for automatic code formatting and linting.

### Publishing to PyPI

This project uses GitHub Actions for automated publishing to PyPI on releases. See [PYPI_PUBLISHING_GUIDE.md](PYPI_PUBLISHING_GUIDE.md) for setup instructions and release workflow.

```bash
# Install pre-commit hooks (one-time setup)
uv run pre-commit install

# Run pre-commit on all files manually
uv run pre-commit run --all-files

# Run Ruff linter manually
uv run ruff check .

# Run Ruff formatter manually
uv run ruff format .
```

The pre-commit hooks will automatically run before each commit to:
- Remove trailing whitespace
- Fix end of file issues
- Check YAML, TOML, and JSON syntax
- Run Ruff linter with automatic fixes
- Format code with Ruff


## Aircraft Database

The application includes an aircraft database with **566,000+ aircraft records** sourced from the [tar1090-db](https://github.com/wiedehopf/tar1090-db) project. When a new aircraft is detected, the decoder automatically looks up and populates:

- **Registration** (tail number, e.g., N12345, G-ABCD)
- **Type Code** (ICAO aircraft type, e.g., B738, A320)
- **Type Description** (full aircraft name, e.g., BOEING 737-800)

This enrichment happens automatically during message decoding and is displayed in the map interface.

**Note**: The aircraft database is not included in the repository. Download it before running the server:

```bash
uv run adsb download
```

See `data/README.md` for more information about the aircraft database.

## Database Schema

### Aircraft Table
Stores current state for each tracked aircraft including position, velocity, identification, telemetry data, and enriched information from the aircraft database (registration, type code).

### AircraftPosition Table
Historical position data for trajectory tracking.

### AircraftMetadata Table
Reception metadata including timing, signal strength (RSSI), and receiver identification.

## Architecture

The application consists of several key components:

1. **Decoder** (`decoder.py`): Uses pyModeS to decode ADS-B messages and update aircraft state
2. **Database** (`database.py`): SQLAlchemy-based persistence layer with SQLite
3. **API** (`api.py`): FastAPI REST endpoints matching jet1090 interface
4. **CLI** (`cli.py`): Click-based command-line interface

## Configuration

Default configuration values:
- Host: `0.0.0.0`
- Port: `8000`
- Database: `adsb.db` (in current directory)
- Stale timeout: `60` seconds

All values can be overridden via CLI options.

## Network Data Sources

The server can connect to existing ADS-B receivers that provide network feeds:

- **dump1090**: Classic ADS-B decoder (port 30005 for Beast format, port 30002 for raw)
- **readsb**: Modern fork of dump1090 (same ports)
- **modesdeco2**: Another popular decoder
- **Any Beast or raw hex format source**

Example connection to dump1090/readsb:
```bash
# Replace with your actual receiver coordinates
uv run adsb serve --source net --connect localhost 30005 beast --lat 40.7 --lon -74.0
```

**Important**: The `--lat` and `--lon` parameters are **required** for accurate position decoding. ADS-B position messages use Compact Position Reporting (CPR) which requires either:
1. A reference position within 180 NM (your receiver location), OR
2. Both odd and even position messages

By providing your receiver's location, the decoder can immediately decode positions with a single message.

The network client runs in a background thread and continuously:
1. Connects to the data source using pyModeS's built-in TCP client
2. Decodes incoming ADS-B messages
3. Updates the database with aircraft state
4. Cleans up stale aircraft every 30 seconds

## Notes

- The decoder currently supports basic ADS-B message types (DF17, DF4, DF5, DF20, DF21)
- Position decoding requires both odd and even messages (CPR decoding)
- Network decoding uses pyModeS's built-in `TcpClient` for reliable Beast/raw format parsing
- The API is fully compatible with the existing frontend application
- Stale aircraft (not seen for 60 seconds by default) are automatically removed

## License

This project is licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later). See the [LICENSE](LICENSE) file for details.
