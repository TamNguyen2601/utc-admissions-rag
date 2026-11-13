"""Import a complete source-bound catalogue. Stop the backend before running."""
import argparse
import json
from pathlib import Path

from app.core.config import get_settings
from app.db.session import Database
from app.services.recommendation import RecommendationService

MAX_CATALOG_BYTES = 20 * 1024 * 1024


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True, type=Path)
    args = parser.parse_args(argv)
    database = None
    try:
        with args.file.open('rb') as stream:
            content = stream.read(MAX_CATALOG_BYTES + 1)
        if len(content) > MAX_CATALOG_BYTES:
            raise ValueError('CATALOG_TOO_LARGE')
        payload = json.loads(content.decode('utf-8-sig'), object_pairs_hook=unique_keys)
        database = Database(get_settings())
        database.initialize()
        version = RecommendationService(database).import_catalog(payload)
    except Exception:
        # Validation errors may contain private source text/local paths. Never echo them.
        print('Catalogue import failed: check file schema, complete mapping and current permitted UTC sources. Existing catalogue preserved.')
        return 1
    finally:
        if database is not None:
            database.dispose()
    print(f'Catalogue imported atomically. rubric_version={version}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
