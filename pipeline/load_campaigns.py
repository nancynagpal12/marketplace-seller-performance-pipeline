
import json
from pathlib import Path
from sqlalchemy import text
from pipeline.db import engine
from pipeline.transform import parse_campaign_date
from pipeline import internal_data


def load_campaigns():
    campaign_file = internal_data.INTERNAL_DIR / "campaigns.json"

    with open(campaign_file, "r", encoding="utf-8") as file:
        campaigns = json.load(file)

    def prepare_campaign(campaign):
        date_format = campaign.get("date_format")

        start = parse_campaign_date(
            campaign["start"], date_format
        )

        end = parse_campaign_date(
            campaign["end"], date_format
        )

        if "T" not in campaign["end"]:
            end = end.replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=999999
            )

        return {
            "campaign_id": campaign["campaign_id"],
            "campaign_name": campaign["name"],
            "start_date": start.to_pydatetime(),
            "end_date": end.to_pydatetime(),
            "priority": campaign["priority"],
            "target_states": json.dumps(
                campaign.get("target_states", [])
            ),
            "target_regions": json.dumps(
                campaign.get("target_regions", [])
            ),
            "categories": json.dumps(
                campaign["categories"]
            )
        }

    query = text("""
        INSERT INTO dim_campaign (
            campaign_id,
            campaign_name,
            start_date,
            end_date,
            priority,
            target_states,
            target_regions,
            categories
        )
        VALUES (
            :campaign_id,
            :campaign_name,
            :start_date,
            :end_date,
            :priority,
            :target_states,
            :target_regions,
            :categories
        )
        ON DUPLICATE KEY UPDATE
            campaign_name = VALUES(campaign_name),
            start_date = VALUES(start_date),
            end_date = VALUES(end_date),
            priority = VALUES(priority),
            target_states = VALUES(target_states),
            target_regions = VALUES(target_regions),
            categories = VALUES(categories)
    """)

    records = [prepare_campaign(c) for c in campaigns]

    with engine.begin() as connection:
        connection.execute(query, records)

    print(f"Successfully loaded {len(records)} campaigns.")


if __name__ == "__main__":
    load_campaigns()
