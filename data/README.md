# Aircraft Database

This directory contains the aircraft database used to enrich ADS-B data with aircraft information.

## Source

The aircraft database (`aircraft.csv`) is sourced from the [tar1090-db](https://github.com/wiedehopf/tar1090-db) project, which maintains the database originally from [Mictronics Aircraft Database](https://www.mictronics.de/aircraft-database/).

## Database Format

The CSV file contains the following fields (semicolon-delimited):

1. **ICAO24 Address** - 6-character hexadecimal identifier (e.g., `004002`)
2. **Registration** - Aircraft tail number (e.g., `N12345`, `G-ABCD`)
3. **Type Code** - ICAO aircraft type code (e.g., `B738`, `A320`)
4. **Unknown Field** - Reserved field
5. **Type Description** - Full aircraft type name (e.g., `BOEING 737-800`)
6. **Additional Fields** - Reserved for future use

## Downloading the Database

The aircraft database is **not included** in the repository. Download it using the CLI command:

```bash
uv run adsb download
```

It is written to a per-user data directory (`~/.local/share/adsb-map/aircraft.csv` on
Linux), **not** to this directory, so it is found regardless of where `adsb start backend` runs
from. Override the location with `--aircraft-db PATH` (pass the same path to `adsb start backend`).

This will:
1. Download the compressed database (~9MB) from tar1090-db
2. Extract it to the location above (~32MB)
3. Display statistics about the downloaded records

## Updating the Database

To update to the latest version, simply run the download command again:

```bash
uv run adsb download
```

The command will overwrite the existing database with the latest version.

## Database Statistics

- **Records**: ~616,000+ aircraft
- **File Size**: ~32 MB (uncompressed), ~8.4 MB (compressed)
- **Update Frequency**: The upstream database is updated regularly

## License

The aircraft database is maintained by the community and aggregated from various public sources. When using this data, please respect the original data sources and their terms of use.
