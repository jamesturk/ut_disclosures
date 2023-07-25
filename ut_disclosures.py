#!/usr/bin/env python3

import io
import csv
import json
import time
import glob
from pathlib import Path
import requests
import click
from spatula import HtmlPage, HtmlListPage, CSS, XPath, URL
from dataclasses import dataclass, field, asdict
from flatten_dict import flatten
from lxml import etree
import traceback
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
    folder_id: str
    entity_id: str
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


def _get_report_html(report_id):
    url = f"https://disclosures.utah.gov/Reports/GetReport/{report_id}"
    resp = requests.get(url)
    return resp.text

# def _get_lobbyist_folder(folder_id):
#     url = f'https://lobbyist.utah.gov/Search/PublicSearch/FolderDetails/{folder_id}'
#     resp = requests.get(url)
#     return resp.text

class LobbyistFolder(HtmlPage):

    def get_source_from_input(self):
        return f"https://disclosures.utah.gov/Search/PublicSearch/FolderDetails/{self.input}"

    selector = CSS("ul.dis-reports-list li")

    def process_page(self):
        # metadata is in this iframe
        url = XPath("//iframe[@id='registrationDialogIFrame']/@src").match(self.root)[0]
        
        return EntityMetadata(self.input, source=url)

    # search_url = (
    #     "https://disclosures.utah.gov/Search/AdvancedSearch/GetEntityReportList"
    # )
    
    # source = URL(search_url, method="POST", data={"PageNumber": 1})


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


class LobbyistList(HtmlListPage):

    search_url = (
        'https://lobbyist.utah.gov/Search/PublicSearch/Category/LOBB?showClosed=false'
    )

    source = URL(search_url, method="POST", data={"PageNumber": 1})
    selector = CSS("li")

    def process_item(self, item):
        # print(item.getchildren())
        entity_link = item.getchildren()[0]
        name = entity_link.text_content().strip()
        url = entity_link.get("href")
        folder_id = url.split("/")[-1]
        entity = dict(
            name=name,
            folder_id=folder_id,
            entity_type="lobbyist",
        )
        return entity

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


class EntityPageDetails(HtmlPage):
    """
    connection from the folder details page to the entity metadata page
    """

    # input is an entity ID

    def get_source_from_input(self):
        return f"https://disclosures.utah.gov/Registration/EntityDetails/{self.input}"

    def process_page(self):
        # metadata is in this iframe
        url = self.get_source_from_input()
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
        "Elected or appointed position that the lobbyist holds in state or local government (if any)": "office",
        "CreateDate": "date_created",
        "Types of expenditures for which the lobbyist will be reimbursed": "reimbursement_types",
        "Principal's Name": "principal_name",
        "General Purposes, Interests, and Nature of the Principal": "principal_interests",
    }

    type_mapping = {
        "Political Issues Commitee Statement of Organization": "Political Issues Committee",
        "Financial Disclosures Registration for Corporation": "Corporation",
        "Political Action Committee Statement of Organization": "Political Action Committee",
        "Candidates & Office Holders Statement of Organization": "Candidates & Office Holders",
        "Financial Disclosures Registration for Political Party": "Political Party",
        "Financial Disclosures Registration for Independent Expenditures": "Independent Expenditures",
        "Financial Disclosures Registration for Electioneering": "Electioneering",
        "Financial Disclosures Registration for Lobbyist": "Lobbyist",
    }

    def process_page(self):
        # carry over fields from directory page
        entity = Entity(
            folder_id=self.input,
            source=self.source.url,
            entity_id=self.source.url.split("/")[-1],
        )
        # print(etree.tostring(self.root, pretty_print=True))
        # print(self.root.cssselect('div.fieldset'))
        h1 = CSS("h1").match_one(self.root).text_content()
        entity.type = self.type_mapping[h1]
        try:
            for fieldset in CSS("div.fieldset,fieldset").match(self.root):
                # collect all the data
                # print(etree.tostring(fieldset, pretty_print=True))
                data = {}
                for item in CSS("div.dis-cell label").match(fieldset):
                    if item.text_content() not in self.ENTITY_DATA_MAPPING:
                        print(f'new field: {field}')
                    else:
                        field = self.ENTITY_DATA_MAPPING[item.text_content()]
                        data[field] = item.tail.strip()

                # attach it to the object
                try:
                    # legend = CSS("span.legend").match_one(fieldset).text_content().strip()
                    # print(fieldset.cssselect('span.fieldset,sp'))
                    legend = fieldset.cssselect('legend,span.fieldset')[0].text_content().strip()
                    if legend in (
                        "Corporate Information",
                        "PAC Information",
                        "PIC Information",
                        "Party Information",
                        "Candidate Information",
                        "Independent Expenditures Information",
                        "Electioneer Information",
                        "Lobbyist Information",
                        "Business Information",
                        "Payment Information",
                        "Principals (Clients) for Which the Lobbyist Works or is Hired as an Independent Contractor"
                    ):
                        for k, v in data.items():
                            setattr(entity, k, v)
                    elif legend.startswith("Information about") or legend.startswith(
                        "Personal Campaign Committee"
                    ):
                        person = Person(**data)
                        entity.associated_people.append(person)
                    else:
                        raise ValueError(f"unknown legend {legend}")
                except Exception as e:
                    print(e)
                    print(etree.tostring(fieldset, pretty_print=True))

            return entity
        except Exception as e:
            print('error', e, traceback.print_exc(), self.source.url)
            


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


@cli.command()
def get_lobbyists():
    """
    Get all entities & writes them to ut_entities.csv.
    """
    filename = f"data/ut_lobbyists.csv"
    seen = set()
    with open(filename, "w") as f:
        writer = csv.DictWriter(f, ("folder_id", "entity_type", "name"))
        writer.writeheader()
        for item in LobbyistList().do_scrape():
            if item["folder_id"] in seen:
                break
            seen.add(item["folder_id"])
            writer.writerow(item)
    print(f"wrote {len(seen)} to {filename}")


@cli.command()
def get_lobbyist_folders():
    """
    Get all entities & writes them to ut_entities.csv.
    """
    filename = f"data/ut_lobbyists.csv"
    seen = set()
    with open(filename, "r") as f:
        reader = csv.DictReader(f, ("folder_id", "entity_type", "name") )
        i = 0
        for row in reader:
            if i > 1:
                # print(i, row)
                try:
                    for report in LobbyistFolder(row['folder_id']).do_scrape():
                        print(report)
                        pass
                except Exception as e:
                    pass
            i += 1
            # if i == 0:
            #     continue
            # else:
            #     i += 1
            #     print(row)
            

    #     writer = csv.DictWriter(f, ("folder_id", "entity_id", "entity_type", "name"))
    #     writer.writeheader()
    #     for item in LobbyistFolderList().do_scrape():
    #         if item["folder_id"] in seen:
    #             break
    #         seen.add(item["folder_id"])
    #         writer.writerow(item)
    # print(f"wrote {len(seen)} to {filename}")

def _write_registration_json(entity_id, skip_if_exists=False):
    filename = f"data/ut_registration_{entity_id}.json"
    if skip_if_exists and Path(filename).exists():
        print(f"{filename} already exists")
    else:
        item = list(EntityPageDetails(entity_id).do_scrape())
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
            try:
                _write_registration_json(row["entity_id"], skip_if_exists=True)
            except Exception as e:
                print(f"failed on {row['entity_id']} - {e}")



@cli.command()
@click.argument("entity_id")
@click.argument("year")
def get_disclosures(entity_id, year):
    """
    Get disclosures by entity_id and year.

    Writes a single CSV per year, using the same fieldnames disclosures.utah.gov does.
    """
    click.echo((entity_id, year))
    filename = f"data/ut_disclosures_{entity_id}_{year}.csv"
    fieldnames = (
        "PCC",
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
            writer.writerow({k: row.get(k) for k in fieldnames})
    print(f"wrote {n} to {filename}")


@cli.command()
@click.argument("start_year", type=int)
@click.argument("end_year", type=int)
@click.pass_context
def get_all_disclosures(ctx, start_year: int, end_year:int=2022):
    """
    Get all disclosures by entity_id.

    Writes a single CSV per year, using the same fieldnames disclosures.utah.gov does.
    """
    with open("data/ut_entities.csv") as f:
        for row in csv.DictReader(f):
            print(row)
            try:
                for year in range(start_year, end_year+ 1):
                    print(f'getting disclosures for {row["entity_id"]} in {year}')
                    # get_disclosures(str(row["entity_id"]), str(year))
                    ctx.invoke(get_disclosures, entity_id=row["entity_id"], year=year)
            except Exception as e:
                print(f"{e} failed on {row['entity_id']}")
   

@cli.command()
def consolidate_files():
    """
    Consolidate all disclosures into a single CSV file.
    """
    disclosure_fields = (
        "ENTITY_ID",
        "PCC",
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
        "INKIND_COMMENTS"
    )

    with open("data/ut_disclosures.csv", "w") as f:
        writer = csv.DictWriter(f, disclosure_fields)
        writer.writeheader()
        for file in glob.glob('data/ut_disclosures_*'):
            print(file)
            with open(file) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    writer.writerow(
                        {**{k: row.get(k) for k in disclosure_fields},**{"ENTITY_ID": file.split('_')[2]}}
                    )
    

    registration_fields = (
        'entity_id',
        'date_created',
        'affiliated_organization',
        'phone',
        # 'associated_people',
        'ballot_proposition',
        'ballot_position',
        'state',
        'source',
        'name',
        'folder_id',
        'address1',
        'address2',
        'city',
        'zipcode',
        'type',
        'aka'
    )

    fields = set()
    people = []
    with open("data/ut_registrations.csv", "w") as f:
        writer = csv.DictWriter(f, registration_fields)
        writer.writeheader()
        for file in glob.glob('data/ut_registration_*'):
            print(file)
            with open(file) as f:
                obj = json.load(f)
                for person in obj['associated_people']:
                    person['entity_id'] = obj['entity_id']
                    people.append(person)
                fields.update(flatten(obj, reducer='underscore').keys())
                writer.writerow(
                    {k: obj.get(k) for k in registration_fields}
                )

    person_fields = (
        'entity_id',
        'party',
        'occupation',
        'office',
        'title',
        'first',
        'middle',
        'last',
        'suffix',
        'address1',
        'address2',
        'state'
        'phone',
        'email',
        'zipcode',
        'district_number',
        
    )

    # fields = set()

    with open("data/ut_people.csv", "w") as f:
        writer = csv.DictWriter(f, person_fields)
        writer.writeheader()
        for person in people:
            writer.writerow({k: person.get(k) for k in person_fields})

    # click.echo(fields)

    # for file in glob.glob('data/ut_registration*.json'):
    #     print(file)
    #     with open(file) as f:
    #         data = json.load(f)
    #         registration_fields.update(data.keys())
    
    # click.echo(registration_fields)
    # with open("data/ut_registrations.csv") as f:
    #     writer = csv.DictWriter(f, fieldnames)

    
    # n = 0
    # with open("data/ut_disclosures.csv", "w") as f:
    #     writer = csv.DictWriter(f, fieldnames)
    #     writer.writeheader()
    #     for filename in Path("data").glob("ut_disclosures_*.csv"):
    #         print(f"reading {filename}")
    #         with open(filename) as f:
    #             reader = csv.DictReader(f)
    #             for row in reader:
    #                 n += 1
    #                 writer.writerow(row)
    # print(f"wrote {n} to data/ut_disclosures.csv")

if __name__ == "__main__":
    cli()
