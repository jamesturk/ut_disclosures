#!/usr/bin/env python3

import io
import csv
import json
import time
from pathlib import Path
import requests
import click
from spatula import HtmlPage, HtmlListPage, CSS, XPath, URL
from dataclasses import dataclass, field, asdict

# Data Models ##############


@dataclass
class Person:
    first: str
    middle: str = ""
    last: str = ""
    suffix: str = ""
    title: str = ""
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zipcode: str = ""
    phone: str = ""
    email: str = ""
    occupation: str = ""
    office: str = ""
    district_number: str = ""
    party: str = ""


@dataclass
class Entity:
    id: str
    source: str
    type: str = ""
    name: str = ""
    phone: str = ""
    address1: str = ""
    address2: str = ""
    city: str = ""
    state: str = ""
    zipcode: str = ""
    aka: str = ""
    date_created: str = ""
    ballot_proposition: str = ""
    ballot_position: str = ""
    affiliated_organization: str = ""
    associated_people: list[Person] = field(default_factory=list)


# scrapers ##################


def _fetch_disclosures(entity_id, year):
    EMPTY_MSG = "There are no recorded transactions for this entity in this year."
    url = f"https://disclosures.utah.gov/Search/AdvancedSearch/GenerateReport/{entity_id}?ReportYear={year}"
    resp = requests.get(url)
    if resp.text == EMPTY_MSG:
        return []
    else:
        reader = csv.DictReader(io.StringIO(resp.text))
        return list(reader)


class EntityList(HtmlListPage):
    """
    Pull down the full list of entities via submitting the advanced search query
    with blank values from the UT Secretary of State public data library
    """

    search_url = (
        "https://disclosures.utah.gov/Search/AdvancedSearch/GetEntityReportList"
    )

    source = URL(search_url, method="POST", data={"PageNumber": 1})
    selector = CSS("tbody tr")

    def process_item(self, item):
        entity_link, entity_type, *rest = item.getchildren()
        entity_link = entity_link.getchildren()[0]
        name = entity_link.text_content().strip()
        url = entity_link.get("href")
        entity_id = url.split("/")[-1]
        entity = dict(
            name=name,
            entity_id=entity_id,
            entity_type=entity_type.text_content().strip(),
        )
        return entity

    def get_next_source(self):
        # so Utah's pages just... loop after you reach the end (currently ~147)
        next_page = self.source.data["PageNumber"] + 1
        data = {"PageNumber": next_page}
        return URL(self.search_url, method="POST", data=data)

    def process_error_response(self, error):
        # quite a few pages just error out, we'll note & skip
        print(error, self.source.data)


class EntityFolderDetails(HtmlPage):
    """
    connection from the folder details page to the entity metadata page
    """

    # input is an entity ID

    def get_source_from_input(self):
        return f"https://disclosures.utah.gov/Search/PublicSearch/FolderDetails/{self.input}"

    def process_page(self):
        # metadata is in this iframe
        url = XPath("//iframe[@id='registrationDialogIFrame']/@src").match(self.root)[0]
        return EntityMetadata(self.input, source=url)


class EntityMetadata(HtmlPage):
    """
    pull the entity metadata (statement of organization)
    """

    example_source = "https://disclosures.utah.gov/Registration/EntityDetails/1409777"

    ENTITY_DATA_MAPPING = {
        "Name of Corporation": "name",
        "Name": "name",
        "Name of Political Party": "name",
        "County": "county",
        "Telephone Number": "phone",
        "Street Address": "address1",
        "Suite/PO Box": "address2",
        "City": "city",
        "State": "state",
        "Zip": "zipcode",
        "Also known as": "aka",
        "Date Created": "date_created",
        "First": "first",
        "Middle": "middle",
        "Last": "last",
        "Suffix": "suffix",
        "Title": "title",
        "Email": "email",
        "Occupation": "occupation",
        "Business Address": "address1",
        "Ballot Proposition": "ballot_proposition",
        "Ballot Position": "ballot_position",
        "Name of organization, individual, corporation, association, unit of government, or union that the PIC Represents": "first",
        "Name of organization, individual, corporation, association, unit of government, or union that the PAC Represents": "first",
        "Name of organization affiliated with the PAC": "first",
        "Name of organization affiliated with the PIC": "first",
        "Office": "office",
        "Party": "party",
        "District #": "district_number",
        "County of Election": "county",
        "Organization": "affiliated_organization",
    }

    type_mapping = {
        "Political Issues Commitee Statement of Organization": "Political Issues Committee",
        "Financial Disclosures Registration for Corporation": "Corporation",
        "Political Action Committee Statement of Organization": "Political Action Committee",
        "Candidates & Office Holders Statement of Organization": "Candidates & Office Holders",
        "Financial Disclosures Registration for Political Party": "Political Party",
        "Financial Disclosures Registration for Independent Expenditures": "Independent Expenditures",
        "Financial Disclosures Registration for Electioneering": "Electioneering",
    }

    def process_page(self):
        # carry over fields from directory page
        entity = Entity(id=self.input, source=self.source.url)

        h1 = CSS("h1").match_one(self.root).text_content()
        entity.type = self.type_mapping[h1]

        for fieldset in CSS("fieldset").match(self.root):
            # collect all the data
            data = {}
            for item in CSS("div.dis-cell label").match(fieldset):
                field = self.ENTITY_DATA_MAPPING[item.text_content()]
                data[field] = item.tail.strip()

            # attach it to the object
            legend = CSS("legend").match_one(fieldset).text_content().strip()
            if legend in (
                "Corporate Information",
                "PAC Information",
                "PIC Information",
                "Party Information",
                "Candidate Information",
                "Independent Expenditures Information",
                "Electioneer Information",
            ):
                for k, v in data.items():
                    setattr(entity, k, v)
            elif (
                legend.startswith("Information about")
                or legend.startswith("Personal Campaign Committee")
            ):
                person = Person(**data)
                entity.associated_people.append(person)
            else:
                raise ValueError(f"unknown legend {legend}")

        return entity


# CLI #######################


@click.group()
def cli():
    pass


@cli.command()
def get_entities():
    """
    Get all entities & writes them to ut_entities.csv.
    """
    filename = f"data/ut_entities.csv"
    seen = set()
    with open(filename, "w") as f:
        writer = csv.DictWriter(f, ("entity_id", "entity_type", "name"))
        writer.writeheader()
        for item in EntityList().do_scrape():
            if item["entity_id"] in seen:
                break
            seen.add(item["entity_id"])
            writer.writerow(item)
    print(f"wrote {len(seen)} to {filename}")


def _write_registration_json(entity_id, skip_if_exists=False):
    filename = f"data/ut_registration_{entity_id}.json"
    if skip_if_exists and Path(filename).exists():
        print(f"{filename} already exists")
    else:
        item = list(EntityFolderDetails(entity_id).do_scrape())
        with open(filename, "w") as f:
            json.dump(asdict(item[0]), f)
        print(f"wrote {filename}")
        time.sleep(1)


@cli.command()
@click.argument("entity_id")
def get_registration(entity_id):
    """
    Get entity registration by id.

    Writes a single JSON file with all information from entity's registration.
    """
    _write_registration_json(entity_id)


@cli.command()
def get_all_registrations():
    """
    Get all entity registrations.

    Writes a single JSON file per entity.
    """
    with open("data/ut_entities.csv") as f:
        for row in csv.DictReader(f):
            print(row)
            _write_registration_json(row["entity_id"], skip_if_exists=True)


@cli.command()
@click.argument("entity_id")
@click.argument("year")
def get_disclosures(entity_id, year):
    """
    Get disclosures by entity_id and year.

    Writes a single CSV per year, using the same fieldnames disclosures.utah.gov does.
    """
    filename = f"data/ut_disclosures_{entity_id}_{year}.csv"
    fieldnames = (
        "CORP",
        "REPORT",
        "TRAN_ID",
        "TRAN_TYPE",
        "TRAN_DATE",
        "TRAN_AMT",
        "INKIND",
        "LOAN",
        "AMENDS",
        "NAME",
        "PURPOSE",
        "ADDRESS1",
        "ADDRESS2",
        "CITY",
        "STATE",
        "ZIP",
        "INKIND_COMMENTS",
    )
    n = 0
    with open(filename, "w") as f:
        writer = csv.DictWriter(f, fieldnames)
        writer.writeheader()
        for row in _fetch_disclosures(entity_id, year):
            n += 1
            writer.writerow(row)
    print(f"wrote {n} to {filename}")


if __name__ == "__main__":
    cli()
