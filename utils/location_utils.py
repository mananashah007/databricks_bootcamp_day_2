import json
from pathlib import Path

data_file = Path("/Workspace/Users/mshah959@gmail.com/databricks_bootcamp_day_2/data/data.json")


def load_location():
    with open(data_file,"r") as f:
        return json.load(f)

def get_location(display_name: str):
    locations = load_location()

    for location in locations:
        if location["display_name"] == display_name:
            return location
    return None

def list_locations():
    return [location["display_name"] for location in load_location()]
