# Utah Disclosures Scraper

Scrape records from https://disclosures.utah.gov

## Notes

The Utah site seems to have quite a few technical issues.  Some pages of entities (approx 5% at time of writing) fail to return data, consistently giving a 500 error instead.  The only solution to this is to skip them, though that means some entities will not be included in the scrape.

A second issue is that the site periodically seems to go down for stretches of time.  This was encountered several times while testing and doesn't seem to be dependent upon rate limiting.  Most outages were 5-10 minutes long, but one was a period as long as four hours.

## CLI

The CLI consists of several subcommands:

### get-disclosures

Usage: ut_disclosures.py get-disclosures ENTITY_ID YEAR

  Get disclosures by entity_id and year.

  Writes a single CSV per year, using the same fieldnames disclosures.utah.gov
  does.

### get-entities

Usage: ut_disclosures.py get-entities

  Get all entities & writes them to ut_entities.csv.

### get-registrations

Usage: ut_disclosures.py get-registration [OPTIONS] ENTITY_ID

  Get entity registration by id.

  Writes a single JSON file with all information from entity's registration.

### get-all-registrations

Usage: ut_disclosures.py get-all-registrations [OPTIONS]

  Get all entity registrations.

  Writes a single JSON file per entity.
